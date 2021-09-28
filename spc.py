# TODO make this cross platform
# (startfile is windows only and produces obscure errors on linux)
from os import startfile
from pathlib import Path
from copy import copy

import pygame
import imgui

import snesapu.snesapu as snesapu

from formats import G, load_rom_data_block, byte_insert, int_insert, FORMATS
from messenger import std, err, log

dat_dir = Path(__file__).resolve().parent / "res"
SPC_WORK_RAM_FILE = dat_dir / "spc_work_ram.bin"
SPC_AUX_RAM_FILE = dat_dir / "spc_aux_ram.bin"

def build_spc(prj, seqid):
    rom = prj.src.rom()
    format = FORMATS["ff6"]
    seq = prj.seq[seqid]
    
    with open(SPC_WORK_RAM_FILE, "rb") as f:
        work_ram = f.read()
    with open(SPC_AUX_RAM_FILE, "rb") as f:
        aux_ram = f.read()
    
    spc = bytearray(0x10100)
    header = work_ram[:0x100]
    
    spc = byte_insert(spc, 0, work_ram[0x100:0x300])
    spc = byte_insert(spc, 0x200, load_rom_data_block(rom, format.spc_engine_address))
    
    static_brr_data = load_rom_data_block(rom, format.spc_static_brr_address)
    static_brr_ptr = load_rom_data_block(rom, format.spc_static_ptr_address)
    static_brr_env = load_rom_data_block(rom, format.spc_static_env_address)
    static_brr_pitch = load_rom_data_block(rom, format.spc_static_pitch_address)
    
    free_brr_offset = 0x4800 + len(static_brr_data)
    
    all_brr_data = bytearray(static_brr_data)
    dyn_brr_ptr = bytearray(0x40)
    dyn_brr_env = bytearray(0x20)
    dyn_brr_pitch = bytearray(0x20)
    
    for i in range(16):
        inst_id = seq.inst[i]
        if inst_id:
            brr_loop = prj.brr[inst_id].loop
            brr_env = prj.brr[inst_id].env.bytes()
            brr_pitch = prj.brr[inst_id].pitch.to_bytes(2, "big", signed=True)
            inst_brr_data = prj.brr[inst_id].data
            
            dyn_brr_ptr = int_insert(dyn_brr_ptr, 4 * i, free_brr_offset, 2)
            dyn_brr_ptr = int_insert(dyn_brr_ptr, 4 * i + 2, free_brr_offset + brr_loop, 2)
            dyn_brr_env = byte_insert(dyn_brr_env, 2 * i, brr_env, 2)
            dyn_brr_pitch = byte_insert(dyn_brr_pitch, 2 * i, brr_pitch, 2)
            all_brr_data += inst_brr_data
            free_brr_offset = 0x4800 + len(all_brr_data)
            
    meta = bytearray(0x200)
    meta = byte_insert(meta, 0x000, static_brr_pitch)
    meta = byte_insert(meta, 0x040, dyn_brr_pitch)
    meta = byte_insert(meta, 0x080, static_brr_env)
    meta = byte_insert(meta, 0x0C0, dyn_brr_env)
    meta = byte_insert(meta, 0x100, static_brr_ptr)
    meta = byte_insert(meta, 0x180, dyn_brr_ptr)
    
    spc = byte_insert(spc, 0x1A00, meta)
    spc = byte_insert(spc, 0x4800, all_brr_data)
    
    seqdata = seq.data + b"\xEB"
    spc = byte_insert(spc, 0x1C00, seqdata)
    
    address_base = int.from_bytes(seqdata[0:2], "little")
    script_offset = 0x11C24 - address_base
    while script_offset >= 0x10000:
        script_offset -= 0x10000    
    spc = int_insert(spc, 0, script_offset, 2)
    for i in range(8):
        loc = 4 + i * 2
        track_start = int.from_bytes(seqdata[loc:loc+2], "little")
        track_start -= address_base
        track_start += 0x1C24
        loc = 2 + i * 2
        spc = int_insert(spc, loc, track_start, 2)

    spc = byte_insert(spc, 0xF600, aux_ram)
    
    spc = header + spc
    return spc

