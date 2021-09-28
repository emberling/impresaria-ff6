## something something this file probably has to be GPL

from ctypes import *
import os

snesapudll = CDLL(os.path.abspath("snesapu.dll"))

class DSPVoice(Structure):
    _fields_ = [
            ("volL", c_int8),
            ("volR", c_int8),
            ("pitch", c_uint16),
            ("srcn", c_uint8),
            ("adsr", c_uint8 * 2),
            ("gain", c_uint8),
            ("envx", c_int8),
            ("outx", c_int8),
            ("__r", c_int8 * 6)
            ]
            
class DSPFIR(Structure):
    _fields_ = [
            ("__r", c_int8 * 15),
            ("c", c_int8)
            ]
            
class Voice(Structure):
    _fields_ = [
            ("vAdsr", c_uint16),
            ("vGain", c_uint8),
            ("vRsv", c_uint8),
            ("sIdx", POINTER(c_int16)),

            ("bCur", c_void_p),
            ("bHdr", c_uint8),
            ("mFlg", c_uint8),

            ("eMode", c_uint8),
            ("eRIdx", c_uint8),
            ("eRate", c_uint32),
            ("eCnt", c_uint32),
            ("eVal", c_uint32),
            ("eAdj", c_int32),
            ("eDest", c_uint32),
                   
            ("vMaxL", c_int32),
            ("vMaxR", c_int32),
                   
            ("sP1", c_int16),
            ("sP2", c_int16),
            ("sBufP", c_int16 * 8),
            ("sBuf", c_int16 * 16),
                   
            ("mTgtL", c_float),
            ("mTgtR", c_float),
            ("mChnL", c_int32),
            ("mChnR", c_int32),
            ("mRate", c_uint32),
            ("mDec", c_uint16),
            ("mSrc", c_uint8),
            ("mKOn", c_uint8),
            ("mOrgP", c_uint32),
            ("mOut", c_int32)
            ]

class DSPReg_S(Structure):
    _fields_ = [
            ("__r00", c_int8 * 12),
            ("mvolL", c_int8),
            ("efb", c_int8),
            ("__r0E", c_int8),
            ("c0", c_int8),
            
            ("__r10", c_int8 * 12),
            ("mvolR", c_int8),
            ("__r1D", c_int8),
            ("__r1E", c_int8),
            ("c1", c_int8),
            
            ("__r20", c_int8 * 12),
            ("evolL", c_int8),
            ("pmon", c_int8),
            ("__r2E", c_int8),
            ("c2", c_int8),
            
            ("__r30", c_int8 * 12),
            ("evolR", c_int8),
            ("non", c_int8),
            ("__r3E", c_int8),
            ("c3", c_int8),
            
            ("__r40", c_int8 * 12),
            ("kon", c_int8),
            ("eon", c_int8),
            ("__r4E", c_int8),
            ("c4", c_int8),
            
            ("__r50", c_int8 * 12),
            ("kof", c_int8),
            ("dir", c_int8),
            ("__r5E", c_int8),
            ("c5", c_int8),
            
            ("__r60", c_int8 * 12),
            ("flg", c_int8),
            ("esa", c_int8),
            ("__r6E", c_int8),
            ("c6", c_int8),
            
            ("__r70", c_int8 * 12),
            ("endx", c_int8),
            ("edl", c_int8),
            ("__r7E", c_int8),
            ("c7", c_int8)
            ]
            
class DSPReg(Union):
    _anonymous_ = ("s",)
    _fields_ = [
            ("voice", DSPVoice * 8),
            ("s", DSPReg_S),
            ("fir", DSPFIR),
            ("reg", c_uint8 * 128)
            ]
            
def load_spc_file(buffer: bytes):
    assert len(buffer) == 66048
    return snesapudll.LoadSPCFile(bytes(buffer))
    
def set_apu_length(song: int, fade: int):
    # 1 unit = 1/64000 sec
    # Returns total length for some reason
    total = snesapudll.SetAPULength(c_uint32(song), c_uint32(fade))
    return int(total)
    
def emulate_apu(length: int, len_type: int):
    buffer = create_string_buffer(length * 8)
    buffer_startp = pointer(buffer)
    buffer_endp = snesapudll.EmuAPU(buffer_startp, length, len_type)
    start_addr = cast(buffer_startp, c_void_p).value
    return bytes(buffer[:buffer_endp - start_addr])
    
snesapudll.GetAPUData.argtypes = [
        POINTER(POINTER(c_uint8)),
        POINTER(POINTER(c_uint8)),
        POINTER(POINTER(c_uint8)),
        POINTER(POINTER(c_uint32)),
        POINTER(POINTER(DSPReg)),
        POINTER(POINTER(Voice)),
        POINTER(POINTER(c_uint32)),
        POINTER(POINTER(c_uint32))
        ]
def get_apu_data(ram=False, xram=False, timer=False, dsp=False, voice=False,
            mvol=False):
    pRAM = POINTER(c_uint8)()
    pXRAM = POINTER(c_uint8)()
    pOutPort = POINTER(c_uint8)()
    pT64Cnt = POINTER(c_uint32)()
    pDSP = POINTER(DSPReg)()
    pVoice = POINTER(Voice)()
    pVMMaxL = POINTER(c_uint32)()
    pVMMaxR = POINTER(c_uint32)()
    
    result = snesapudll.GetAPUData(byref(pRAM), byref(pXRAM), byref(pOutPort),
            byref(pT64Cnt), byref(pDSP), byref(pVoice), byref(pVMMaxL), byref(pVMMaxR))
    retval = []
    if ram:
        # Only getting interesting areas of RAM because getting the whole thing is S L O W
        buf = bytearray()
        buf += bytes(pRAM[:0x100])
        buf += bytes(0xF500)
        buf += bytes(pRAM[0xF600:0xFA00])
        buf += bytes(0x600)
        retval.append(buf)
        
        #retval.append(bytearray(pRAM[:65536]))
        #retval.append(bytes(65536))
    if xram:
        retval.append(bytes(pXRAM[:128]))
    # OutPort not implemented - not sure how many bytes "4 ports of output" is
    # and I can't imagine any relevant use of it
    if timer:
        retval.append(int.from_bytes(pT64Cnt, "little"))
    if dsp:
        retval.append(pDSP.contents)
    if voice:
        retval.append(pVoice.contents)
    if mvol:
        retval.append(tuple(int(pVMMaxL), int(pVMMaxR)))
    return retval
    
    