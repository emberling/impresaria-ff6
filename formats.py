from messenger import OPT, log, std, err

class G():
    MAPPING_MODES = {
        0x20: "LoROM",
        0x21: "HiROM",
        0x23: "SA-1",
        0x30: "LoROM+FastROM",
        0x31: "HiROM+FastROM",
        0x32: "ExLoROM",
        0x35: "ExHiROM"
        }
    
    SHADOW_HACK_ADDRESS = 0x50B05
    SHADOW_HACK_ON =  b"\x78\xFF\xC5\xF0\x19\x68\xE2\xD0\x03\x8F\xFF\xC5\x68\xE3\xD0\x05\x3F\x25\x17\x2F\xD4\x68\xF5\xD0\x05\x3F\x95\x16\x2F\xCB\x68\xE5\xD0\x05\x3F\xCF\x15\x2F\xC2\x68\xE7\xD0\x0B\x3F\xF3\x15\x2F\xB9\x00\x00\x00\x00\x00\x00"
    SHADOW_HACK_OFF = b"\x68\xE3\xD0\x05\x3F\x25\x17\x2F\xE0\x68\xF5\xD0\x05\x3F\x95\x16\x2F\xD7\x68\xE5\xD0\x05\x3F\xCF\x15\x2F\xCE\x68\xE7\xD0\x05\x3F\xF3\x15\x2F\xC5\x68\xE9\xD0\x05\x3F\x33\x16\x2F\xBC\x68\xEA\xD0\x05\x3F\x39\x16\x2F\xB3"

    BRR_ID = "AA-brr"
    LOOP_ID = "AB-loop"
    PITCH_ID = "AC-pitch"
    ENV_ID = "AD-env"
    SEQ_ID = "AE-seq"
    INST_ID = "AF-inst"
    
    AUDIO_BUFFER = 1024

def from_rom_address(addr):
    # NOTE ROM offset 7E0000-7E7FFF and 7F000-7F7FFF are inaccessible.
    # This is not handled by this program and it will treat them like 7E8000, etc
    if addr >= 0xC00000:
        addr -= 0xC00000
    elif addr < 0x400000 and addr >= 0x3E0000:
        addr += 0x400000
    return addr
    
def to_rom_address(addr):
    if addr < 0x400000:
        addr += 0xC00000
    elif addr >= 0x7E0000 and addr < 0x800000:
        addr -= 0x400000
    return addr

def byte_insert(data, position, newdata, maxlength=0, end=0):
    while position > len(data):
        data += (b"\x00" * (position - len(data)))
    if end:
        maxlength = end - position + 1
    if maxlength and len(data) > maxlength:
        newdata = newdata[:maxlength]
    return data[:position] + newdata + data[position + len(newdata):]

def int_insert(data, position, newdata, length, reversed=True):
    n = int(newdata)
    l = []
    while len(l) < length:
        l.append(n & 0xFF)
        n = n >> 8
    if n:
        log.send(f"WARNING: tried to insert {hex(newdata)} into ${length:X} bytes, truncated")
    if not reversed: l.reverse()
    return byte_insert(data, position, bytes(l), length)
    
def clamp(min, val, max):
    if min > max:
        std.send(f"warning: reverse clamp f{min}, f{val}, f{max}")
        min, max = max, min
    if val < min:
        val = min
    if val > max:
        val = max
    return val
    
def load_rom_data_block(rom, offset, seq=False):
    length = int.from_bytes(rom[offset:offset+2], "little")
    if seq:
        length += 2
    data = rom[offset+2 : offset+2+length]
    if seq and OPT.trim_sequence_ends:
        data = trim_sequence_ends(data)
    return data
    
def file_read(fn, bin=False, **kwargs):
    mode = "rb" if bin else "r"
    if not bin:
        kwargs["encoding"] = "utf-8"
    try:
        with open(fn, mode) as f:
            dat = f.read()
        return dat
    except IOError:
        err.send(f"I/O error: could not read file {fn}")
        return None
            
def trim_sequence_ends(seq):
    # The driver's sequence loading code loads one or two extra bytes
    # vs. the specified size. If we don't load them, some sequences
    # lose data. If we do load them, we get random extra garbage at
    # the end of most sequences. This function looks at the ends of
    # sequences and tries to identify and remove that garbage without
    # removing anything load-bearing.
    
    # Basic logic is that any segment that doesn't eventually end with
    # EB (end track), F6 (unconditional jump), or E3 (end loop) is going
    # to at some point stray into arbitrary/uninitialized memory, so that's
    # probably unused data.
    
    max_trim_amount = 6
    end_codes = {
        0xEB: 1,
        0xE3: 1,
        0xF6: 3,
        0xF5: 4,
        0xFC: 3
        }
    for trim in range(0, max_trim_amount):
        code = seq[-1 - trim]
        if code in end_codes:
            bytes_to_trim = trim - end_codes[code] + 1
            if bytes_to_trim == 0:
                return seq
            elif bytes_to_trim > 0:
                return seq[:-bytes_to_trim]
    return seq
            
def create_rom_data_block(data):
    if len(data) > 0x10000:
        err.send("Invalid data block (${len(data):X} bytes)")
        return b""
    return len(data).to_bytes(2, "little") + data
 