def build_and_play_spc(prj, seqid):
    spc = build_spc(prj, seqid)

    with open("temp.spc", "wb") as f:
        f.write(spc)

    startfile("temp.spc")
    
class SnesApu():
    def __init__(self):
        self.initialized = False
        self.playing = False
        self.spc = None
        self.chn = None
        self.seq = None
        self.samp = None
        self.volume = 1
        
        self.next = bytearray()
        self.cache = {}
        self.cur_apu_sample = 0
        self.next_frame_sample = 0
        
    def init(self):
        pygame.mixer.set_reserved(1)
        self.chn = pygame.mixer.Channel(0)
        
    def play_id(self, prj, seqid):
        spc = build_spc(prj, seqid)
        self.seq = prj.seq[seqid]
        self.samp = {}
        for i in range(16):
            if self.seq.inst[i]:
                self.samp[i+0x20] = prj.brr[self.seq.inst[i]]
        for i in range(256, max(prj.brr) + 1):
            self.samp[i - 256] = prj.brr[i]
        self.play(spc)
        
    def play(self, spc):
        self.next = bytearray()
        self.chn = pygame.mixer.Channel(0)
        self.chn.set_volume(self.volume)
        
        snesapu.load_spc_file(spc)
        snesapu.set_apu_length(-1, 0)
        self.spc = spc
        self.playing = True
        self.initialized = True
        
    def stop(self):
        self.playing = False
        self.cache = {}
        self.cur_apu_sample = 0
        self.next_frame_sample = 0
        
    def update(self):
        if self.playing:
            # Sometimes MIDI-notes ignore reserved channel and mess with APU volume
            # Resetting it every frame to make this less disruptive
            self.chn.set_volume(self.volume)
            
            while len(self.next) <= G.AUDIO_BUFFER * 8:
                buf = bytes(snesapu.emulate_apu(64, 1))
                self.cur_apu_sample += 64
                ram, timer, dsp = snesapu.get_apu_data(ram=True, timer=True, dsp=True)
                self.cache[self.cur_apu_sample] = (buf, copy(dsp), ram, timer)
                self.next += buf
            if not self.chn.get_queue():
                snd = pygame.mixer.Sound(buffer=self.next)
                self.chn.queue(snd)
                self.next = bytearray()
                self.next_frame_sample = self.cur_apu_sample - G.AUDIO_BUFFER
            self.next_frame_sample += imgui.get_io().delta_time * 32000
            
    def get_dsp(self):
        # Gets DSP state for next displayed frame, not current
        self.cache = {k: v for k, v in self.cache.items() if k > self.next_frame_sample}
        try:
            key = min(self.cache.keys())
            return (self.cache[key][1], EngineState(self.cache[key][2]))
        except ValueError:
            return snesapu.DSPReg(), blank_engine
        
class EngineState():
    # Record some engine-specific voice data from SPC RAM
    def __init__(self, ram):
        self.v = []
        self.tempo = ram[0x46]
        for i in range(8):
            self.v.append(EngineStateVoice(i, ram))
            
class EngineStateVoice():
    def __init__(self, idx, ram):
        bitmask = 1 << idx
        self.idx = idx
        self.loop_level = ram[0x26 + idx * 2] - idx * 4
        self.slur = bool(ram[0x5B] & bitmask)
        self.gapless = bool(ram[0x5F] & bitmask)
        self.octave = ram[0xF600 + idx * 2]
        tremval = (ram[0xF861 + idx * 2] << 1) & 0xFF
        self.volume = ram[0xF621 + idx * 2]
        if tremval != 0:
            if tremval <= 0x80:
                tremval += 0x100
        #    self.volume = min(127, round(self.volume * tremval / 0x100))
        self.vol_pct = self.volume / 127
        pswval = ram[0xF881 + idx * 2]
        if pswval >= 0x80:
            pswval -= 0x100
        self.pan = ram[0xF661 + idx * 2] + pswval
        self.pan_pct = (self.pan - 0x80) / 0x80

blank_engine = EngineState(bytes(0x10000))
        
apu = SnesApu()
