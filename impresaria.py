# Project notes for later

# PyWin32 looks like the place to go for dragon-drop
# Example @ https://www.reddit.com/r/Python/comments/hsq43/drag_and_drop_with_pygame/ 
# That should handle dropping onto the program itself but may not handle subwindows
# ImGui/C++ example @ https://github.com/ocornut/imgui/issues/2602
# This example integrates with ImGui D&D functions

import colorsys
import os
import sys
import math

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame
import pygame.midi
import OpenGL.GL as gl
from imgui.integrations.pygame import PygameRenderer
import imgui
import win32gui
import win32con

from audio import PianoState, scale_to_unity_key
from project import Project
from rom import Rom
from formats import clamp
from spc import build_and_play_spc, apu
from messenger import (KEY, log, std, err, pretty_bytes, vblank,
        init_meta, write_metadata, repr_bank)
import widgets

prj = None
errorbox = None
UNIT = 13
cur_seq = 0
cur_smp = 1
midi_device = None
midi_state = PianoState(play_audio=True)
io = None
logo_texture = None
log_text = ""
temporary_status_text = ""
main_window_mode = "seq"
WINW, WINH, WINSCALE = 1280, 720, 1
MAIN_MENU_HEIGHT = 15
JPFONT, SMALLERFONT, BIGGERFONT = None, None, None

MAIN_WINDOW_FLAGS = (imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_COLLAPSE
        | imgui.WINDOW_NO_BRING_TO_FRONT_ON_FOCUS | imgui.WINDOW_NO_TITLE_BAR)

def set_main_window_dims():
    head = UNIT * 6 + MAIN_MENU_HEIGHT
    foot = UNIT * 10
    right = (202 / 1280) * WINW
    imgui.set_next_window_position(0, head)
    imgui.set_next_window_size(WINW - right, WINH - head - foot)
    
