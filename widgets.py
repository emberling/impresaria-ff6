import math

import imgui
import pygame

from formats import clamp
from spc import apu
from audio import scale_to_unity_key, PianoState
from messenger import repr_bank
from sample import Envelope

WINW = 1280
WINH = 720
WINSCALE = 1.0
UNIT = 13

def share_fonts(norm, small, big):
    global JPFONT, SMALLERFONT, BIGGERFONT
    JPFONT = norm
    SMALLERFONT = small
    BIGGERFONT = big
    
def share_units(winw, winh, winscale, unit):
    global WINW, WINH, WINSCALE, UNIT
    WINW, WINH, WINSCALE, UNIT = winw, winh, winscale, unit
    
def center_text(text):
    text_size = imgui.get_font_size() * len(text) / 2
    winx, winy = imgui.get_window_size()
    imgui.same_line((winx / 2) - (text_size / 2))
    imgui.text(text)
    
def glow_button(text, condition, color=None):
    if not color:
        color = (0.4, 0.35, 0.2)
    bright_color = ((v + v + 1) / 3 for v in color)
    brighter_color = ((v + 1) / 2 for v in color)
    if condition:
        imgui.push_style_color(imgui.COLOR_BUTTON, *color)
        imgui.push_style_color(imgui.COLOR_BUTTON_HOVERED, *bright_color)
        imgui.push_style_color(imgui.COLOR_BUTTON_ACTIVE, *brighter_color)
        ret = imgui.button(text)
        imgui.pop_style_color(3)
    else:
        ret = imgui.button(text)
    return ret
    
def range_entry(label, value, buffer_length=16, flags=0):
    if value:
        text = repr_bank(value)
    else:
        text = ""
    c, text = imgui.input_text(label, text, buffer_length)
    text = ''.join((c for c in text if c in "1234567890abcdefABCDEF"))
    if text:
        val = int(text, 16)
        return c, min(val, 0xFFFFFF)
    else:
        return c, None
        
def knob(id, value, min=0.0, max=1.0, scale=1):
    # read only knob
    with imgui.istyled(imgui.STYLE_WINDOW_PADDING, (1, 1)):
        imgui.begin_child(id, UNIT * scale, UNIT * scale)
        draw = imgui.get_window_draw_list()
        xorig, yorig = imgui.get_cursor_screen_pos()
        radius = UNIT / 2
        draw.add_circle_filled(xorig + radius, 
                yorig + radius, radius, imgui.get_color_u32_rgba(.3, .3, .3, 1))
        pct = (value - min) / (max - min)
        deg = ((1-pct) * 270 - 45)
        linex = radius * math.cos(math.radians(deg))
        liney = radius * math.sin(math.radians(deg))
        draw.add_line(xorig + radius, yorig + radius,
                xorig + radius + linex, yorig + radius - liney,
                imgui.get_color_u32_rgba(.8, .8, .8, 1), 2 * scale)
        imgui.end_child()
        
def spinner(label, value, min, max, hex=False, pad=None):
    initial = value
    if hex:
        form = ("{:0" + str(pad) + "X}") if pad else "{:X}"
        flags = imgui.INPUT_TEXT_CHARS_HEXADECIMAL | imgui.INPUT_TEXT_CHARS_UPPERCASE
        base = 16
    else:
        form = ("{:0" + str(pad) + "}") if pad else "{}"
        flags = imgui.INPUT_TEXT_CHARS_DECIMAL
        base = 10
        
    text = form.format(value)
    imgui.begin_group()
    ch, text = imgui.input_text(label, text, 8, imgui.INPUT_TEXT_CHARS_HEXADECIMAL
            | imgui.INPUT_TEXT_CHARS_UPPERCASE)
    if ch:
        try:
            value = int(text, base)
        except ValueError:
            pass
    
    imgui.same_line()
    imgui.begin_group()
    if imgui.small_button("+"):
        value += 1
    if imgui.small_button("-"):
        value -= 1
    imgui.end_group()
    imgui.end_group()
    
    value = clamp(min, value, max)
    
    return (value == initial), value
    
