import audioop
import math

import pygame

ROOT_NOTE_KEY = 69 # A5
SAMPLE_MIN_SIZE = 512 * 64

class no():
    def __init__(self):
        self._audio = None
        
    @property
    def AUDIO(self):
        if not self._audio:
            self._audio = pygame.mixer.Sound(buffer=b"")
        return self._audio
NO = no()

class PianoState():
    def __init__(self, play_audio = False):
        keys = {}
        for i in range(128):
            keys[i] = False
        self.keys = keys
        self.play_audio = play_audio
        self.sample = None
        self.last_mouse_key = None
        
    def key_on(self, key, sample=None):
        if sample is not None:
            self.sample = sample
        if self.play_audio:
            if not self.keys[key]:
                self.keys[key] = KeyOnState(self.sample, key)
            self.keys[key].key_on(self.sample, key)
        else:
            self.keys[key] = True
        
    def key_off(self, key):
        if self.play_audio:
            try:
                self.keys[key].key_off()
            except AttributeError:
                pass
        #self.keys[key] = False
        
    def read_midi(self, sample, message_queue):
        for message, delta in message_queue:
            type = message[0]
            if type in range(0x80, 0x90):
                self.key_off(message[1])
            elif type in range(0x90, 0xA0):
                self.key_on(message[1], sample=sample)
                # Velocity is in message[2] if we ever decide to add that
                
    def sustain(self):
        for i in range(128):
            try:
                self.keys[i].hold()
            except AttributeError:
                pass
        
    def key_is_on(self, key):
        if self.play_audio:
            if self.keys[key]:
                if self.keys[key].active:
                    return True
            return False
        else:
            if self.keys[key]:
                return True
        return False
        
    def any_key_is_on(self):
        if self.play_audio:
            states = [key.active for key in self.keys]
        else:
            states = self.keys.values()
        return (True in states)
        
    def __repr__(self):
        s = ""
        for i in range(128):
            if self.keys[i]:
                if (not self.play_audio) or (self.keys[i].active):
                    s += f"{i:02X} "
        return s.strip()
        
class KeyOnState():
    def __init__(self, sample, key):
        self.smp = sample
        self.chn = pygame.mixer.find_channel()
        self.active = False
        self.fadeout = False
        self.key = key
        
        self.start_time = pygame.time.get_ticks()
        self.delta_time = 0
        self.peak_time = 1
        self.shift_time = 2
        self.zero_time = 3
        self.key_off_time = None
        self.key_off_level = 1.0
        self.key_off_rate = 100
        self.sustain_level = 1.0
        self.onset_, self.loopdata_ = sample.get_split_loop_pcm()
        
        self.init_pitched()
        
    def init_pitched(self):
        self.cvstate = None
        rate = int(32000 * unity_key_to_scale(self.key) * (1 / self.smp.get_pitch_as_scale()))
        self.onset, self.cvstate = audioop.ratecv(self.onset_, 2, 2, 32000, rate, self.cvstate)
        self.loopdata, self.cvstate = audioop.ratecv(self.loopdata_, 2, 2, 32000, rate, self.cvstate)
        
        if self.smp.is_looped:
            self.loopdata = bytearray(self.loopdata)
            base_loopdata = bytes(self.loopdata)
            while len(self.loopdata) < SAMPLE_MIN_SIZE:
                self.loopdata = self.loopdata + base_loopdata
        
        self.pyg_sound = pygame.mixer.Sound(buffer=self.onset)
        self.pyg_loop = pygame.mixer.Sound(buffer=self.loopdata)
        
    def key_off(self):
        if self.active and not self.fadeout:
            self.key_off_level = self.calc_env_level()
            self.key_off_time = pygame.time.get_ticks() - self.start_time
        self.active = False
        self.fadeout = True
        
    def key_on(self, sample, key):
        if not self.active:
            self.active = True
            if sample == self.smp and key == self.key:
                try:
                    self.init_pitched()
                    self.chn = pygame.mixer.find_channel()
                    self.chn.set_volume(1 if sample.env.a == 15 else 0)
                    self.chn.play(self.pyg_sound)
                    self.chn.queue(self.pyg_loop)
                    self.start_time = pygame.time.get_ticks()
                    self.calc_envelope()
                except AttributeError:
                    # Too many notes pushed at once can produce None for find_channel
                    # we'll just drop the last note-ons processed
                    self.active = False
            else:
                self.__init__(sample, key)
                self.key_on(sample, key)
            
    def hold(self):
        if self.active or self.fadeout:
            try:
                if not self.chn.get_queue():
                    self.chn.queue(self.pyg_loop)
                
                self.delta_time = pygame.time.get_ticks() - self.start_time
                self.chn.set_volume(self.calc_env_level())
            except AttributeError:
                pass
                    
    def calc_envelope(self):
        env = self.smp.env
        self.peak_time = env.attack_time()
        self.sustain_level = env.sustain_level()
        self.shift_time = env.decay_time() + self.peak_time
        self.zero_time = None if not env.release_time() else (env.release_time() + self.shift_time)
        
    def calc_env_level(self):
        if self.fadeout:
            fade_per_frame = self.key_off_level / self.key_off_rate
            try:
                level = self.key_off_level - (fade_per_frame * (self.delta_time - self.key_off_time))
            except TypeError:
                level = 0
            if level <= 0:
                self.fadeout = False
                level = 0
            return level
        else:
            if self.delta_time < self.peak_time:
                level = self.delta_time / self.peak_time
            elif self.delta_time < self.shift_time:
                pct = ((self.delta_time - self.peak_time) / self.shift_time)
                level_delta = 1.0 - self.sustain_level
                level = ((1 - pct) * level_delta) + self.sustain_level
            elif self.zero_time is None:
                level = self.sustain_level
            elif self.delta_time < self.zero_time:
                pct = ((self.delta_time - self.shift_time) / self.zero_time)
                level = (1 - pct) * self.sustain_level
            else:
                level = 0
            return level
            
def unity_key_to_scale(key):
    delta = ROOT_NOTE_KEY - key
    scale = 2**(delta/12)
    return scale
    
def scale_to_unity_key(scale):
    delta = math.log2(scale) * 12
    return ROOT_NOTE_KEY + delta