def main():
    global UNIT
    global io
    global errorbox
    global control_window
    global midi_state
    global cur_seq, cur_smp
    global temporary_status_text
    global main_window_mode
    global logo_texture
    global WINW, WINH, WINSCALE
    global MAIN_MENU_HEIGHT
    global JPFONT, SMALLERFONT, BIGGERFONT
    
    # # # Declarations # # #    
    new_project_window = None
    
    errorbox = ErrorBox()
    
    init_meta()
    
    # # # Backend initialization # # #
    
    pygame.mixer.pre_init(frequency=32000, size=-16, channels=2, buffer=1024)
    pygame.init()
    pygame.fastevent.init()
    
    pygame.mixer.set_num_channels(32)
    pygame.midi.init()
    apu.init()
        
    pygame.display.set_mode((WINW, WINH), pygame.DOUBLEBUF | pygame.OPENGL | pygame.RESIZABLE)
    
    imgui.create_context()
    impl = PygameRenderer()
    impl.io.key_map[imgui.KEY_SPACE] = pygame.K_SPACE
    
    io = imgui.get_io()
    io.config_flags |= imgui.CONFIG_NAV_ENABLE_KEYBOARD
    io.display_size = (WINW, WINH)
    
    JPFONT = io.fonts.add_font_from_file_ttf("res/SourceHanCodeJP-Medium.otf", 16,
            io.fonts.get_glyph_ranges_japanese())
    SMALLERFONT = io.fonts.add_font_from_file_ttf("res/SourceHanCodeJP-Bold.otf", 12,
            io.fonts.get_glyph_ranges_japanese())
    BIGGERFONT = io.fonts.add_font_from_file_ttf("res/SourceHanCodeJP-Bold.otf", 32,
            io.fonts.get_glyph_ranges_japanese())
    impl.refresh_font_texture()
    widgets.share_fonts(JPFONT, SMALLERFONT, BIGGERFONT)
    
    # # # Pre-loop initializations # # #
    
    control_window = ControlWindow()
    
    # # # Main loop # # #
    while True:
        key_ups = []
        key_downs = []
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                key_downs.append(event)
            elif event.type == pygame.KEYUP:
                key_ups.append(event)
            elif event.type == pygame.QUIT:
                cleanup_and_quit()
                
            impl.process_event(event)
        KEY.update(key_downs, key_ups)
        
        imgui.new_frame()
        vblank.tick()
        
        dispinfo = pygame.display.Info()
        
        display_size_changed = True if (dispinfo.current_w != WINW
                or dispinfo.current_h != WINH) else False
        WINW, WINH = dispinfo.current_w, dispinfo.current_h
        io.display_size = WINW, WINH
        WINSCALE = WINW / 1280
        UNIT = imgui.get_text_line_height_with_spacing()
        widgets.share_units(WINW, WINH, WINSCALE, UNIT)
        
        imgui.push_font(JPFONT)
        # # Textures # #
        
        if display_size_changed or not logo_texture:
            logo_texture = Texture(os.path.join("res", "impresaria.png"))

        # # Keys # #
        if KEY.UP(pygame.K_F1):
            main_window_mode = "seq"
        elif KEY.UP(pygame.K_F2):
            main_window_mode = "smp"
        elif KEY.UP(pygame.K_F3):
            main_window_mode = "rom"

        # # Menu # #
        make_a_new_project_window_this_frame = False
        
        if imgui.begin_main_menu_bar():
            if imgui.begin_menu("File", True):
                c, _ = imgui.menu_item("New Project / Open Project...", "", False, True)
                make_a_new_project_window_this_frame = c
                c, _ = imgui.menu_item("Save Project", "Ctrl-S", False, True)
                if c:
                    print(prj.serialize())
                    print(len(prj.serialize()))
                imgui.separator()
                c, _ = imgui.menu_item("Revert sequence and sample names", "NYI", False, True)
                c, _ = imgui.menu_item("Save sequence and sample names", "", False, True)
                if c:
                    write_metadata(prj.seq, prj.brr)
                imgui.separator()
                c, _ = imgui.menu_item("Quit", 'Alt-F4', False, True)
                if c:
                    cleanup_and_quit()
                imgui.end_menu()
            
            if widgets.glow_button("Sequences (F1)", main_window_mode == "seq"):
                main_window_mode = "seq"
            if widgets.glow_button("Samples (F2)", main_window_mode == "smp"):
                main_window_mode = "smp"
            if widgets.glow_button("ROM Map (F3)", main_window_mode == "rom"):
                main_window_mode = "rom"
                
            MAIN_MENU_HEIGHT = imgui.get_window_size()[1]
            imgui.end_main_menu_bar()
        
        # # Main UI # #
        display_side_panel()
        
        if prj is None:
            if not new_project_window:
                new_project_window = NewProjectWindow()
            new_project_window.draw()
            if prj:
                new_project_window = None
        elif prj.init_status is not True:
            #temporary_status_text = f"{prj.frame_init()}"
            pass
        else:
            control_window.display()
            
            if main_window_mode == "seq":
                display_sequence_window()
            elif main_window_mode == "smp":
                display_sample_window()
            elif main_window_mode == "rom":
                rom_map_window.draw()
                
            display_spc_debug()
            
            if make_a_new_project_window_this_frame:
                new_project_window = NewProjectWindow(allow_cancel = True)
            if new_project_window:
                done = new_project_window.draw()
                if done is True:
                    new_project_window = None
            
        # # Messenger # #
        
        display_log_window()
        handle_stdout()
        errorbox.draw(end_frame=True)
        
        # # Audio / Vblank Loop # #
        
        #print(pygame.time.get_ticks() - vblank._tick)
        while True:
            
            if midi_device and prj is not None and prj.init_status is True:
                if midi_device.poll():
                    midi_events = midi_device.read(16)
                    midi_state.read_midi(prj.brr[cur_smp], midi_events)
            midi_state.sustain()
            
            if vblank.ok and prj is not None and prj.init_status is not True:
                temporary_status_text = f"{prj.frame_init()}"
                
            if not vblank.ok:
                break
            
        apu.update()
        
        imgui.pop_font()
        # note: cannot use screen.fill((1, 1, 1)) because pygame's screen
        #       does not support fill() on OpenGL sufraces
        gl.glClearColor(0, 0, 0, 1)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        impl.render(imgui.get_draw_data())

        pygame.display.flip()
        
class NewProjectWindow():
    def __init__(self, allow_cancel=False):
        self.new_source = "ff6.smc"
        self.new_name = "New Project"
        self.load_prj_fn = ""
        self.recent_prj_idx = 0
        self.allow_cancel = allow_cancel
        
        imgui.open_popup("New Project")
        
    def draw(self):
        global prj
        global cur_seq, cur_smp
        
        return_true = False # Return true if dialog is finished, regardless of 
                            # whether a new project is opened.
        if imgui.begin_popup_modal("New Project", True, imgui.WINDOW_NO_COLLAPSE)[0]:
            imgui.text("Welcome to Impresaria Final Fantasy!")
            imgui.text("Where all* your dreams come true!")
            imgui.text("*As long as those dreams involve editing the music in Final Fantasy VI SNES/SFC.")
            imgui.separator()
            imgui.text("To get started, you need to either create a new project by selecting a "
                       "source ROM, or open an existing project file.")
            imgui.separator()
            imgui.text("Create new project:")
            imgui.text("Source ROM file:")
            _, self.new_source = imgui.input_text("##newsrc", self.new_source, 256)
            imgui.same_line()
            if imgui.button("..."):
                self.new_source = open_file_dialog("Open ROM", self.new_source,
                        [("SNES ROM files", "*.smc;*.sfc;*.swc;*.fig"),
                        ("Python files", "*.py"),
                        ("Git files", "*.git*"),
                        ("All files", "*.*")])
            imgui.text("Project name:")
            _, self.new_name = imgui.input_text("##newname", self.new_name, 256)
            if imgui.button("Create new project"):
                rom = Rom(self.new_source)
                if rom.is_valid:
                    imgui.close_current_popup()
                    cur_seq = 0
                    cur_smp = 1
                    prj = Project(self.new_name, rom)
                    return_true = True
            imgui.spacing()
            imgui.separator()
            imgui.spacing()
            imgui.text("Open existing project:")
            imgui.text("Filename:")
            _, self.load_prj_fn = imgui.input_text("##prjfile", self.load_prj_fn, 256)
            _, self.recent_prj_idx = imgui.listbox("Recent files", self.recent_prj_idx, ["Not", "yet", "implemented"])
            imgui.button("Open project")
            if self.allow_cancel:
                imgui.same_line()
                if imgui.button("Cancel"):
                    imgui.close_current_popup()
            
            errorbox.draw()
            imgui.end_popup()
            return return_true
        elif not self.allow_cancel:
            imgui.open_popup("New Project")
            return False
        else:
            return True

