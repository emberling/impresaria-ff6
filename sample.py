from array import array
from base64 import b64encode
from messenger import err, std, log, lookup_brr_metadata
from formats import clamp
from audio import scale_to_unity_key

SAMPLE_EXTRA_ITERATIONS = 1
SAMPLE_MIN_SIZE = 512
STEREO = True

class Sample():
    def __init__(self, data=None, loop=None, pitch=None, env=None, id=""):
        try:
            id = f" {id:02X}"
        except ValueError:
            id = f" {id}"
        self.data = b"\x01\x00\x00\x00\x00\x00\x00\x00\x00" if data is None else data
        self.loop = 0 if loop is None else loop
        self.pitch = 0 if pitch is None else pitch
        self.env = Envelope() if env is None else env
                
        walkinfo = walk_brr(self.data)
        self.blocks =    walkinfo[0]
        self.is_looped = walkinfo[1]
        proper      =    walkinfo[2]
        
        if not self.blocks:
            log.send(f"Attempted to load non-terminated sample{id}.")
            self.__init__()
        elif not proper:
            log.send(f"Truncating improper sample{id} at {self.blocks} blocks..")
            self.data = self.data[:self.blocks*9]
        
        self.source_type = ""
        self.source_detail = None
        self.name = ""
        lookup_brr_metadata(self)
        
        self.decode_brr(self.data, self.loop, extend=True)
        
        pcmfloats = []
        stride = 4 if STEREO else 2
        for i in range(len(self.pcm)//stride):
            word = self.pcm[i*stride:i*stride+2]
            intword = int.from_bytes(word, "little", signed=True)
            pcmfloats.append(float(intword))
        self.pcmarray = array('f', pcmfloats)
        
    def get_data(self):
        return (len(self.data)).to_bytes(2, "little") + self.data
        
    def get_split_loop_pcm(self):
        if self.is_looped:
            truncate_point = len(self.pcm) - 64
            split_point = truncate_point - self.pcmlooplen
            onset = self.pcm[:split_point]
            loop = self.pcm[split_point:truncate_point]
            return onset, loop
        else:
            return self.pcm, b""
            
    def set_source(self, source, detail):
        source = source.lower()
        if source == "rom":
            self.source_type = "rom"
            self.source_detail = detail
        elif source == "file":
            self.source_type = "file"
            self.source_detail = detail
    
    def get_pitch_as_scale(self):
        # for retrieving scale (0.5x - ~1.5x)
        return (self.pitch + 0x10000) / 0x10000
        
    def pitch_to_key(self, pitch, int=True):
        # input: vxPitch (base 4096), output MIDI-key
        ret = scale_to_unity_key(pitch / (4096 * self.get_pitch_as_scale()))
        return round(ret) if int else ret
        
    def decode_brr(self, brr, loop, extend=False):
        channels = 2 if STEREO else 1
        looplength = ((len(brr) - loop) // 9) * 16 * channels
        orig_len = len(brr)
        
        pcm = bytearray()
        pre = 0
        prepre = 0
        loc = 0
        loops = 0
        while True:
            block = brr[loc:loc+9]
            pcm_samples, pre, prepre = self.decode_block(block, pre, prepre)
            
            for p in pcm_samples:
                ext = p.to_bytes(2, "little", signed=True)
                for i in range(channels):
                    pcm.extend(ext)
                
            if block[0] & 0b11 == 0b11:
                if (extend
                        and loops >= SAMPLE_EXTRA_ITERATIONS
                        and len(pcm) >= SAMPLE_MIN_SIZE * channels
                        ):
                    valid = self.validate_loop(pcm, looplength, orig_len)
                    if valid:
                        looplength *= valid
                        #std.send(f"\n  Loop extended by {valid}x (total iterations {loops+1})")
                        #std.send(f"  loop size {looplength}, sample size {len(pcm)}")
                        break
                loops += 1
                loc = loop
                continue
            elif block[0] & 1:
                break
                
            loc += 9
            if loc > len(brr):
                err.send("BRR block unexpected EOF")
                break
        
        #std.send(f"pcm is {len(pcm)}, looplength {looplength}")
        self.pcm = pcm
        self.pcmlooplen = looplength
        
            
    def decode_block(self, block, pre, prepre):
        head = block[0]
        filtermode = (head & 0b1100) >> 2
        shiftrange = head >> 4
        # print(f"filter {filtermode} shift {shiftrange}")
        
        nybs = []
        pcms = []
        for byt in block[1:]:
            nybs.append(byt >> 4)
            nybs.append(byt & 0x0F)
        # print(nybs)
        for n in nybs:
            if n >= 8:
                n -= 16
            if shiftrange > 13:
                pcm = (-1 if n < 0 else 1) << 11
            else:
                pcm = n << shiftrange >> 1
            debug_shifted = pcm
            
            if filtermode == 0:
                filter = 0
            elif filtermode == 1:
                filter = pre + ((-1 * pre) >> 4)
            elif filtermode == 2:
                filter = (pre << 1) + ((-1*((pre << 1) + pre)) >> 5) - prepre + (prepre >> 4)
            elif filtermode == 3:
                filter = (pre << 1) + ((-1*(pre + (pre << 2) + (pre << 3))) >> 6) - prepre + (((prepre << 1) + prepre) >> 4)
            pcm += filter
            debug_filtered = pcm
            
            pcm = clamp(-0x8000, pcm, 0x7FFF)
            if pcm > 0x3FFF:
                pcm -= 0x8000
            elif pcm < -0x4000:
                pcm += 0x8000
            #print(f"{debug_shifted} -> {debug_filtered} ({filter}) -> {pcm}")
            pcms.append(pcm)
            prepre = pre
            pre = pcm
        return pcms, pre, prepre

    def validate_loop(self, pcm, looplen, orig_len):
        lstart = len(pcm) - looplen
        lscale = 1
        while True:
            lstart = len(pcm) - looplen * lscale
            prelstart = lstart - looplen * lscale
            if prelstart <= orig_len:
                break
            if pcm[lstart:] == pcm[prelstart:lstart]:
                return lscale
            lscale += 1
        return False
        
    def get_saveable(self):
        sav = {}
        sav["data"] = b64encode(self.data).decode('utf-8')
        sav["loop"] = self.loop
        sav["pitch"] = self.pitch
        sav["env"] = [self.env.a, self.env.d, self.env.s, self.env.r]
        sav["source_type"] = self.source_type
        sav["source_detail"] = self.source_detail
        sav["name"] = self.name
        return sav
        
class Envelope():
    def __init__(self, a=None, d=None, s=None, r=None, bin=None):
        if bin:
            self.a = bin[0] & 0b00001111
            self.d = (bin[0] & 0b01110000) >> 4
            self.s = (bin[1] & 0b11100000) >> 5
            self.r = bin[1] & 0b00011111
        else:
            self.a = 15 if a is None else a
            self.d = 7 if d is None else d
            self.s = 7 if s is None else s
            self.r = 0 if r is None else r
            
    def bytes(self):
        val = bytearray(2)
        val[0] = 0x80 + (self.d << 4) + self.a
        val[1] = (self.s << 5) + self.r
        return val

    def attack_time(self):
        return self.attack_table[self.a]
        
    def decay_time(self):
        dt = int(self.decay_table[self.d] * (1 - self.sustain_level()))
        # this seems wrong / too long but i can't find the error so
        # temporarily just adjusting this by feel
        return dt // 1.25
        
    def sustain_level(self):
        return (self.s + 1) / 8
        
    def release_time(self):
        return self.release_table[self.r]
        
    def __eq__(self, other):
        if (self.a == other.a and self.d == other.d
                and self.s == other.s and self.r == other.r):
            return True
        return False
        
    attack_table = {
        0: 4100,
        1: 2600,
        2: 1500,
        3: 1000,
        4: 640,
        5: 380,
        6: 260,
        7: 160,
        8: 96,
        9: 64,
        10: 40,
        11: 24,
        12: 16,
        13: 10,
        14: 6,
        15: 0 }

    decay_table = {
        0: 1200,
        1: 740,
        2: 440,
        3: 290,
        4: 180,
        5: 110,
        6: 74,
        7: 37 }
        
    release_table = {
        0: None,
        1: 38000,
        2: 38000,
        3: 24000,
        4: 19000,
        5: 14000,
        6: 12000,
        7: 9400,
        8: 7100,
        9: 5900,
        10: 4700,
        11: 3500,
        12: 2900,
        13: 2400,
        14: 1800,
        15: 1500,
        16: 1200,
        17: 880,
        18: 740,
        19: 590,
        20: 440,
        21: 370,
        22: 290,
        23: 220,
        24: 180,
        25: 150,
        26: 110,
        27: 92,
        28: 74,
        29: 55,
        30: 37,
        31: 28 }
        
# Walk through a BRR sample to record some basic info about it.
# Returns [# of blocks until end, or None if no end], [True if looped],
#                        [True if no extra data is attached afterward]
def walk_brr(brr):
    end = None
    loop = False
    proper = False
    i = 0
    while i < len(brr):
        if brr[i] & 1:
            end = i // 9 + 1
            loop = True if brr[i] & 2 else False
            break
        i += 9
    if end and len(brr) == end * 9:
        proper = True
    return end, loop, proper
    
def decode_brr_akaotool_ver(brr, stereo=False):
    pos = 0
    wyrds = []
    last_wyrd, lastest_wyrd = 0, 0
    pcm = bytearray()
    while pos < len(brr)-9:
        block = brr[pos:pos+9]
        header = block[0]
        nybbles = []
        for i in range(1,9):
            nybbles.append(block[i] >> 4)
            nybbles.append(block[i] & 0b1111)
        end = header & 0b1
        loop = (header & 0b10) >> 1
        filter = (header & 0b1100) >> 2
        shift = header >> 4
        for n in nybbles:
            if n >= 8:
                n -= 16
            if shift <= 0x0C:
                wyrd = (n << shift) >> 1
            else:
                wyrd = 1<<11 if n >= 0 else (-1)<<11
            if filter == 1:
                wyrd += last_wyrd + ((-last_wyrd) >> 4)
            elif filter == 2:
                wyrd += (last_wyrd << 1) + ((-((last_wyrd << 1) + last_wyrd)) >> 5) - lastest_wyrd + (lastest_wyrd >> 4)
            elif filter == 3:
                wyrd += (last_wyrd << 1) + ((-(last_wyrd + (last_wyrd << 2) + (last_wyrd << 3))) >> 6) - lastest_wyrd + (((lastest_wyrd << 1) + lastest_wyrd) >> 4)
            if wyrd > 0x7FFF:
                wyrd = 0x7FFF
            elif wyrd < -0x8000:
                wyrd = -0x8000
            if wyrd > 0x3FFF:
                wyrd -= 0x8000
            elif wyrd < -0x4000:
                wyrd += 0x8000
            
            lastest_wyrd = last_wyrd
            last_wyrd = wyrd
            w = wyrd.to_bytes(2, byteorder='little', signed=True)
            pcm.extend(w)
            if stereo:
                pcm.extend(w)
        pos += 9
        if end:
            break
    return pcm
    
