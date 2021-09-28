from copy import copy
import json

from allocator import Allocator
from formats import byte_insert, int_insert, to_rom_address
from messenger import IMPRESARIA_VERSION, log, std, err, repr_bank, pretty_bytes, vblank

class Project():
    def __init__(self, name, rom):
        self.init_status = False
        
        self.sourcefile = rom.fn
        self.src = rom
        self.format = rom.format
        
        self.alloc = Allocator()
        self.seq = {}
        self.brr = {}
        
        self.action_queue = []
        self.action_queue_kwargs = {}
        self.completed_actions = []
        
        #self.seq_table_auto = True
        #self.inst_table_auto = True
        #self.brr_table_auto = True
        #self.loop_table_auto = True
        #self.pitch_table_auto = True
        #self.env_table_auto = True
        
    def frame_init(self):
        status = False
        while vblank.ok and self.init_status is not True and status is not True:
            status = self.src.frame_init(alloc=self.alloc)
        if status is True:
            self.seq = copy(self.src.seq)
            self.brr = copy(self.src.brr)
            self.init_status = True
        return status
            
    def repr_seq(self, idx):
        seq = self.seq[idx]
        name = seq.name if seq.name else "Unknown Sequence"
        return f"{idx:02X} {name} ({len(seq.data):X} b)"
        
    def repr_smp(self, idx):
        smp = self.brr[idx]
        name = smp.name if smp.name else "Unknown Sample"
        idx_text = f"@{idx-256:X}" if idx >= 256 else f"{idx:02X}"
        return f"{idx_text} {name} ({len(smp.data) // 9} blk)"
    
    def get_samples(self):
        return {k: v for k, v in self.brr.items() if k < 256}

    def sample_get_clones(self, idx):
        # Returns None if no duplicates, otherwise
        # returns two lists of IDs, one for non-exact and one for exact clones.
        idx_t = f"brr{idx:02X}"
        bin = self.alloc.data_index[idx_t]
        if len(self.alloc.data_blocks[bin]) <= 1:
            return None

        smp = self.brr[idx]
        partial_clones = []
        full_clones = []
        for cloneid in self.alloc.data_blocks[bin]:
            if cloneid == idx_t:
                continue
            try:
                clid_i = int(cloneid[3:], 16)
            except ValueError:
                err.send(f"Something weird happened and {cloneid} doesn't reduce to a number!")
                continue
            clone = self.brr[clid_i]
            if (smp.loop == clone.loop and
                    smp.pitch == clone.pitch and
                    smp.env == clone.env):
                full_clones.append(clid_i)
            else:
                partial_clones.append(clid_i)
        return partial_clones, full_clones
            
    def serialize(self):
        sav = {}
        
        sav["version"] = IMPRESARIA_VERSION
        sav["sourcefile"] = self.sourcefile
        sav["format"] = self.format.id
        
        sav["seq"] = {}
        for k, v in self.seq.items():
            sav["seq"][k] = v.get_saveable()
        sav["brr"] = {}
        for k, v in self.brr.items():
            sav["brr"][k] = v.get_saveable()
        return json.dumps(sav)

    def process_action_queue(self):
        # An action queue function returns:
        # - a list of action queue functions to append to the start of the queue
        # - a list of action queue functions to append to the end of the queue
        # - a list of string tuples (desc, status) to represent any completed actions
        
        # Action queue functions should also all accept **kwargs.
        # self.action_queue_kwargs stores any state variables relevant to the current
        # queue, e.g. information on where free/redundant sample IDs can be found.
        
        if self.action_queue:
            action = self.action_queue.pop(0)
            front, back, complete = action.process(**self.action_queue_kwargs)
        elif self.completed_actions:
            for a in self.completed_actions:
                if a[1] != "OK":
                    text = f"[{a[1]}] -- {a[0]}"
                else:
                    text = a[0]
                log.send(text)
            self.completed_actions = []
            self.action_queue_kwargs = {}
    
    #def replace_sample_from_file(self, idx, fn, type=None):
        
            
class ActionQueueEntry():
    def __init__(self, func, text, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.text = text
        
    def process(self, **kwargs):
        return self.func(*self.args, {**self.kwargs, **kwargs})