class ControlWindow():
    def __init__(self):
        self.selected_midi_device = 0
        self.init_midi()
        
    def init_midi(self):
        self.midi_input_devices = ["None"]
        self.midi_input_indices = [None]
        default = pygame.midi.get_default_input_id()
        for i in range(pygame.midi.get_count()):
            ifc, name, inp, out, open = pygame.midi.get_device_info(i)
            name = name.decode()
            if inp:
                self.midi_input_devices.append(name)
                self.midi_input_indices.append(i)
                if i == default:
                    self.midi_input_devices[0] = f"Default ({name})"
                    self.midi_input_indices[0] = i
        
    def display(self):
        global cur_seq
        global cur_smp
        global midi_device
        
        imgui.set_next_window_position(0, MAIN_MENU_HEIGHT)
        imgui.set_next_window_size(WINW, UNIT * 6)
        imgui.begin("Controls", False, MAIN_WINDOW_FLAGS)
        
        imgui.begin_group()
        imgui.text("Current sequence:")
        imgui.same_line()
        imgui.push_item_width(UNIT * 9)
        _, cur_seq = imgui.input_int("##seq", cur_seq, 1, 16, flags= imgui.INPUT_TEXT_CHARS_HEXADECIMAL)
        cur_seq = clamp(0, cur_seq, len(prj.seq))
        cur_smp_text = prj.repr_smp(cur_smp)[:2]
        _, cur_smp_text = imgui.input_text("##smp", cur_smp_text, 8)
        imgui.pop_item_width()
        imgui.end_group()
        
        imgui.same_line(spacing=UNIT * 3)
        imgui.begin_group()
        if imgui.button("Play (external)"):
            build_and_play_spc(prj, cur_seq)
        if apu.playing:
            if imgui.button("Stop (internal)"):
                apu.stop()
        else:
            if imgui.button("Play (internal)"):
                apu.play_id(prj, cur_seq)
        imgui.end_group()
        
        imgui.begin_group()
        pia = widgets.Piano(midi_state, interactive=True)
        piaw = pia.get_width(first=0, last=127, scale=1.5)
        imgui.set_cursor_pos((imgui.get_window_width() - 5 - piaw, 5))
        prjsmp = prj.brr[cur_smp] if (prj and prj.init_status is True) else None
        pia.draw("##pia", first=0, last=127, scale=1.5, sample=prjsmp)
        imgui.end_group()
        
        with imgui.istyled(imgui.STYLE_WINDOW_PADDING, (1, 1)):
            imgui.set_cursor_pos((imgui.get_window_width() - 5 - piaw,
                    imgui.get_window_height() * 3 / 4 - (UNIT * 1.25)))
            imgui.begin_child("##piano_text_chile", piaw, UNIT * 2.1, border=False)
            
            imgui.align_text_to_frame_padding()
            imgui.text("Sample:")
            imgui.same_line()
            imgui.push_item_width(UNIT * 9)
            cur_smp_last = cur_smp
            _, cur_smp = imgui.input_int("##smp", cur_smp, step=1, step_fast=16,
                    flags = imgui.INPUT_TEXT_CHARS_HEXADECIMAL)
            cur_smp = validate_cur_smp(cur_smp, cur_smp_last)
            #cur_smp = max(1, cur_smp)
            #if 256 > cur_smp > len(prj.get_samples()):
            #    if cur_smp_last >= 256:
            #        cur_smp -= 255 - len(prj.get_samples())
            #    else:
            #        cur_smp += 255 - len(prj.get_samples())
            #if cur_smp > (255 + len(prj.brr) - len(prj.get_samples())):
            #    cur_smp = 255 + len(prj.brr) - len(prj.get_samples())
            imgui.pop_item_width()
            
            imgui.same_line()
            imgui.text(prj.brr[cur_smp].name)
            
            x, y = imgui.get_window_content_region_max()
            imgui.set_cursor_pos((x * 2 / 3, 0))
            if midi_device is None:
                if imgui.button("[ ]"):
                    try:
                        midi_device = pygame.midi.Input(
                                self.midi_input_indices[self.selected_midi_device])
                    except Exception:
                        log.send("Could not initialize MIDI input "
                                f"'{self.midi_input_devices[self.selected_midi_device]}'")
            else:
                if widgets.glow_button("[x]", True, (.2, .5, .2)):
                    midi_device = None
            imgui.same_line()
            imgui.text(f"MIDI:")
            imgui.same_line()
            c, self.selected_midi_device = imgui.combo(f"##MidiDeviceCombo",
                    self.selected_midi_device, self.midi_input_devices)
            if c:
                midi_device = None
            imgui.end_child()
        
        imgui.end()
