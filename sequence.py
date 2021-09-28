from formats import int_insert
from messenger import lookup_seq_metadata
from base64 import b64encode

from mfvitools.mfvi2mml import akao_to_mml

class Sequence():
    def __init__(self, data=None, inst=None, source=None):
        self.data = b"\x26\x00" * 18 if data is None else data
        self.inst = {}
        if inst is None:
            for i in range(16):
                self.inst[i] = 0
        else:
            self.setup_inst_data(inst)
        
        self.raw_mml = ""
        self.source_type = ""
        self.source_detail = None
        self.name = ""
        lookup_seq_metadata(self)
        
        if source:
            self.set_source(*source)
        self.update_raw_mml()
        
    def setup_inst_data(self, data):
        if len(data) < 32:
            data += b"\x00" * 32
        for i in range(16):
            self.inst[i] = int.from_bytes(data[i*2:i*2+2], "little")
        
    def get_data(self):
        return (len(self.data) - 1).to_bytes(2, "little") + self.data
        
    def get_inst_table(self):
        table = bytearray(0x20)
        for i in range(16):
            table = int_insert(table, i*2, self.inst[i], 2)
        return table
        
    def update_raw_mml(self):
        if len(self.data) <= 0x26:
            self.raw_mml = ""
        else:
            fileid = "seq" + (f"{self.source_detail[0]:02X}" if self.source_detail else " ??")
            self.raw_mml = "\n".join(akao_to_mml(self.data, None, raw_length=True, quiet=True, extra_header=False, fileid=fileid))
        
    def set_source(self, source, detail):
        source = source.lower()
        if source == "rom":
            self.source_type = "rom"
            self.source_detail = detail
        elif source == "mml":
            #TODO we should get both the filename and full text of the MML
            #     (maybe that's not stored here idk)
            self.source_type = "mml"
            self.source_detail = detail
        else:
            self.source = ""
            if source:
                log.send(f"Unrecognized sequence source '{source}'.")
            
    def repr_source(self):
        if self.source_type == "rom":
            s = f"ROM, from id ${self.source_detail[0]} @ ${self.source_detail[1]:06X}"
        elif self.source_type == "mml":
            s = f"MML, from {self.source_detail[0]}"
        else:
            s = "unknown"
        return s
        
    def get_saveable(self):
        sav = {}
        sav["data"] = b64encode(self.data).decode('utf-8')
        sav["inst"] = self.inst
        sav["source_type"] = self.source_type
        sav["source_detail"] = self.source_detail
        sav["name"] = self.name
        return sav