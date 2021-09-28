import configparser
import hashlib
from pathlib import Path

import pygame

IMPRESARIA_VERSION = "0.0.0"

# this file has basically ballooned out from its original purpose
# into a general catch-all for "things that might need to be
# imported in multiple other places"

# vblank.ok - check to see if there's still time to calculate things
#     before the next frame is drawn. use only when the next frame
#     draw DEFINITELY does not overlap/conflict with the calculations.
#     necessarily dependent on GUI library; may just be dummied out
#     in some cases.

class Vblank():
    def __init__(self):
        self._tick = 0
        
    @property
    def ok(self):
        return (pygame.time.get_ticks() - self._tick) < 15
        
    def tick(self):
        self._tick = pygame.time.get_ticks()
        
vblank = Vblank()

class KeyboardEventHandler():
    def __init__(self):
        self.down = []
        self.up = []
        
    def update(self, down, up):
        self.down = down
        self.up = up

    def DOWN(self, key, mod=None, no=None):
        return self.test(self.down, key, mod, no)
        
    def UP(self, key, mod=None, no=None):
        return self.test(self.up, key, mod, no)
        
    def test(self, db, key, mod, no):
        for event in db:
            if event.key == key:
                if mod is None or mod & event.mod:
                    if no is None or (not no & event.mod):
                        return True
        return False
KEY = KeyboardEventHandler()

## no backend dependent code below this line

# TODO this is likely to break with pyinstaller (resolves to temp dir)?
META_FILENAME = Path(__file__).resolve().parent / "names.ini"
meta = None

class LogMessenger():
    def __init__(self):
        self.textqueue = []
        self.textqueue_queue = ""
        
    def send(self, text, qq=False):
        if qq and self.textqueue_queue:
            self.flush_qq()
        self.textqueue.append(text)
        
    def queue(self, text, pad=1):
        self.textqueue_queue += text + (" " * pad)
        
    def flush_qq(self):
        if self.textqueue_queue:
            self.textqueue.append(self.textqueue_queue)
        self.textqueue_queue = ""
    
    def flush(self):
        self.flush_qq()
        ret = self.textqueue
        self.textqueue = []
        return ret
    
log = LogMessenger()
std = LogMessenger()
err = LogMessenger()

def repr_bank(val):
    if val is None:
        return "None"
    text = f"{val:06X}"
    return f"${text[:2]}/{text[2:]}"
    
def pretty_bytes(bin, group=2, line=None):
    s = ""
    count = 0
    lcount = 0
    for i in bin:
        s += f"{i:02X} "
        count += 1
        lcount += 1
        if lcount >= line:
            s += "\n"
            count = 0
            lcount = 0
        if count >= group:
            s += " "
            count = 0
    return s.strip()
    
class OPT():
    trim_sequence_ends = True

def init_meta():
    global meta
    meta = configparser.ConfigParser(interpolation=None)
    try:
        meta.read(META_FILENAME)
    except IOError:
        pass
    if not meta.has_section("Sequences"):
        meta.add_section("Sequences")
    if not meta.has_section("Samples"):
        meta.add_section("Samples")
     
def write_metadata(seq, brr):
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(META_FILENAME)
    except IOError:
        err.send("Can't read file {META_FILENAME}")
        return
        
    if not cp.has_section("Sequences"):
        cp.add_section("Sequences")
    if not cp.has_section("Samples"):
        cp.add_section("Samples")
        
    for id, sequence in seq.items():
        if not sequence.name:
            continue
        blob = sequence.get_inst_table() + sequence.data
        key = (f"{hashlib.md5(blob).hexdigest()}"
                f" {len(sequence.data):x}")
        val = f"{sequence.name}"
        cp["Sequences"][key] = val
        
    for id, sample in brr.items():
        if not sample.name:
            continue
        key = f"{hashlib.md5(sample.data).hexdigest()} {sample.blocks}"
        val = f"{sample.name}"
        cp["Samples"][key] = val
        
    try:
        with open(META_FILENAME, "w") as f:
            cp.write(f)
        log.send("Names and meta-information saved.")
    except IOError:
        err.send("Can't write to file {META_FILENAME}")
        
        
def lookup_brr_metadata(brr):
    key = f"{hashlib.md5(brr.data).hexdigest()} {brr.blocks}"
    if key in meta["Samples"]:
        val = meta["Samples"][key]
        brr.name = val
        
def lookup_seq_metadata(seq):
    blob = seq.get_inst_table() + seq.data
    key = f"{hashlib.md5(blob).hexdigest()} {len(seq.data):x}"
    if key in meta["Sequences"]:
        val = meta["Sequences"][key]
        seq.name = val