control_window = None

def display_midi_debug():
    global midi_device

    imgui.begin("MIDI Debug", False)
    for i in range(pygame.midi.get_count()):
        if imgui.button(f"Use##{i}"):
            midi_device = pygame.midi.Input(i)
        imgui.same_line()
        ifc, name, inp, out, open = pygame.midi.get_device_info(i)
        imgui.text(f"Interface: {ifc} || {name} || {inp} || {out} || {open}")
    if imgui.button("Release"):
        midi_device = None
    if imgui.button("Default"):
        midi_device = pygame.midi.Input(pygame.midi.get_default_input_id())
    imgui.same_line()
    imgui.text(f"{pygame.midi.get_default_input_id()}")
    imgui.text(f"{midi_device}")
    imgui.separator()
    imgui.text(f"MIDI state: {midi_state}")
    imgui.end()
    
big_apu_graph = widgets.APUHistGraph()
piano_alpha = [0.0 for i in range(0x30)]
def display_spc_debug():
    global big_apu_graph
    if apu.initialized:
        dsp, engine = apu.get_dsp()
        
        pianos = [widgets.Piano() for i in range(0x30)]
        piano_ids = [f"{i:02X}##DebugPiano{i:02X}" for i in range(0x30)]
        piano_fade_rate = 0.1
        
        hist_length = 50
        hist_height = 150
        if not apu.playing:
            big_apu_graph = widgets.APUHistGraph()
        imgui.begin("SPC Debug", False)
        imgui.begin_group()
        imgui.begin_group()
        for i in range(8):
            vo = dsp.voice[i]
            srcn = int(vo.srcn)
            if vo.envx > 0:
                big_apu_graph.record(vo)
            if i % 4:
                imgui.same_line()
            imgui.text(f"Ch. {i+1} | vxPitch {vo.pitch}\nPRG ${vo.srcn:02X} | Env {vo.envx}")
            if vo.envx and (vo.volL + vo.volR):
                #pianos[i+10].state.key_on(round(scale_to_unity_key(vo.pitch / 4096)))
                pianos[i+10].state.key_on(apu.samp[srcn].pitch_to_key(vo.pitch))
                piano_alpha[i+10] = 1.0
                #pianos[srcn].state.key_on(round(scale_to_unity_key(vo.pitch / 4096)))
                pianos[srcn].state.key_on(apu.samp[srcn].pitch_to_key(vo.pitch))
                piano_alpha[srcn] = 1.0
        imgui.end_group()
        
        imgui.begin_group()
        for i in range(10, 18):
            if piano_alpha[i] and not pianos[i].state.any_key_is_on():
                piano_alpha[i] = max(piano_alpha[i] - piano_fade_rate, 0.0)
            imgui.text(f"T{i-9:X}")
            imgui.same_line()
            pianos[i].draw(piano_ids[i], first=36,
                    alpha=piano_alpha[i])
        imgui.dummy(UNIT, UNIT)
        for i in range(0, 8):
            if piano_alpha[i] and not pianos[i].state.any_key_is_on():
                piano_alpha[i] = max(piano_alpha[i] - piano_fade_rate, 0.0)
            imgui.text(f"@{i:X}")
            imgui.same_line()
            pianos[i].draw(piano_ids[i], first=36,
                    alpha=piano_alpha[i])
        imgui.end_group()
        
        imgui.same_line()
        imgui.begin_group()
        big_apu_graph.draw("##big_apu_graph")
        imgui.end_group()
        imgui.end_group()
        
        imgui.same_line()
        imgui.begin_group()
        for i in range(0x20, 0x30):
            if piano_alpha[i] and not pianos[i].state.any_key_is_on():
                piano_alpha[i] = max(piano_alpha[i] - piano_fade_rate, 0.0)
            if i in apu.samp:
                imgui.dummy(UNIT, 1)
                imgui.same_line()
                with imgui.font(SMALLERFONT):
                    imgui.text(f"{{{apu.seq.inst[i-0x20]:02X}}} {apu.samp[i].name}")
                x, y = imgui.get_cursor_pos()
                imgui.set_cursor_pos((x, y - 3))
            imgui.text(f"{i:02X}")
            imgui.same_line()
            pianos[i].draw(piano_ids[i], first=36,
                    alpha=piano_alpha[i])
        imgui.end_group()
        
        imgui.end()
        
        ## SPC debug window 2
        
        with imgui.istyled(imgui.STYLE_WINDOW_PADDING, (1, 1)):
            imgui.begin("SPC Debug 2")
            track_vizen = []
            for i in range(8):
                track_vizen.append(widgets.TrackViz())
                track_vizen[i].draw(i, dsp, engine)
                pianos[i+10].draw(piano_ids[i+10], first=36,
                    alpha=piano_alpha[i+10])
            imgui.end()
        