class GameFormat():
    def __init__(self, id, display_name):
        self.id = id
        self.display_name = "EmptyFormat"
        self.scanner_data = b"placeholder"

        self.asm_inst_table_address =   0
        self.asm_brr_pointer_address =  0
        self.asm_brr_loop_address =     0
        self.asm_brr_pitch_address =    0
        self.asm_brr_env_address =      0
        self.asm_seq_pointer_address =  0
        self.spc_engine_address =       0
        self.global_edl_address =       0
        self.spc_static_brr_address =   0
        self.spc_static_ptr_address =   0
        self.spc_static_env_address =   0
        self.spc_static_pitch_address = 0
        self.sequence_count_address =   0
        
        self.valid_map_modes = set((0x31, 0x35))
        self.original_romsize = 0
        
        self.default_track_names = {}
        
FORMATS = {}

FORMATS["ff6"] = GameFormat("ff6", "AKAO4 / Final Fantasy VI")
FORMATS["ff6"].scanner_address = 0x50720
FORMATS["ff6"].scanner_data = b"\x00\x8D\x0C\x3F\x48\x06\x8D\x1C" + \
                              b"\x3F\x48\x06\x8D\x2C\x3F\x48\x06"
FORMATS["ff6"].asm_inst_table_address =   0x501E3
FORMATS["ff6"].asm_brr_pointer_address =  0x50222
FORMATS["ff6"].asm_brr_loop_address =     0x5041C
FORMATS["ff6"].asm_brr_pitch_address =    0x5049C
FORMATS["ff6"].asm_brr_env_address =      0x504DE
FORMATS["ff6"].asm_seq_pointer_address =  0x50539
FORMATS["ff6"].spc_engine_address =       0x5070E
FORMATS["ff6"].global_edl_address =       0x5076A
FORMATS["ff6"].spc_static_brr_address =   0x51EC7
FORMATS["ff6"].spc_static_ptr_address =   0x52016
FORMATS["ff6"].spc_static_env_address =   0x52038
FORMATS["ff6"].spc_static_pitch_address = 0x5204A
FORMATS["ff6"].sequence_count_address =   0x53C5E
FORMATS["ff6"].brr_spc_ram_address =      0x4800

FORMATS["ff6"].default_track_names = {
    0x00: "(silence)",
    0x01: "The Prelude (FF6)",
    0x02: "Omen, part 1",
    0x03: "Omen, part 2",
    0x04: "Omen, part 3",
    0x05: "Awakening",
    0x06: "Terra's Theme",
    0x07: "Shadow's Theme",
    0x08: "Strago's Theme",
    0x09: "Gau's Theme",
    0x0A: "Edgar & Sabin's Theme",
    0x0B: "Coin of Fate",
    0x0C: "Cyan's Theme",
    0x0D: "Locke's Theme",
    0x0E: "Forever Rachel",
    0x0F: "Relm's Theme",
    0x10: "Setzer's Theme",
    0x11: "Epitaph",
    0x12: "Celes's Theme",
    0x13: "Techno de Chocobo",
    0x14: "The Decisive Battle (FF6)",
    0x15: "Johnny C. Bad",
    0x16: "Kefka's Theme",
    0x17: "The Mines of Narshe",
    0x18: "Phantom Forest",
    0x19: "The Veldt",
    0x1A: "Protect the Espers!",
    0x1B: "The Gestahl Empire",
    0x1C: "Troops March On",
    0x1D: "Under Martial Law",
    0x1E: "(water flowing, FF6)",
    0x1F: "Metamorphosis",
    0x20: "Phantom Train",
    0x21: "Esper World",
    0x22: "Grand Finale",
    0x23: "Mt. Koltz",
    0x24: "Battle (FF6)",
    0x25: "(slow fanfare, FF6)",
    0x26: "Wedding Waltz, part 1",
    0x27: "Aria Di Mezzo Carattere",
    0x28: "The Serpent Trench",
    0x29: "Slam Shuffle",
    0x2A: "Kids Run Through the City",
    0x2B: "What? (FF6)",
    0x2C: "(crowd noise, FF6)",
    0x2D: "Gogo's Theme",
    0x2E: "The Returners",
    0x2F: "Victory Fanfare (FF6)",
    0x30: "Umaro's Theme",
    0x31: "Mog's Theme",
    0x32: "The Unforgiven",
    0x33: "Battle to the Death (FF6)",
    0x34: "From That Day On...",
    0x35: "The Airship Blackjack",
    0x36: "Catastrophe",
    0x37: "The Magic House",
    0x38: "(good night, FF6)",
    0x39: "(wind, FF6)",
    0x3A: "(waves, FF6)",
    0x3B: "Dancing Mad, parts 1-3",
    0x3C: "(train stopping, FF6)",
    0x3D: "Spinach Rag",
    0x3E: "Rest in Peace (FF6)",
    0x3F: "(chocobos running, FF6)",
    0x40: "(walking out of zozo)",
    0x41: "Overture, part 1",
    0x42: "Overture, part 2",
    0x43: "Overture, part 3",
    0x44: "Wedding Waltz, part 2",
    0x45: "Wedding Waltz, part 3",
    0x46: "Wedding Waltz, part 4",
    0x47: "Devil's Lab",
    0x48: "(esper attack)",
    0x49: "(cranes, FF6)",
    0x4A: "(burning house, FF6)",
    0x4B: "Floating Continent",
    0x4C: "Searching for Friends",
    0x4D: "The Fanatics",
    0x4E: "Kefka's Tower",
    0x4F: "Dark World",
    0x50: "Dancing Mad, part 5",
    0x52: "Dancing Mad, part 4",
    0x53: "Balance is Restored, part 1",
    0x54: "Balance is Restored, part 2"
    }