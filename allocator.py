class AllocRange():
    def __init__(self, start, end=None, length=1):
        self.start = start
        self.end = start + length - 1 if end is None else end
        self.length = self.end - self.start + 1
        if not self.length:
            self.start = None
            self.end = None
            self.length = 0
        
    def contains(self, addr):
        return self.start <= addr <= self.end
        
    def intersects(self, other):
        return self.contains(other.start) or self.contains(other.end) or other.contains(self.start) or other.contains(self.end)
        
    def __add__(self, other):
        first_start = min(self.start, other.start)
        last_start = max(self.start, other.start)
        first_end = min(self.start, other.start)
        last_end = max(self.start, other.start)
        
        if (first_end + 1) < last_start:
            return [self, other]
        else:
            return [AllocRange(first_start, last_end)]
            
    def __sub__(self, other):
        fragments = []
        if self.contains(other.start):
            fragments.append(AllocRange(self.start, other.start - 1))
        if self.contains(other.end):
            fragments.append(AllocRange(other.end + 1, self.end))
        fragments = [frag for frag in fragments if frag.length > 0]
        if len(fragments) > 1:
            return fragments[0] + fragments[1]
        elif len(fragments) > 0:
            return fragments
        elif other.contains(self.start):
            return []
        else:
            return [self]
            
    def __repr__(self):
        return f"(( {self.start:06X} ~~ {self.end:06X} ))"
                    