def display_sequence_window():
    global cur_seq
    
    smp_list = [f"{i:02X}" for i in range(len(prj.get_samples())+1)]
            
    if KEY.UP(pygame.K_PAGEUP):
        cur_seq = clamp(0, cur_seq - 1, len(prj.seq))
        seq_changed_keyboard = True
    elif KEY.UP(pygame.K_PAGEDOWN):
        cur_seq = clamp(0, cur_seq + 1, len(prj.seq))
        seq_changed_keyboard = True
    else:
        seq_changed_keyboard = False
    
    cseq = prj.seq[cur_seq]
        
    def inst_widget(idx):
        imgui.begin_group()
        imgui.text(f"{idx+0x20:02X}")
        imgui.push_item_width(int(UNIT * 3.5))
        c, s = imgui.combo(f"##inst{idx}cbx", cseq.inst[idx], smp_list)
        cseq.inst[idx] = s
        imgui.pop_item_width()
        imgui.end_group()
        
    set_main_window_dims()
    imgui.begin("Sequences", False, MAIN_WINDOW_FLAGS)
    n_items = int((imgui.get_window_height() / (1.5 * UNIT)) - 1)
    
    imgui.push_item_width(imgui.get_window_width() * 0.3)
    imgui.begin_group()
    lst = [prj.repr_seq(i) for i in range(len(prj.seq))]
    _, cur_seq = imgui.listbox("##seqlist", cur_seq, lst, n_items)
    imgui.end_group()
    imgui.pop_item_width()
    
    imgui.same_line(spacing=UNIT * 3)
    imgui.begin_group()
    imgui.text("Name:")
    imgui.same_line()
    if seq_changed_keyboard:
        imgui.set_keyboard_focus_here(0)
    _, cseq.name = imgui.input_text(f"##sequence{cur_seq}name", cseq.name, 64)
    if cur_seq in prj.format.default_track_names:
        imgui.text(f"Originally: {prj.format.default_track_names[cur_seq]}")
    imgui.text(f"${len(cseq.get_data()):X} bytes")
    try:
        imgui.text(f"Address: ${prj.alloc.get_address(f'seq{cur_seq:02X}'):06X}")
    except TypeError:
        imgui.text(f"Address: {prj.alloc.get_address(f'seq{cur_seq:02X}')}")
    
    imgui.begin_group()
    for i in range(2):
        for j in range(8):
            if j > 0:
                imgui.same_line()
            inst_widget(j + i*8)
    imgui.end_group()
    
    imgui.begin_child("##rawmml")
    imgui.text_unformatted(cseq.raw_mml)
    imgui.end_child()
    imgui.end_group()
    
    imgui.end()
    
def cur_smp_to_idx(cur_smp_):
    if cur_smp_ >= 256:
        idx = cur_smp_ - 256 + len(prj.get_samples())
    else:
        idx = cur_smp_ - 1
    return idx
    
def idx_to_cur_smp(idx):
    cur_smp_ = idx + 1
    non_fixed_sample_count = len(prj.get_samples())
    if cur_smp_ > non_fixed_sample_count:
        cur_smp_ = cur_smp_ + 255 - non_fixed_sample_count
    return cur_smp_
    
def validate_cur_smp(cur_smp, cur_smp_last):
    cur_smp = max(1, cur_smp)
    if 256 > cur_smp > len(prj.get_samples()):
        if cur_smp_last >= 256:
            cur_smp -= 255 - len(prj.get_samples())
        else:
            cur_smp += 255 - len(prj.get_samples())
    if cur_smp > (255 + len(prj.brr) - len(prj.get_samples())):
        cur_smp = 255 + len(prj.brr) - len(prj.get_samples())
    return cur_smp
        