class Piano():
    black_key_width = 5
    white_key_width = 6
    black_keys = [1, 3, 6, 8, 10]
    xpos_table = [0, 2.5, 6, 9.5, 12, 18, 20.5, 24, 27, 30, 33.5, 36]
    octave_width = (white_key_width) * 7 
    black_key_length = 18*.75
    white_key_length = 30*.75
    
    def __init__(self, state=None, interactive=False):
        self.state = PianoState() if state is None else state
        
        self.interactive = interactive
        
    def get_width(self, first=12, last=104, scale=1.0):
        if first % 12 in self.black_keys:
            first -= 1
        if last % 12 in self.black_keys:
            last += 1
        
        return (last + 1 - first) * (7/12) * (self.white_key_width + 1) * scale
        
    def draw(self, id, first=12, last=104, scale=1.0, alpha=1.0, sample=None):
        white_key_width = scale * self.white_key_width
        black_key_width = scale * self.black_key_width
        white_key_length = scale * self.white_key_length
        black_key_length = scale * self.black_key_length
        octave_width = scale * self.octave_width
        xpos_table = [n * scale for n in self.xpos_table]
        
        if first % 12 in self.black_keys:
            first -= 1
        if last % 12 in self.black_keys:
            last += 1
        left_adjust = (octave_width * (first // 12)) + xpos_table[first % 12]
        
        mouseover = None
        mouse_x, mouse_y = imgui.get_mouse_position()
        with imgui.istyled(imgui.STYLE_WINDOW_PADDING, (1, 1)):
            width = (last + 1 - first) * (7/12) * (white_key_width)
            imgui.begin_child(id, width + 2, white_key_length + 2, border=True)
            draw = imgui.get_window_draw_list()
            xorig, yorig = imgui.get_cursor_screen_pos()
            for i in range(first, last + 1):
                octkey = i % 12
                octave = i // 12
                if octkey not in self.black_keys:
                    xpos = (octave_width * octave) + xpos_table[octkey] + xorig - left_adjust
                    color = (imgui.get_color_u32_rgba(1, .3, .3, alpha)
                            if self.state.key_is_on(i) else
                            octave_colors(octave, alpha))
                    draw.add_rect_filled(xpos, yorig, xpos + white_key_width - 1,
                            yorig + white_key_length, color)
                    if (xpos <= mouse_x <= xpos + white_key_width and
                            yorig <= mouse_y <= yorig + white_key_length):
                        if imgui.is_window_hovered():
                            mouseover = i
            for i in range(first, last + 1):
                octkey = i % 12
                octave = i // 12
                if octkey in self.black_keys:
                    xpos = (octave_width * octave) + xpos_table[octkey] + xorig - left_adjust
                    draw.add_rect_filled(xpos, yorig, xpos + black_key_width,
                            yorig + black_key_length, imgui.get_color_u32_rgba(.2, .2, .3, alpha))
                    if self.state.key_is_on(i):
                        draw.add_rect_filled(xpos+scale, yorig,
                                xpos + black_key_width - scale, yorig + black_key_length - scale,
                                imgui.get_color_u32_rgba(1, .3, .3, alpha))
                    if (xpos <= mouse_x <= xpos + black_key_width and
                            yorig <= mouse_y <= yorig + black_key_length):
                        if imgui.is_window_hovered():
                            mouseover = i
            imgui.end_child()

        if self.interactive and sample:
            if self.state.last_mouse_key is None:
                if imgui.is_mouse_down(0):
                    if mouseover is not None:
                        self.state.key_on(mouseover, sample=sample)
                        self.state.last_mouse_key = mouseover
            else:
                if imgui.is_mouse_down(0):
                    if mouseover != self.state.last_mouse_key and mouseover is not None:
                        self.state.key_off(self.state.last_mouse_key)
                        self.state.key_on(mouseover, sample=sample)
                        self.state.last_mouse_key = mouseover
                else:
                    self.state.key_off(self.state.last_mouse_key)
                    self.state.last_mouse_key = None
                    
        
class APUHistGraph():
    hist_length = 75 * 3
    hist_height = 200 * 3
    thickness = 3 * 5
    width = 3
    def __init__(self):
        self.history = [ [] for i in range(self.hist_length)]
        self.queue = []
        
    def record(self, voice):
        if voice.envx > 0:
            self.queue.append((voice.pitch, voice.envx, voice.srcn, (voice.volL + voice.volR)))
        
    def draw(self, id):
        self.history.pop(0)
        self.history.append(self.queue)
        self.queue = []
        imgui.begin_group()
        imgui.begin_child(id, self.hist_length * self.width, self.hist_height, border=True)
        if apu.playing:
            draw = imgui.get_window_draw_list()
            xpos, ypos = imgui.get_cursor_screen_pos()
            draw.add_text(xpos + 5, ypos + 5, icolor(15, .67), id)
            for i, snapshot in enumerate(self.history):
                for voice in snapshot:
                    vxpitch, envx, srcn, vol = voice
                    xpos, ypos = imgui.get_cursor_screen_pos()
                    xpos += i * self.width
                    alpha = (i / self.hist_length) * (envx/128) 
                    thick = (i / self.hist_length) * (envx*self.thickness/128) * (vol/128)
                    key = apu.samp[srcn].pitch_to_key(vxpitch, int=False)
                    ypos += self.hist_height - (key * self.hist_height/93)
                    ypos += srcn - 0x20
                    draw.add_line(xpos, ypos, xpos + self.width, ypos,
                            icolor(srcn % 16, alpha), thick)
        else:
            self.__init__()
        imgui.end_child()
        imgui.end_group()
        
class TrackViz():
    def __init__(self):
        self.show_track_id = True
        self.show_sample_icon = True
        self.show_sample_id = True
        self.show_sample_name = True
        self.show_lr_volume = False
        self.show_engine_volume = True
        self.show_generic_pan = False
        self.show_engine_pan = True
        self.show_adsr = True
        self.show_general_flags = True
        self.show_engine_flags = True
        self.show_env_meter = True
        self.show_piano = True
        self.show_extra_engine_debug = False
        
    def draw(self, idx, dsp, engine):
        vo = dsp.voice[idx]
        evo = engine.v[idx]
        bitmask = 1 << idx
        
        padding = UNIT / 4
        widgetheight = UNIT
        widgetheight += UNIT if self.show_sample_name else 0
        widgetheight += UNIT / 4 + 2 if self.show_env_meter else 0
        
        #imgui.new_line()
        #imgui.begin_group()
        with imgui.istyled(imgui.STYLE_WINDOW_PADDING, (1, 1)):
            imgui.begin_child(f"##tvizchild{idx}", 300, widgetheight + 2, border=True)
            minx, miny = imgui.get_cursor_screen_pos()
            mainx = minx
            
            if self.show_track_id:
                with imgui.font(BIGGERFONT):
                    sizex, sizey = imgui.calc_text_size(f"{idx + 1}")
                    imgui.set_cursor_screen_pos((minx, miny + (widgetheight / 2 - sizey / 2)))
                    imgui.text(f"{idx + 1}")
                    mainx += sizex + padding
                #mainx = imgui.get_item_rect_max()[0]
            
            x, y = mainx, miny
            if self.show_sample_name:
                imgui.set_cursor_screen_pos((mainx, miny))
                imgui.begin_group()
                if self.show_sample_id:
                    imgui.text(f"{vo.srcn:02X}")
                    x = imgui.get_item_rect_max()[0] + padding
                    imgui.set_cursor_screen_pos((x, miny))
                if vo.srcn in apu.samp:
                    text = f"{apu.samp[vo.srcn].name}"
                else:
                    text = "---"
                with imgui.font(SMALLERFONT):
                    imgui.text(text)
                y = imgui.get_item_rect_max()[1]
                imgui.end_group()
            
            imgui.begin_group()
            x = mainx
            if self.show_sample_id and not self.show_sample_name:
                imgui.set_cursor_screen_pos((x, y))
                imgui.text(f"{vo.srcn:02X}")
                x += imgui.calc_text_size("aaa")[0] + padding
            if self.show_lr_volume:
                pass
            if self.show_engine_volume:
                imgui.set_cursor_screen_pos((x, y))
                imgui.text(f"Vol {evo.volume}")
                x += imgui.calc_text_size("Vol 127")[0] + padding
            if self.show_generic_pan:
                pass
            if self.show_engine_pan:
                imgui.set_cursor_screen_pos((x, y))
                #imgui.text(f"Pan {evo.pan_pct:.2%} ")
                knob(f"knobpan{idx}", evo.pan_pct, min=-1)
                x += UNIT + padding
            if self.show_adsr:
                imgui.set_cursor_screen_pos((x, y))
                env = Envelope(bin=bytes(vo.adsr))
                imgui.text(f"A{env.a} D{env.d} S{env.s} R{env.r}")
                x += imgui.calc_text_size("Axx Dx Sx Rxx")[0] + padding
            flag_text = ""
            if self.show_general_flags:
                if dsp.s.pmon & bitmask:
                    flag_text += "Pmod "
                if dsp.s.non & bitmask:
                    flag_text += "Noise "
                if dsp.s.eon & bitmask:
                    flag_text += "Echo "
            if self.show_engine_flags:
                if evo.slur:
                    flag_text += "Legato "
                if evo.gapless:
                    flag_text += "Gapless "
            if flag_text:
                imgui.set_cursor_screen_pos((x, y))
                imgui.text(flag_text.strip())
            imgui.end_group()
            x = mainx
            y = imgui.get_item_rect_max()[1]
            
            imgui.begin_group()
            if self.show_env_meter:
                imgui.set_cursor_screen_pos((x, y))
                imgui.begin_child(f"##tvizenv{idx}", 129, UNIT / 4 + 2, border=True)
                draw = imgui.get_window_draw_list()
                xorig, yorig = imgui.get_cursor_screen_pos()
                draw.add_rect_filled(xorig, yorig, xorig + vo.envx, yorig + UNIT / 2,
                        icolor(vo.srcn % 16, 1))
                imgui.end_child()
            imgui.end_group()
            
            imgui.begin_group()
            if self.show_extra_engine_debug:
                imgui.text(f"Loop level {evo.loop_level}")
                imgui.text(f"Octave {evo.octave}")
            imgui.end_group()
            
            
            imgui.end_child()
        #imgui.end_group()
        
def icolor(i, alpha):
    index = {
            0: (1, .5, .5),
            6: (1, .75, .5),
            1: (1, 1, .5),
            7: (.75, 1, .5),
            2: (.5, 1, .5),
            8: (.5, 1, .75),
            3: (.5, 1, 1),
            9: (.5, .75, 1),
            4: (.67, .67, 1),
            10: (.75, .5, 1),
            5: (1, .5, 1),
            11: (1, .5, .75),
            12: (.8, .6, .6),
            13: (.6, .8, .6),
            14: (.6, .6, .8),
            15: (.8, .8, .8)
            }
    return imgui.get_color_u32_rgba(*index[i], alpha)
    
def octave_colors(idx, alpha):
    return imgui.get_color_u32_rgba(*octave_colors_[idx], alpha)
    
octave_colors_ = [
        (.30, .30, .30), #0
        (.35, .30, .30), #1
        (.35, .30, .35), #2
        (.35, .30, .40), #3
        (.35, .35, .40), #4
        (.35, .40, .40), #5
        (.35, .40, .35), #6
        (.40, .40, .35), #7
        (.45, .40, .35), #8
        (.45, .40, .40), #9
        (.45, .45, .45), #10
        ]
        