class Allocator():
    # FORBIDDEN ranges are unusable at all times (e.g. bank 0/40)
    # UNHANDLED or RELEASED ranges will not be affected by this allocator
    # HANDLED ranges can hold data using this allocator
    # those will contain FREE and USED ranges
    MAX_VALUE = 0x7FFFFF
    FORBIDDEN = [
                 AllocRange(0,        length=0x10000),
                 AllocRange(0x050000, length=0x3C5F),
                 AllocRange(0x400000, length=0x10000),
                 AllocRange(0x7E0000, length=0x8000),
                 AllocRange(0x7F0000, length=0x8000)
                ]
                
    def __init__(self):
        self.ranges = []
        # Blocks - maps unique data block with multiple indexes (GC when empty)
        # Index - maps unique index with corresponding data block
        # Addresses - keys should be kept identical to Index. caches addresses
        #             data blocks would have when the ROM is built.
        self.data_blocks = {}
        self.data_index = {}
        
        self.data_is_packed = False
        
        # These attributes depend on allocate_data() to be accurate
        # and should not be accessed externally, only through a getter function
        # that checks data_is_packed.
        self.data_addresses = {}
        self.range_blocks = {}
        self.ranges_by_start_addr = {}
        self.out_of_room = False
        
    def add(self, start_or_range, end=None, length=1):
        if isinstance(start_or_range, AllocRange):
            range = start_or_range
        else:
            range = AllocRange(start_or_range, end, length)
        self.ranges.append(range)
        self.crunch()

    def add_multi(self, new_ranges):
        self.ranges.extend(new_ranges)
        self.crunch()
        
    def release(self, start_or_range, end=None, length=1):
        if isinstance(start_or_range, AllocRange):
            release_range = start_or_range
        else:
            release_range = AllocRange(start_or_range, end, length)
        ranges = []
        for r in self.ranges:
            result = r - release_range
            ranges.extend(result)
        self.ranges = ranges
        self.data_is_packed = False
            
    # Function to handle merging overlapping ranges and
    # trimming forbidden ranges.
    def crunch(self):
        # First, forbidden ranges are trimmed, because subtraction during the
        # merge check would muck up the sorting if one range got split into 2.
        ranges = []
        for r in self.ranges:
            if r.start > self.MAX_VALUE:
                continue
            r.end = min(self.MAX_VALUE, r.end)
            result = None
            for f in self.FORBIDDEN:
                result = r - f
                if not result:
                    break
                if len(result) > 1:
                    self.ranges.extend(result[1:])
                r = result[0]
            if not result:
                continue
            ranges.append(r)
        if not ranges:
            return
        # Sort and merge
        self.ranges = []
        ranges = sorted(ranges, key=lambda x: (x.start, x.end))
        start, end = ranges[0].start, ranges[0].end
        for r in ranges:
            if r.start > end + 1:
                self.ranges.append(AllocRange(start, end))
                start = r.start
            end = max(end, r.end)
        self.ranges.append(AllocRange(start, end))
        self.data_is_packed = False

    def set_data(self, id, data):
        """
        Add or change a data bytestring managed by this allocator.
        Data blocks left without index pointers will be garbage collected.
        If data is None, removes the index pointer id from the allocator.
        """
        data = bytes(data)
        if id in self.data_index:
            old_data = self.data_index[id]
            self.data_blocks[old_data].remove(id)
            if not len(self.data_blocks[old_data]):
                del self.data_blocks[old_data]
        if data is None:
            del self.data_index[id]
        else:
            self.data_index[id] = data
            if data in self.data_blocks:
                self.data_blocks[data].append(id)
            else:
                self.data_blocks[data] = [id]
        self.data_is_packed = False
    
    def allocate_data(self):
        """
        Distribute data into data blocks (self.range_blocks).
        This must be called for any free space or final data
        requests to be accurate. Keys are range start addresses.
        Any data that could not be packed (not enough free space)
        will be collected in key None.
        """
        if self.data_is_packed:
            return
        self.out_of_room = False
        self.data_addresses = {}
        sorted_data = sorted(self.data_blocks.items(), key=lambda x: min(x[1]))
        range_bin = {r.start: bytearray() for r in self.ranges}
        for bin, ids in sorted_data:
            allocated = False
            for range in self.ranges:
                if len(bin) <= (range.length - len(range_bin[range.start])):
                    addr = range.start + len(range_bin[range.start])
                    range_bin[range.start] += bin
                    allocated = True
                    for id in ids:
                        self.data_addresses[id] = addr
                    break
            if not allocated:
                self.out_of_room = True
                if None not in range_bin:
                    range_bin[None] = bytearray()
                range_bin[None] += bin
        self.range_blocks = range_bin
        self.ranges_by_start_addr = {r.start: r for r in self.ranges}
        self.data_is_packed = True    
        
        #print("sorted data:")
        #for bin, ids in sorted_data:
        #    print(f"    {min(ids)} - full ids {ids} - data len {len(bin):4X} - addr $" +
        #            (f"{self.data_addresses[ids[0]]:06X}" if ids[0] in self.data_addresses else "None"))
            
    def get_space_usage(self, r_start):
        """
        Retrieve the amount of used and free space
        in the data block beginning at r_start.
        """
        if not self.data_is_packed:
            self.allocate_data()
        if r_start is None:
            return (len(self.range_blocks[None]), 0)
        range = self.ranges_by_start_addr[r_start]
        used = len(self.range_blocks[range.start])
        free = range.length - used
        return (used, free)
        
    def repr_total_usage(self):
        if not self.data_is_packed:
            self.allocate_data()
        used, free = 0, 0
        maxfree = 0
        for range in self.ranges:
            u, f = self.get_space_usage(range.start)
            used += u
            free += f
            maxfree = max(maxfree, f)
        if self.out_of_room:
            used += len(self.range_blocks[None])
            text = (f"${used:X} bytes used\n"
                    f"**WARNING** Not enough space!\n"
                    f"Unplaced data: ${len(self.range_blocks[None]):X} bytes\n"
                    f"largest free block open: ${maxfree:X} bytes")
        else:
            text = (f"${used:X} bytes used\n"
                    f"${free:X} bytes available\n"
                    f"largest free block open: ${maxfree:X} bytes")
        return text
        
    def get_address(self, id):
        if not self.data_is_packed:
            self.allocate_data()
        try:
            return self.data_addresses[id]
        except KeyError:
            return None
        
    def get_all_data(self):
        if not self.data_is_packed:
            self.allocate_data()
        return self.range_blocks