def display_sample_window():
    global cur_seq, cur_smp
    
    cur_smp_last = cur_smp
    if KEY.UP(pygame.K_PAGEUP):
        cur_smp -= 1
        smp_changed_keyboard = True
    elif KEY.UP(pygame.K_PAGEDOWN):
        cur_smp += 1
        smp_changed_keyboard = True
    else:
        smp_changed_keyboard = False
    cur_smp = validate_cur_smp(cur_smp, cur_smp_last)
    
    csmp = prj.brr[cur_smp]
    
    set_main_window_dims()
    imgui.begin("Samples", False, MAIN_WINDOW_FLAGS)
    n_items = int((imgui.get_window_height() / (1.5 * UNIT)) )
    
    imgui.push_item_width(imgui.get_window_width() * 0.3)
    imgui.begin_group()
    lst = [prj.repr_smp(i) for i in sorted(prj.brr.keys())]
    cur_smp_tmp = cur_smp_to_idx(cur_smp)
    c, cur_smp_tmp = imgui.listbox("##smplist", cur_smp_tmp, lst, n_items)
    if c:
        cur_smp = idx_to_cur_smp(cur_smp_tmp)
    imgui.end_group()
    imgui.pop_item_width()
    
    imgui.same_line(spacing=UNIT)
    imgui.begin_group()
    
    imgui.text("Name:")
    if smp_changed_keyboard:
        imgui.set_keyboard_focus_here(0)
    imgui.same_line()
    _, csmp.name = imgui.input_text("##samplename", csmp.name, 64)
    smplen = len(csmp.get_data())
    imgui.text(f"{smplen // 9} blocks || ${smplen:X} bytes")
    try:
        imgui.text(f"Address: ${prj.alloc.get_address(f'brr{cur_smp:02X}'):06X}")
    except TypeError:
        imgui.text(f"Address: {prj.alloc.get_address(f'brr{cur_smp:02X}')}")
    clones = prj.sample_get_clones(cur_smp)
    if clones is not None:
        clonetext = ""
        if clones[1]:
            clonetext = (clonetext + "Duplicated by " + ''.join(
                    [f"{i:02X}, " for i in clones[1]]))[:-2] + ". "
        if clones[0]:
            clonetext = (clonetext + "Shares data with " + ''.join(
                    [f"{i:02X}, " for i in clones[0]]))[:-2] + "."
        imgui.text(clonetext)
    imgui.plot_lines("##waveplot", prj.brr[cur_smp].pcmarray,
            graph_size=(imgui.get_window_width() * 0.66, UNIT * 5))

    imgui.begin_group()
    etypes = (
            # id, text, clamp max
            ("##attack",  "A", 15),
            ("##decay",   "D", 7),
            ("##sustain", "S", 7),
            ("##release", "R", 31)
            )
    csenv = csmp.env
    env_vals = [csenv.a, csenv.d, csenv.s, csenv.r]
    for i, etype in enumerate(etypes):
        if i > 0:
            imgui.same_line()
        imgui.text(etype[1])
        imgui.same_line()
        imgui.push_item_width(imgui.get_window_width() * 0.1)
        _, env_vals[i] = imgui.input_int(etype[0], env_vals[i], 1, 1, imgui.INPUT_TEXT_CHARS_DECIMAL)
        env_vals[i] = clamp(0, env_vals[i], etype[2])
        imgui.pop_item_width()
        imgui.same_line()
        imgui.dummy(UNIT, UNIT)
    imgui.end_group()
    csenv.a, csenv.d, csenv.s, csenv.r = env_vals
    
    imgui.push_item_width(imgui.get_window_width() * 0.2)
    imgui.begin_group()
    imgui.text("Pitch:")
    imgui.same_line()
    _, csmp.pitch = imgui.input_int("##rawpitch", csmp.pitch, 1, 1, imgui.INPUT_TEXT_CHARS_HEXADECIMAL
            | imgui.INPUT_TEXT_CHARS_UPPERCASE)
    imgui.same_line()
    imgui.text("Scale:")
    imgui.same_line()
    c, pscale = imgui.slider_float("##scalepitch", csmp.get_pitch_as_scale(), 0.5, (0x17FFF/0x10000))
    if c:
        csmp.pitch = int((pscale - 1) * 0x10000)
    imgui.end_group()
    
    if csmp.is_looped:
        imgui.text(f"Loop: ON -- at {csmp.loop // 9} blocks")
    else:
        imgui.text("Loop: OFF")
        
    used_in = {k: seq for k, seq in prj.seq.items() if cur_smp in seq.inst.values()}
    imgui.begin_group()
    imgui.text("Sample is used in:")
    if used_in:
        imgui.begin_child("##sample_used_in", imgui.get_window_width() * 0.5,
                imgui.get_window_height() * 0.4)
        namelen = max(10, *[len(seq.name) for seq in used_in.values()])
        for k, seq in used_in.items():
            if cur_smp in seq.inst.values():
                if imgui.small_button(f"{k:02X} {seq.name:{namelen}}##sample_used_in"):
                    cur_seq = k
                text = "as " + ''.join([f"{prg+0x20:02X}, "
                        for prg, sid in seq.inst.items() if sid == cur_smp])
                imgui.same_line()
                imgui.text(text[:-2])
        imgui.end_child()
    else:
        imgui.text("        Nothing!")
    imgui.end_group()
    
    imgui.end_group()
    imgui.end()

