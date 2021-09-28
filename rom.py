from formats import G, FORMATS, file_read, from_rom_address, load_rom_data_block
from sequence import Sequence
from sample import Sample, Envelope
from messenger import log, std, err, vblank

roms = {}

class Rom():
    def __init__(self, fn, data=None):
        self.init_status = False
        self._seq_init = 0
        self._fixed_brr_init = 0
        self._brr_init = 0
        
        self.max_brr = 255
        self.is_valid = False
        if not data:
            data = file_read(fn, bin=True)
        if data:
            self.format, self.header, data = self.identify_format(data)
            if self.format and len(data) >= self.format.original_romsize:
                self.is_valid = True
                self.identify_mapping_mode(data)
                
                # TODO this actually uses JIS X 201, which shares much with ASCII
                # but includes kana in high bytes. Needs custom decoder though.
                # If LoROM ever becomes relevant, that also needs a different
                # address for this.
                self.rom_name = data[0xFFC0:0xFFD5].decode('latin-1')
                
                self.banks = len(data) // 0x10000 + (len(data) % 0x10000 > 0)
                self.identify_edl(data)
                self.identify_shadow(data)
                self.locate_tables(data)
                self.seq_count = data[self.format.sequence_count_address]
                
                self.seq = {}
                self.brr = {}
                
                self.fn = fn
                roms[fn] = data
            
    def identify_format(self, data):
        for format in FORMATS.values():
            address = format.scanner_address
            end = address + len(format.scanner_data)
            if data[address:end] == format.scanner_data:
                log.queue(f"Found format {format.id}, no header.")
                return format, None, data
            elif data[address+0x200:end+0x200] == format.scanner_data:
                log.queue(f"Found format {format.id}, with header.")
                return format, data[:0x200], data[0x200:]
            else:
                log.send(f"ERROR: Unrecognized ROM format.")
                return None, None, data
    
    def identify_mapping_mode(self, data):
        modebyte = data[0xFFD5]
        modetext = G.MAPPING_MODES[modebyte] if modebyte in G.MAPPING_MODES else f"${modebyte:02X}"
        log.queue(f"Memory mapping mode is {modetext}.")
        if modebyte not in self.format.valid_map_modes:
            log.queue(f"(invalid).")
            self.invalid = True
        self.mapping_mode = modebyte
        self.mapping_mode_name = modetext
            
    def identify_edl(self, data):
        edl = data[self.format.global_edl_address]
        if edl > 15:
            log.queue(f"Invalid EDL detected at {edl}, reverting to 5.")
            edl = 5
        else:
            log.queue(f"EDL is {edl}.")
        self.edl = edl
        
    def identify_shadow(self, data):
        self.shadowfix = False
        if self.format.id == "ff6":
            addr = G.SHADOW_HACK_ADDRESS
            end = addr + len(G.SHADOW_HACK_ON)
            if data[addr:end] == G.SHADOW_HACK_ON:
                self.shadowfix = True
            log.queue(f"Shadow hack is {'enabled' if self.shadowfix else 'disabled'}.")
            
    def locate_tables(self, data):
        loc = self.format.asm_seq_pointer_address
        self.seq_table_address = from_rom_address(int.from_bytes(data[loc:loc+3], "little"))
        loc = self.format.asm_inst_table_address
        self.inst_table_address = from_rom_address(int.from_bytes(data[loc:loc+3], "little"))
        loc = self.format.asm_brr_pointer_address
        self.brr_table_address = from_rom_address(int.from_bytes(data[loc:loc+3], "little"))
        loc = self.format.asm_brr_loop_address
        self.loop_table_address = from_rom_address(int.from_bytes(data[loc:loc+3], "little"))
        loc = self.format.asm_brr_pitch_address
        self.pitch_table_address = from_rom_address(int.from_bytes(data[loc:loc+3], "little"))
        loc = self.format.asm_brr_env_address
        self.env_table_address = from_rom_address(int.from_bytes(data[loc:loc+3], "little"))
        
        self.truncate_max_brr(self.seq_table_address)
        self.truncate_max_brr(self.inst_table_address)
        self.truncate_max_brr(self.brr_table_address)
        self.truncate_max_brr(self.loop_table_address)
        self.truncate_max_brr(self.pitch_table_address)
        self.truncate_max_brr(self.env_table_address)
        self.truncate_max_brr(self.format.spc_engine_address)
        self.truncate_max_brr(self.format.spc_static_brr_address)
        self.truncate_max_brr(self.format.spc_static_ptr_address)
        self.truncate_max_brr(self.format.spc_static_env_address)
        self.truncate_max_brr(self.format.spc_static_pitch_address)
        self.truncate_max_brr(self.format.sequence_count_address)
        log.send(f"max_brr on init: {self.max_brr}")
        
    def truncate_max_brr(self, next_data_address):
        tests = [(self.brr_table_address, 3),
                 (self.loop_table_address, 2),
                 (self.pitch_table_address, 2),
                 (self.env_table_address, 2)
                ]
        for taddr, entrysize in tests:
            if next_data_address > taddr:
                self.max_brr = min(self.max_brr, (next_data_address - taddr) // entrysize)
            
    # This starts/continues the second distinct initialization pass.
    # Won't be called on temp files and the like that don't need it.
    # Optionally, an Allocator object can be passed and fed each of these
    # objects' locations as "usable space".
    def frame_init(self, alloc=None):
        #while vblank.ok and self.init_status is not True:
        if self.init_status is not True:
            if self._seq_init is not True:
                sequences = self.seq
                loc = self.seq_table_address
                stbl = self.rom()[loc:loc+(self.seq_count*3)]
                loc = self.inst_table_address
                itbl = self.rom()[loc:loc+(self.seq_count*0x20)]
                
                i = self._seq_init
                goal = self.seq_count - 1

                seq_addr = from_rom_address(int.from_bytes(stbl[i*3:i*3+3], "little"))
                inst = itbl[i*0x20:i*0x20+0x20]
                seq = load_rom_data_block(self.rom(), seq_addr, seq=True)
                seqobj = Sequence(seq, inst, source=("rom", (i, seq_addr)))
                sequences[i] = seqobj
                self.truncate_max_brr(seq_addr)
                if alloc:
                    alloc.add(seq_addr, length = len(seq) + 2)
                    alloc.set_data(f"seq{i:02X}", seqobj.get_data())

                self._seq_init = True if i == goal else i+1
                self.seq = sequences
                
            elif self._fixed_brr_init is not True:
                brrs = load_rom_data_block(self.rom(), self.format.spc_static_brr_address)
                ptrs = load_rom_data_block(self.rom(), self.format.spc_static_ptr_address)
                envs = load_rom_data_block(self.rom(), self.format.spc_static_env_address)
                pits = load_rom_data_block(self.rom(), self.format.spc_static_pitch_address)
                
                i = self._fixed_brr_init
                goal = (len(ptrs) // 4) - 1
                ptr = int.from_bytes(ptrs[i*4:i*4+2], "little")
                loop = int.from_bytes(ptrs[i*4+2:i*4+4], "little") - ptr
                ptr -= self.format.brr_spc_ram_address
                endptr = int.from_bytes(ptrs[i*4+4:i*4+6], "little") - self.format.brr_spc_ram_address
                if i == goal:
                    endptr = len(brrs)
                # TODO - assumption is made here that samples are stored in order, may not always be
                # the case?
                brr = brrs[ptr:endptr]
                pitch = int.from_bytes(pits[i*2:i*2+2], "big", signed=True)
                env = Envelope(bin=envs[i*2:i*2+2])
                
                samp = Sample(brr, loop, pitch, env, id=f"@{i:X}")
                samp.set_source("rom_fixed", (i, ptr + self.format.spc_static_brr_address + 2))
                #self.brr[f"@{i:X}"] = samp                    
                self.brr[i+256] = samp
                
                self._fixed_brr_init = True if i == goal else i+1
                self._brr_init = 0 if i == goal else f"@{i:X}"
            elif self._brr_init is not True:
                
                samples = self.brr
                loc = self.brr_table_address
                btbl = self.rom()[loc:loc+(self.max_brr*3)]
                loc = self.loop_table_address
                ltbl = self.rom()[loc:loc+(self.max_brr*2)]
                loc = self.pitch_table_address
                ptbl = self.rom()[loc:loc+(self.max_brr*2)]
                loc = self.env_table_address
                etbl = self.rom()[loc:loc+(self.max_brr*2)]
            
                i = self._brr_init
                goal = self.max_brr - 1

                brr_addr = from_rom_address(int.from_bytes(btbl[i*3:i*3+3], "little"))
                if brr_addr == 0 or brr_addr % 0x10000 == 0xFFFF or brr_addr > len(self.rom()):
                    samples[i+1] = Sample()
                else:
                    brr = load_rom_data_block(self.rom(), brr_addr)
                    loop = int.from_bytes(ltbl[i*2:i*2+2], "little")
                    pitch = int.from_bytes(ptbl[i*2:i*2+2], "big", signed=True)
                    env = Envelope(bin=etbl[i*2:i*2+2])
                    samp = Sample(brr, loop, pitch, env, id=i+1)
                    samp.set_source("rom", (i+1, brr_addr))
                    samples[i+1] = samp
                    if alloc:
                        alloc.add(brr_addr, length = len(brr) + 2)
                        alloc.set_data(f"brr{i+1:02X}", samp.get_data())

                self._brr_init = True if i == goal else i+1
                self.brr = samples
            if self._brr_init is True:
                if alloc:
                    sequences = self.seq
                    loc = self.seq_table_address
                    stbl = self.rom()[loc:loc+(self.seq_count*3)]
                    loc = self.inst_table_address
                    itbl = self.rom()[loc:loc+(self.seq_count*0x20)]
                    tableinfo = [
                        (self.seq_table_address, stbl, G.SEQ_ID),
                        (self.inst_table_address, itbl, G.INST_ID),
                        (self.brr_table_address, btbl, G.BRR_ID),
                        (self.loop_table_address, ltbl, G.LOOP_ID),
                        (self.pitch_table_address, ptbl, G.PITCH_ID),
                        (self.env_table_address, etbl, G.ENV_ID)
                        ]
                    for addr, table, id in tableinfo:
                        alloc.add(addr, length=len(table))
                        alloc.set_data(id, table)
                self.init_status = True
                return True
        retstring = "Located ROM data tables."
        if self._seq_init is True:
            retstring += "\nSequences loaded."
            retstring += f"\nProcessing sample {self._brr_init} of {self.max_brr}"
        else:
            retstring += f"\nProcessing sequence {self._seq_init} of {self.max_brr}"
        return retstring
        
    def rom(self):
        return roms[self.fn]
        