class RomMapWindow():
    def __init__(self):
        self.remove_range_qbox = None
        self.selected_range = None
        self.asking_for_range = False
        self.enter_range_start = None
        self.enter_range_end = None
        self.dialog_label = ""
        
    def ask_for_range(self, label):
        self.asking_for_range = True
        self.enter_range_start = None
        self.enter_range_end = None
        self.dialog_label = label
        
    def draw(self):
        
        set_main_window_dims()
        imgui.begin("ROM Map", False, MAIN_WINDOW_FLAGS)
        
        imgui.begin_group()
        imgui.push_text_wrap_pos(imgui.get_content_region_available_width() * .5)
        imgui.text("This page shows the ROM addresses that Impresaria will write to. ")
        imgui.text("On creating a new project, this is populated with the addresses "
                "of the music data found in the source ROM. You will often need to "
                "specify additional free space in order to export a finalized ROM.")
        imgui.text("ALL PREVIOUS DATA within this space will be lost! Make sure to "
                "keep backups of your source ROMs.")
        imgui.end_group()
        
        imgui.begin_group()
        if imgui.button("Add range"):
            self.ask_for_range("add")
        imgui.same_line()
        if imgui.button("Release range"):
            self.ask_for_range("release")
        imgui.end_group()
        
        imgui.begin_group()
        imgui.begin_child("##allocation")
        imgui.columns(5, "AllocatorCols")
        
        imgui.separator()
        imgui.text("-")
        imgui.next_column()
        imgui.text("Start - End")
        imgui.next_column()
        imgui.text("Size")
        imgui.next_column()
        imgui.text("Used")
        imgui.next_column()
        imgui.text("Free")
        imgui.next_column()
        imgui.separator()
        
        for ra in prj.alloc.ranges:
            used, free = prj.alloc.get_space_usage(ra.start)
            pct = used / ra.length
            imgui.set_column_width(0, UNIT * 4)
            if imgui.button(f"Remove##{ra.start}"):
                self.remove_range_qbox = QuestionBox("Are you sure you want to "
                        "de-allocate\n the range "
                        f"{repr_bank(ra.start)} - {repr_bank(ra.end)}?",
                        uid = ra.start)
                self.selected_range = (ra.start, ra.end)
            imgui.next_column()
            imgui.text(f"{repr_bank(ra.start)} - {repr_bank(ra.end)}")
            imgui.next_column()
            imgui.text(f"${ra.length:X} bytes")
            imgui.next_column()
            imgui.text(f"${used:X} bytes ({pct:.1%})")
            imgui.next_column()
            imgui.text(f"${free:X} bytes ({1 - pct:.1%})")
            imgui.next_column()
            
        imgui.end_child()
        imgui.columns(1)
        imgui.end_group()
        
        try:
            answer = self.remove_range_qbox.draw()
            if answer is True:
                log.send(f"Released range {repr_bank(self.selected_range[0])} "
                        f"to {repr_bank(self.selected_range[1])}")
                prj.alloc.release(*self.selected_range)
            if answer is not None:
                self.remove_range_qbox = None
                self.selected_range = None
        except AttributeError:
            if self.asking_for_range:
                imgui.open_popup(f"Enter range to {self.dialog_label}")
                self.asking_for_range = False
            if imgui.begin_popup_modal(f"Enter range to {self.dialog_label}",
                    True, imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
                _, self.enter_range_start = widgets.range_entry(
                        "##askrangestart", self.enter_range_start)
                imgui.same_line()
                _, self.enter_range_end = widgets.range_entry(
                        "##askrangeend", self.enter_range_end)
                if imgui.button("OK", width = UNIT * 4):
                    if None in (self.enter_range_start, self.enter_range_end):
                        err.send("Enter a valid start and end.")
                    else:
                        if self.dialog_label == "add":
                            prj.alloc.add(self.enter_range_start, self.enter_range_end)
                        elif self.dialog_label == "release":
                            prj.alloc.release(self.enter_range_start, self.enter_range_end)
                        imgui.close_current_popup()
                imgui.same_line()
                if imgui.button("Cancel", width = UNIT * 4):
                    imgui.close_current_popup()
                errorbox.draw()
                imgui.end_popup()
            else:
                self.dialog_label = ""
                self.enter_range_start = None
                self.enter_range_end = None
                        
        imgui.end()
rom_map_window = RomMapWindow()
    
def open_file_dialog(win_title, orig_file, filespec):
    # # Win32
    try:
        filespec_win32 = ""
        for type, ext in filespec:
            filespec_win32 += f"{type}\0{ext}\0"
        fn, filter, flags = win32gui.GetOpenFileNameW(
                Title = win_title,
                Filter = filespec_win32,
                #CustomFilter = "All files\0*.*\0",
                Flags = win32con.OFN_EXPLORER
                )
            # note: filter doesn't seem to work (always returns *.*)
            # so we'll have to parse extensions/filetypes manually
            # for ambiguous items
        return fn
    except win32gui.error:
        return orig_file
    
def display_side_panel():
    head = UNIT * 6 + MAIN_MENU_HEIGHT
    foot = UNIT * 10
    right = (202 / 1280) * WINW
    imgui.set_next_window_position(WINW - right, head)
    imgui.set_next_window_size(right, WINH / 3)
    imgui.begin("IMPRESARIA FINAL FANTASY", True, MAIN_WINDOW_FLAGS)
    imgui.image(*logo_texture.get(scale=WINSCALE))
    imgui.push_text_wrap_pos(0.0)
    imgui.text(temporary_status_text)
    imgui.pop_text_wrap_pos()
    imgui.end()
    
    imgui.set_next_window_position(WINW - right, head + (WINH / 3))
    imgui.set_next_window_size(right, (WINH * 2 / 3) - head)
    imgui.begin("SidePanel", True, MAIN_WINDOW_FLAGS)
    if prj and prj.init_status is True:
        imgui.push_text_wrap_pos(0.0)
        imgui.text(f"{prj.alloc.repr_total_usage()}")
        imgui.pop_text_wrap_pos()
    imgui.end()
    
    
def display_log_window():
    global log_text
    
    for line in log.flush():
        log_text += "\n" + line
    
    right = (202 / 1280) * WINW
    imgui.set_next_window_size(WINW - right, UNIT * 10)
    imgui.set_next_window_position(0, WINH - (UNIT * 10))
    imgui.begin("Log", True, MAIN_WINDOW_FLAGS)
    imgui.begin_child("Log")
    imgui.push_text_wrap_pos(0.0)
    imgui.text_unformatted(log_text)
    imgui.pop_text_wrap_pos()
    imgui.set_scroll_here()
    imgui.end_child()
    imgui.end()
    
def handle_stdout():
    for line in std.flush():
        print(line)
        
class ErrorBox():
    def __init__(self):
        self.log = []
        self.drawn_this_frame = False
    
    # Due to imgui's handling of modals, whenever we're in a modal dialog, we have to
    # draw ErrorBox from within it instead of in the main loop proper. We'll use a
    # check to make sure we're only drawing once per frame, and use end_frame
    # on the last draw() call of the loop to reset it.
    def draw(self, end_frame=False):
        if not self.drawn_this_frame:            
            e = err.flush()
            if e:
                imgui.open_popup("Error")
                self.log.extend(e)
            
            if imgui.begin_popup_modal("Error", True, imgui.WINDOW_NO_COLLAPSE
                    | imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
                for line in self.log:
                    imgui.text(line)
                if imgui.button("OK"):
                    imgui.close_current_popup()
                imgui.end_popup()
            else:
                self.log = []
                
            self.drawn_this_frame = True                
        if end_frame:
            self.drawn_this_frame = False
            
class QuestionBox():
    def __init__(self, prompt, uid=""):
        self.prompt = prompt
        self.uid = "##" + str(uid)
        self.has_opened = False
        
    def open(self):
        self.has_opened = True
        imgui.open_popup(f"Question{self.uid}")
        
    def draw(self):
        ret = None
        if not self.has_opened:
            self.open()
        if imgui.begin_popup_modal(f"Question{self.uid}", True, imgui.WINDOW_NO_COLLAPSE
                    | imgui.WINDOW_ALWAYS_AUTO_RESIZE)[0]:
            imgui.text(self.prompt)
            if imgui.button("Yes", width = UNIT * 4):
                ret = True
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("No", width = UNIT * 4):
                ret = False
                imgui.close_current_popup()
            imgui.end_popup()
        else:
            ret = False
        return ret

class Texture():
    def __init__(self, file, buffer_format=None):
        ### file is bytes or filename
        if buffer_format:
            image = pygame.image.frombuffer(file, len(file), buffer_format)
        else:
            image = pygame.image.load(file)
        
        texture_surface = pygame.transform.flip(image, False, True)
        texture_data = pygame.image.tostring(texture_surface, "RGB", 1)
        
        width = texture_surface.get_width()
        height = texture_surface.get_height()
        
        texture = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, width, height, 0, gl.GL_RGB, gl.GL_UNSIGNED_BYTE, texture_data)
        
        self.texture = texture
        self.width = width
        self.height = height
        
    def get(self, scale=1.0):
        return self.texture, self.width*scale, self.height*scale

def cleanup_and_quit():
    global midi_device
    midi_device = None
    sys.exit(0)
    
if __name__ == "__main__":
    main()