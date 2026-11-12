#!/usr/bin/env python3
"""DVD Ripper — rip a disc into files your PC can actually play.

HandBrake does the encoding; this window is the driver: it scans the disc,
lists every title (one per episode on a TV disc), and can cut a single title
into per-episode files by chapter range or by timestamp.
"""

import json
import math
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import (  # noqa: E402
    Gdk, Gio, GLib, GObject, Graphene, Gtk, Pango)

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import names as episode_names  # noqa: E402
import ripper  # noqa: E402

APP_ID = "org.jimmy.DvdRipper"
APP_VERSION = "1.0.0"
THEMES = [
    {"key": "matrix", "short": "Matrix"},
    {"key": "basic-light", "short": "Basic (light)"},
    {"key": "basic-dark", "short": "Basic (dark)"},
]
THEME_FILES = {
    "matrix": "gtk.css",
    "basic-light": "basic-light.css",
    "basic-dark": "basic-dark.css",
}
_theme_provider = None
STATE_DIR = os.path.join(os.path.expanduser("~"), ".local/share/c0d3d/dvd-ripper")
STATE_FILE = os.path.join(STATE_DIR, "state.json")


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------
def use_matrix_icons():
    """Point this process at the crimson icon theme, without touching the desktop."""
    try:
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-icon-theme-name", "C0D3D-Matrix")
    except Exception:
        pass


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(data):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        temp = STATE_FILE + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(temp, STATE_FILE)
    except OSError as error:
        ripper.log("state save failed: %s" % error)


# --------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------
class CircleStep(Gtk.Widget):
    """A hand-drawn circular − / + button.

    A real Gtk.Button kept getting stretched into an oval by CSS padding, the
    font size or the desktop's fractional scale (C0D3D, 2026-11-11). This widget
    paints its own circle instead: the radius is half of the SMALLER side, so it
    stays round even if the box it is handed is not square.
    """

    def __init__(self, plus, on_click, size=24):
        super().__init__()
        self._plus = plus
        self._on_click = on_click
        self._square = size
        self._hover = False
        self._pressed = False
        self.set_valign(Gtk.Align.CENTER)
        self.add_css_class("circle-step")
        try:
            self.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        except Exception:
            pass
        click = Gtk.GestureClick()
        click.connect("pressed", self._pressed_in)
        click.connect("released", self._released)
        self.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._set_hover(True))
        motion.connect("leave", lambda *_: self._set_hover(False))
        self.add_controller(motion)

    # -- geometry ---------------------------------------------------------
    def do_measure(self, orientation, for_size):
        return (self._square, self._square, -1, -1)

    def do_snapshot(self, snapshot):
        width, height = self.get_width(), self.get_height()
        if width < 3 or height < 3:
            return
        rect = Graphene.Rect().alloc()
        rect.init(0, 0, width, height)
        cr = snapshot.append_cairo(rect)

        # the ring stays the same size it always was; the widget is bigger so
        # the glow has room to spread without being clipped
        radius = min(width, height) / 2.0 - 6.0
        cx, cy = width / 2.0, height / 2.0
        colour = self.get_color()
        red, green, blue = colour.red, colour.green, colour.blue
        alpha = 1.0 if self._hover else 0.92
        if self._pressed:
            alpha = 0.6

        cr.set_line_width(max(1.4, min(width, height) * 0.07))
        # soft outer glow, so the disc reads like the CSS-framed buttons
        # (C0D3D, 2026-11-12: "all the buttons to a deep orange with glow")
        # soft falloff: a stack of faint arcs fading outwards, so it reads as
        # light rather than a second ring (C0D3D, 2026-11-12)
        boost = 1.8 if self._hover else 1.0
        layers = 22
        span = 6.5
        for index in range(layers):
            t = index / (layers - 1.0)          # 0 at the ring, 1 outside
            reach = radius + 0.6 + t * span
            fade = (1.0 - t) ** 1.8 * 0.85 * boost
            cr.set_line_width(span / layers + 1.6)
            cr.set_source_rgba(red, green, blue, min(1.0, fade))
            cr.arc(cx, cy, reach, 0, 2 * math.pi)
            cr.stroke()
        # a tight hot edge right against the ring
        cr.set_line_width(2.4)
        cr.set_source_rgba(red, green, blue, min(1.0, 0.85 * boost))
        cr.arc(cx, cy, radius + 0.8, 0, 2 * math.pi)
        cr.stroke()

        # solid disc (C0D3D, 2026-11-12: "make the whole button colored")
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.set_source_rgba(red, green, blue, alpha)
        cr.fill()

        # rim around the disc (C0D3D, 2026-11-12); on the plain themes it goes
        # the opposite way from the disc so it stays visible
        luma_rim = 0.299 * red + 0.587 * green + 0.114 * blue
        rim = (0.0, 0.0, 0.0) if luma_rim > 0.55 else (1.0, 1.0, 1.0)
        cr.set_line_width(2.0)
        cr.arc(cx, cy, radius - 1.0, 0, 2 * math.pi)
        cr.set_source_rgba(rim[0], rim[1], rim[2], 1.0)
        cr.stroke()

        # the − / + glyph contrasts with the disc it is painted on: black on a
        # bright disc, white on a dark one, so the plain themes still read
        luma = 0.299 * red + 0.587 * green + 0.114 * blue
        ink = (0.0, 0.0, 0.0) if luma > 0.55 else (1.0, 1.0, 1.0)
        arm = radius * 0.52
        thickness = max(1.5, min(width, height) * 0.09)
        cr.set_line_width(thickness)
        cr.set_line_cap(1)  # cairo.LINE_CAP_ROUND
        cr.set_source_rgba(ink[0], ink[1], ink[2], 1.0)
        cr.move_to(cx - arm, cy)
        cr.line_to(cx + arm, cy)
        if self._plus:
            cr.move_to(cx, cy - arm)
            cr.line_to(cx, cy + arm)
        cr.stroke()

    # -- interaction ------------------------------------------------------
    def _set_hover(self, state):
        self._hover = state
        self.queue_draw()

    def _pressed_in(self, _gesture, _n_press, _x, _y):
        self._pressed = True
        self.queue_draw()

    def _released(self, _gesture, _n_press, x, y):
        self._pressed = False
        self.queue_draw()
        if 0 <= x <= self.get_width() and 0 <= y <= self.get_height():
            self._on_click()


class NumberBox(Gtk.Entry):
    """A small integer field with no built-in steppers.

    Gtk.SpinButton always draws its own up/down pair inside the box, and they
    cannot be removed — hiding them with CSS left an invisible clickable strip
    in the middle of the field (C0D3D, 2026-11-11: "the buttons shouldnt
    interfere with the input box"). This keeps the same get_value()/set_value()
    surface the app uses, driven by the round buttons beside it.
    """

    __gsignals__ = {"value-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, low, high, value, step=1):
        super().__init__()
        self.low = low
        self.high = high
        self.step = step
        self.value = int(value)
        self.updating = False
        self.set_width_chars(4)
        self.set_max_width_chars(4)
        self.set_alignment(0.5)
        self.set_input_purpose(Gtk.InputPurpose.DIGITS)
        # C0D3D (2026-11-11): the two number fields carry a light blue frame so
        # they read as the editable values on the row.
        self.add_css_class("number-box")
        self.connect("changed", self.on_text_changed)
        self.connect("activate", lambda *_: self.refresh())
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self.refresh())
        self.add_controller(focus)
        self.refresh()

    def refresh(self):
        text = str(self.value)
        if self.get_text() == text:
            return
        self.updating = True
        self.set_text(text)
        self.updating = False

    def on_text_changed(self, *_args):
        if self.updating:
            return
        text = self.get_text().strip()
        if not text.isdigit():
            return
        self.value = max(self.low, min(self.high, int(text)))
        self.emit("value-changed")

    def get_value(self):
        return float(self.value)

    def set_value(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return
        value = max(self.low, min(self.high, value))
        if value == self.value and self.get_text() == str(value):
            return
        self.value = value
        self.refresh()
        self.emit("value-changed")

    def step_by(self, delta):
        self.set_value(self.value + delta)


class Job:
    def __init__(self, source, title, label, path, preset_key, audio_key,
                 sub_key, start=None, stop=None, chapters=None, method="encode",
                 audio_lang="any", markers=True, resolution="native", size=None,
                 anime=False, denoise="off", deblock="off", deband="off",
                 transcript="off"):
        self.source = source
        self.title_number = title.number
        self.title_duration = title.duration
        self.label = label
        self.path = path
        self.preset_key = preset_key
        self.audio_key = audio_key
        self.sub_key = sub_key
        self.audio_lang = audio_lang
        self.markers = markers
        self.resolution = resolution
        self.output_size = size      # (width, height) for an upscale, or None
        self.anime = anime
        self.denoise = denoise
        self.deblock = deblock
        self.deband = deband
        self.transcript = transcript   # off / fast / better / best
        self.start = start
        self.stop = stop
        self.chapters = chapters
        self.method = method     # "encode" (HandBrake) or "copy" (ffmpeg stream copy)
        self.status = "queued"      # queued running done failed cancelled
        self.fraction = 0.0
        self.detail = ""
        self.size = 0

    def span(self):
        if self.start is None:
            return self.title_duration
        return max(0.5, (self.stop or self.title_duration) - self.start)

    def command(self):
        if self.method == "copy":
            return ripper.build_copy_command(self.source, self.path,
                                             self.start or 0.0, self.stop)
        return ripper.build_encode_command(
            self.source, self.title_number, self.path, self.preset_key,
            self.audio_key, self.sub_key, self.start, self.stop, self.chapters,
            audio_lang=self.audio_lang, markers=self.markers,
            size=self.output_size, anime=self.anime, denoise=self.denoise,
            deblock=self.deblock)

    def mode_text(self):
        if self.method == "copy":
            end = ripper.fmt_clock(self.stop) if self.stop else "end"
            return "copy %s → %s" % (ripper.fmt_clock(self.start or 0), end)
        if self.chapters:
            return "chapters %s" % self.chapters
        if self.start is not None:
            end = ripper.fmt_clock(self.stop) if self.stop else "end"
            return "%s → %s" % (ripper.fmt_clock(self.start), end)
        return "whole title"


# --------------------------------------------------------------------------
# small widgets
# --------------------------------------------------------------------------
def card(spacing=8):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.add_css_class("card")
    return box


# Every button's icon gets its own colour, different from its (red) text
# (C0D3D, 2026-11-12: "all the icons on the buttons, a different color then the
# text, random colors for each button"). The sequence is shuffled per launch so
# neighbours never match, while one window keeps a stable set.
ICON_TINTS = [
    "#00ffff", "#ff00ff", "#ffff00", "#7cff00", "#ff8c00", "#b57cff",
    "#ff69b4", "#00bfff", "#f5f5f5", "#7dffb0", "#ffa07a", "#c0ff00",
]
_icon_tint_index = [0]
_icon_tints_shuffled = []


def next_icon_tint():
    if not _icon_tints_shuffled:
        _icon_tints_shuffled.extend(sorted(ICON_TINTS))
        random.shuffle(_icon_tints_shuffled)
    tint = _icon_tints_shuffled[_icon_tint_index[0] % len(_icon_tints_shuffled)]
    _icon_tint_index[0] += 1
    return tint


def tint_icon(image, colour):
    """Recolour one symbolic icon without touching anything else."""
    global _icon_tint_serial
    _icon_tint_serial += 1
    name = "tint-%d" % _icon_tint_serial
    image.add_css_class(name)
    provider = Gtk.CssProvider()
    image._tint_class = name
    image._tint_provider = provider
    image._tint_colour = colour
    _tinted_images.append(image)
    _write_tint(image)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)


# Every icon we have tinted, so a theme change can recolour the lot.
_tinted_images = []
_current_theme = "matrix"


def _write_tint(image):
    """Write the icon's colour for the current theme.

    The Matrix skin gives each button its own colour (C0D3D, 2026-11-12); the
    plain themes carry no colour at all, so the icons go plain black or white
    with the rest of the text.
    """
    if _current_theme == "matrix":
        colour = image._tint_colour
    else:
        colour = "#000000" if _current_theme == "light" else "#ffffff"
    image._tint_provider.load_from_data(
        ("image.%s { color: %s; }" % (image._tint_class, colour)).encode("utf-8"))


def refresh_icon_tints():
    for image in list(_tinted_images):
        try:
            _write_tint(image)
        except Exception:
            pass


_icon_tint_serial = 0


def icon_button(label, icon, toggle=False):
    """A button with a symbolic icon beside its text.

    GTK4's icon-name property *replaces* the label instead of adding to it, so
    the content is built by hand (C0D3D, 2026-11-12: "give all these buttons an
    appropriate icon").
    """
    button = Gtk.ToggleButton() if toggle else Gtk.Button()
    row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    image = Gtk.Image.new_from_icon_name(icon)
    tint_icon(image, next_icon_tint())
    row.append(image)
    text = Gtk.Label(label=label)
    row.append(text)
    button.set_child(row)
    button.icon_image = image
    button.text_label = text
    return button


def caption(text, centered=False):
    label = Gtk.Label(xalign=0.5 if centered else 0.0)
    label.set_markup("<span>%s</span>" % GLib.markup_escape_text(text))
    label.add_css_class("eyebrow")
    return label


def caption_centred_temp(text):
    return caption(text, centered=True)


def plain(text, css="value", ellipsize=False):
    label = Gtk.Label(xalign=0.0, label=text)
    label.add_css_class(css)
    if ellipsize:
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_hexpand(True)
    return label


class EpisodeListPopover(Gtk.Popover):
    """Every episode of the looked-up show, so the right start can be picked."""

    def __init__(self, show_name, rows, style, season, on_pick):
        super().__init__()
        self.set_has_arrow(False)
        self.set_size_request(560, 520)
        self.rows = rows
        self.show_name = show_name
        self.style = style
        self.season = season
        self.on_pick = on_pick

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        self.set_child(box)

        self.filter = Gtk.Entry()
        self.filter.set_placeholder_text("Filter by number or name…")
        self.filter.connect("changed", lambda *_: self.populate())
        box.append(self.filter)

        self.hint = Gtk.Label(xalign=0.0, label="")
        self.hint.add_css_class("dim")
        box.append(self.hint)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("episode-list")
        self.listbox.connect("row-activated", self.on_row)
        scroller.set_child(self.listbox)
        box.append(scroller)

        self.populate()

    def populate(self):
        while True:
            child = self.listbox.get_first_child()
            if child is None:
                break
            self.listbox.remove(child)
        needle = self.filter.get_text().strip().lower()
        shown = 0
        for row in episode_names.ordered(self.rows):
            label = episode_names.label(self.show_name, row, self.style,
                                        self.season)
            haystack = ("%s %s" % (row.get("index"), label)).lower()
            if needle and needle not in haystack:
                continue
            item = Gtk.ListBoxRow()
            item.episode_number = int(row.get("index") or 0)
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            number = Gtk.Label(label="%03d" % item.episode_number, width_chars=4,
                               xalign=0.0)
            number.add_css_class("episode-number")
            line.append(number)
            name = Gtk.Label(label=label, xalign=0.0)
            name.add_css_class("episode-name")
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_hexpand(True)
            line.append(name)
            item.set_child(line)
            self.listbox.append(item)
            shown += 1
        self.hint.set_text("%d episode%s — click one to start there."
                           % (shown, "" if shown == 1 else "s"))

    def on_row(self, _listbox, item):
        if self.on_pick is not None:
            self.on_pick(item.episode_number)
        self.popdown()


class RipperWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.state = load_state()
        # C0D3D (2026-11-11): a value that is missing from the file must not
        # fall back to "off" — the transcript is the default on this box.
        self.state.setdefault("transcript", "best")
        self.titles = []
        self.episode_rows = []
        self.episode_show = ""
        self.episode_runtime = 0
        self.detected_style = episode_names.STYLE_ABSOLUTE
        self.episode_shows = []
        self.main_feature = 0
        self.source = ""        # every launch starts clean: no disc, no titles
        self.jobs = []
        self.rows = []
        self.selected_job = None
        self.current_proc = None
        self.current_job = None
        self.cancel_requested = False
        self.running = False
        self.scan_generation = 0
        self.dead = False

        self.set_default_size(1240, 860)
        self.set_title("Matrix DVD Ripper")

        header = Gtk.HeaderBar()
        self.set_titlebar(header)
        title_label = Gtk.Label(label="MATRIX DVD RIPPER")
        title_label.add_css_class("app-title")
        header.set_title_widget(title_label)


        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.add_css_class("ripper-rain")
        root.set_margin_top(8)
        root.set_margin_bottom(8)
        root.set_margin_start(8)
        root.set_margin_end(8)

        self.theme_key = "matrix"
        self.theme_button = Gtk.Button(label="Theme selector")
        self.theme_button.add_css_class("compact-button")
        self.theme_button.add_css_class("crimson-button")
        self.theme_button.set_tooltip_text(
            "Matrix is this desktop's look; the Basic themes are plain, neutral "
            "and would pass on Windows.")

        theme_popover = Gtk.Popover()
        self.theme_list = Gtk.ListBox()
        self.theme_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.theme_list.add_css_class("theme-list")
        self.theme_list.connect("row-activated", self.on_theme_row)
        theme_popover.set_child(self.theme_list)
        self.theme_popover = theme_popover
        theme_popover.set_parent(self.theme_button)
        self.theme_button.connect("clicked", lambda *_: theme_popover.popup())
        self.fill_theme_list()

        # SOURCE / SAVE TO card. It auto-hides (C0D3D, 2026-11-11): hovering the
        # top band opens it, and it slides away 2 s after the pointer leaves.
        self.source_card = self.build_source_card()
        # it floats over the panes, so it needs its own opaque face or the
        # content underneath shows through it
        self.source_card.add_css_class("source-floating")
        self.source_revealer = Gtk.Revealer()
        self.source_revealer.set_transition_type(
            Gtk.RevealerTransitionType.SLIDE_UP)
        self.source_revealer.set_transition_duration(650)
        self.source_revealer.set_child(self.source_card)
        self.source_revealer.set_reveal_child(True)

        # the rip queue lives in its own vertical paned so its height can be dragged
        self.queue_paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.queue_paned.set_wide_handle(True)
        self.queue_paned.set_shrink_start_child(True)
        self.queue_paned.set_shrink_end_child(True)
        # the queue grows with the window, so a bigger window shows more rips
        self.queue_paned.set_resize_start_child(True)
        self.queue_paned.set_resize_end_child(True)
        self.queue_paned.set_start_child(self.build_middle())
        self.queue_card = self.build_queue_card()
        self.queue_paned.set_end_child(self.queue_card)
        self.queue_paned.set_vexpand(True)

        # The card floats OVER the panes instead of sitting in the box above them
        # (C0D3D, 2026-11-11: "i dont want anything else to move when i hover over
        # top"). An overlay child is given no layout space of its own, so showing
        # and hiding it never re-flows the columns underneath — it just covers the
        # top strip while it is open and slides out of view when it hides.
        self.source_overlay = Gtk.Overlay()
        self.source_overlay.set_child(self.queue_paned)
        self.source_overlay.set_vexpand(True)
        self.source_revealer.set_valign(Gtk.Align.START)
        self.source_revealer.set_halign(Gtk.Align.FILL)
        self.source_revealer.set_vexpand(False)
        self.source_overlay.add_overlay(self.source_revealer)
        root.append(self.source_overlay)
        self.build_keys()

        self.page = Gtk.ScrolledWindow()
        self.page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
        self.page.set_overlay_scrolling(False)
        self.page.set_child(root)
        self.page.set_vexpand(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_margin_top(6)
        outer.set_margin_bottom(6)
        outer.set_margin_start(8)
        outer.set_margin_end(8)
        outer.append(self.page)
        outer.append(self.build_progress_strip())
        self.set_child(outer)
        self.freeze_wheel(outer)
        self.sky_frame_dropdowns(outer)
        self.install_wheel_fallback()
        self.install_source_autohide()

        saved = self.state
        self.output_dir = saved.get("output_dir") or ripper.DEFAULT_OUTPUT_DIR
        self.output_entry.set_text(self.output_dir)

        GLib.idle_add(self.bootstrap)

    # ---------------------------------------------------------------- source
    def current_theme(self):
        return self.theme_key

    def fill_theme_list(self):
        while True:
            child = self.theme_list.get_first_child()
            if child is None:
                break
            self.theme_list.remove(child)
        for theme in THEMES:
            row = Gtk.ListBoxRow()
            row.theme_key = theme["key"]
            label = Gtk.Label(xalign=0.0)
            label.set_markup(("✓  " if theme["key"] == self.theme_key else "     ")
                             + GLib.markup_escape_text(theme["short"]))
            label.add_css_class("theme-option")
            row.set_child(label)
            self.theme_list.append(row)

    def on_theme_row(self, _listbox, row):
        key = getattr(row, "theme_key", None)
        if key:
            self.set_theme(key)
        self.theme_popover.popdown()

    def set_theme(self, key, remember=True):
        self.theme_key = key
        apply_theme(key)
        self.fill_theme_list()
        if remember:
            self.state["theme"] = key
            save_state(self.state)
        ripper.log("theme: %s" % key)

    def hug_children(self, flow):
        """Flow boxes stretch their children by default; keep buttons to their own width."""
        index = 0
        while True:
            child = flow.get_child_at_index(index)
            if child is None:
                break
            child.set_halign(Gtk.Align.START)
            index += 1

    def round_stepper(self, spin, step=1):
        """Wrap a spin button in its own round − / + buttons.

        The stock steppers are stretched by the spin button's height, which made
        them ovals (C0D3D, 2026-11-10), and CSS-sized real buttons did the same
        again at a fractional desktop scale (2026-11-11). These are hand-drawn
        circles, so their shape cannot be stretched by anything.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        # The pair sits to the right of the box (C0D3D, 2026-11-10: "put em both
        # on the right side"), the way a stock spin button reads.
        box.append(spin)
        for plus, delta in ((False, -step), (True, step)):
            button = CircleStep(
                plus,
                lambda d=delta, target=spin: target.set_value(
                    target.get_value() + d),
                size=34)   # room for the glow inside the widget
            box.append(button)
        return box

    def section_rule(self):
        rule = Gtk.Box()
        rule.set_size_request(-1, 2)
        rule.set_hexpand(True)
        rule.add_css_class("section-rule")
        return rule

    def show_about(self):
        about = Gtk.AboutDialog(transient_for=self, modal=True)
        about.set_program_name("Matrix DVD Ripper")
        about.set_version(APP_VERSION)
        about.set_comments(
            "Rips a DVD into video files your PC can play — every title, every "
            "chapter range or any timestamp you like, with the episodes named "
            "from the show's own episode list.")
        about.set_copyright("© 2026 William James Sova (C0D3D) — PeaceMachineStudios")
        about.set_authors([
            "William James Sova, AKA C0D3D",
            "PeaceMachineStudios",
        ])
        about.set_website("https://peacemachinestudios.com")
        about.set_website_label("peacemachinestudios.com")
        about.add_credit_section("Built with", [
            "HandBrake — the encoder underneath",
            "FFmpeg — stream copy, detection and deband",
            "TVmaze — episode names",
            "GTK4 and PyGObject",
        ])
        about.set_logo_icon_name("media-optical")
        about.present()

    def build_source_card(self):
        box = card(1)   # tight: SAVE TO sits right under SOURCE (C0D3D, 2026-11-11)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.append(caption("SOURCE"))

        browse = Gtk.Button(label="Browse…")
        browse.add_css_class("compact-button")
        browse.add_css_class("crimson-button")
        browse.set_tooltip_text("Pick an ISO image, a VIDEO_TS folder, or a raw device")
        browse.connect("clicked", lambda *_: self.browse_source())
        row.append(browse)

        self.source_entry = Gtk.Entry()
        self.source_entry.set_placeholder_text(
            "DVD drive, .iso file, or a VIDEO_TS folder")
        self.source_entry.set_hexpand(True)
        self.source_entry.set_width_chars(10)
        self.source_entry.add_css_class("source-entry")
        self.source_entry.connect("activate", lambda *_: self.start_scan())
        row.append(self.source_entry)

        self.scan_now = Gtk.Button(label="Scan disc")
        self.scan_now.add_css_class("compact-button")
        self.scan_now.add_css_class("crimson-button")
        self.scan_now.connect("clicked", lambda *_: self.start_scan())
        row.append(self.scan_now)

        self.folder_button = Gtk.Button(label="Rips folder")
        self.folder_button.add_css_class("compact-button")
        self.folder_button.add_css_class("crimson-button")
        self.folder_button.set_tooltip_text("Open the folder rips are written to")
        self.folder_button.connect("clicked", lambda *_: self.open_folder())
        row.append(self.folder_button)
        if hasattr(self, "theme_button"):
            row.append(self.theme_button)

        # C0D3D (2026-11-10): About sits beside the theme selector in the source
        # row, not down at the bottom of the split block.
        self.about_button = Gtk.Button(label="About")
        self.about_button.add_css_class("compact-button")
        self.about_button.add_css_class("crimson-button")
        self.about_button.set_tooltip_text("About Matrix DVD Ripper")
        self.about_button.connect("clicked", lambda *_: self.show_about())
        row.append(self.about_button)
        box.append(row)

        self.source_status = plain("No disc scanned yet.", "dim", ellipsize=True)
        self.source_status.set_width_chars(10)
        # C0D3D (2026-11-11): the status line moved to the right-hand end of the
        # SAVE TO row (under the button row) so the card is one line shorter.
        self.source_status.set_xalign(1.0)
        self.source_status.set_hexpand(True)
        self.source_status.set_halign(Gtk.Align.END)
        # The episode status reports here, under the source row (C0D3D, 2026-11-10)
        # instead of cluttering the settings column.
        self.top_status_box = box
        return box

    def use_drive(self):
        sources = ripper.list_sources()
        if sources:
            self.source_entry.set_text(sources[0])
            self.start_scan()

    def browse_source(self):
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose a disc, ISO image or VIDEO_TS folder")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        iso = Gtk.FileFilter()
        iso.set_name("Disc images (*.iso, *.img)")
        for pattern in ("*.iso", "*.ISO", "*.img"):
            iso.add_pattern(pattern)
        filters.append(iso)
        video = Gtk.FileFilter()
        video.set_name("Video files (*.mkv, *.mp4, *.avi, *.ts …)")
        for pattern in ("*.mkv", "*.MKV", "*.mp4", "*.m4v", "*.avi", "*.ts",
                        "*.m2ts", "*.webm", "*.mov", "*.mpg", "*.mpeg", "*.wmv"):
            video.add_pattern(pattern)
        filters.append(video)
        everything = Gtk.FileFilter()
        everything.set_name("All files")
        everything.add_pattern("*")
        filters.append(everything)
        dialog.set_filters(filters)

        def done(chooser, result):
            try:
                picked = chooser.open_finish(result)
            except GLib.Error:
                return
            if picked is not None and picked.get_path():
                self.source_entry.set_text(picked.get_path())
                self.start_scan()

        dialog.open(self, None, done)

    # ---------------------------------------------------------------- middle
    def build_middle(self):
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(520)
        paned.set_vexpand(True)
        paned.set_wide_handle(True)
        paned.set_shrink_start_child(True)
        paned.set_shrink_end_child(True)
        # a re-tile (switching tabs and back) must not squeeze the settings column:
        # the titles column gives and takes instead
        paned.set_resize_start_child(True)
        paned.set_resize_end_child(False)
        # the titles column gives and takes on a resize, the settings column keeps
        # its width — otherwise Hyprland re-tiling the window (switching tabs and
        # back) pushes the divider over and the sidebar "re-collapses"
        self.paned = paned
        self.paned_save_guard = False

        # ---- titles
        titles_box = card(6)
        titles_box.add_css_class("titles-card")
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        head.append(caption("TITLES ON THE DISC"))
        clear_titles = Gtk.Button(label="Clear")
        clear_titles.add_css_class("tiny-button")
        clear_titles.set_tooltip_text("Empty the title list")
        clear_titles.connect("clicked", lambda *_: self.clear_titles())
        head.append(clear_titles)
        self.titles_count = plain("", "dim")
        self.titles_count.set_hexpand(True)
        self.titles_count.set_halign(Gtk.Align.END)
        head.append(self.titles_count)
        titles_box.append(head)

        self.titles_hint = plain(
            "Scan a disc to list its titles. On a TV disc each episode is usually "
            "its own title — tick the ones you want.", "dim")
        self.titles_hint.set_wrap(True)
        titles_box.append(self.titles_hint)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_min_content_height(120)
        self.titles_scroller = scroller
        self.titles_list = Gtk.ListBox()
        self.titles_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.titles_list.add_css_class("title-list")
        scroller.set_child(self.titles_list)
        titles_box.append(scroller)
        paned.set_start_child(titles_box)

        settings = card(4)

        _blocks = {}
        self.settings_card = settings

        self.preset_dropdown = Gtk.DropDown.new_from_strings(
            [preset.get("short") or preset["label"] for preset in ripper.PRESETS])
        self.preset_dropdown.set_hexpand(False)
        self.preset_dropdown.set_halign(Gtk.Align.CENTER)
        self.preset_dropdown.set_tooltip_text(
            " | ".join("%s: %s" % (preset.get("short"), preset["note"])
                       for preset in ripper.PRESETS))
        self.preset_dropdown.connect("notify::selected", lambda *_: self.preset_changed())
        self.resolution_dropdown = Gtk.DropDown.new_from_strings(
            [mode["short"] for mode in ripper.RESOLUTIONS])
        self.resolution_dropdown.set_hexpand(False)
        self.resolution_dropdown.set_halign(Gtk.Align.CENTER)
        self.resolution_dropdown.set_tooltip_text(
            "DVDs hold 720x480 — upscaling cannot add detail, it just scales once "
            "with a decent filter instead of leaving it to your player.")
        self.resolution_dropdown.connect("notify::selected", lambda *_: self.split_text_changed())
        clean_row = Gtk.FlowBox()
        clean_row.set_selection_mode(Gtk.SelectionMode.NONE)
        clean_row.set_max_children_per_line(4)
        clean_row.set_min_children_per_line(1)
        clean_row.set_column_spacing(6)
        clean_row.set_row_spacing(4)
        clean_row.set_homogeneous(False)
        self.anime_check = Gtk.CheckButton(label="Anime tuning")
        self.anime_check.set_tooltip_text(
            "x264/x265 tune for line art: cleaner edges, less ringing. On the GPU "
            "encoder it uses NVENC's high-quality tune.")
        self.anime_check.connect("toggled", lambda *_: self.split_text_changed())
        clean_row.append(self.anime_check)

        self.denoise_dropdown = Gtk.DropDown.new_from_strings(
            [mode["short"] for mode in ripper.DENOISE_MODES])
        self.denoise_dropdown.set_tooltip_text(
            "Temporal denoise (hqdn3d). DVD anime has mosquito noise around the "
            "outlines — light usually fixes the worst of it without smearing.")
        clean_row.append(self.denoise_dropdown)

        self.deblock_dropdown = Gtk.DropDown.new_from_strings(
            [mode["short"] for mode in ripper.DEBLOCK_MODES])
        self.deblock_dropdown.set_tooltip_text(
            "Stronger in-loop deblocking (x264/x265 only): smooths the blocky "
            "patches DVD compression leaves behind. It softens detail too.")
        clean_row.append(self.deblock_dropdown)

        self.deband_dropdown = Gtk.DropDown.new_from_strings(
            [mode["short"] for mode in ripper.DEBAND_MODES])
        self.deband_dropdown.set_tooltip_text(
            "HandBrake cannot deband, so this runs ffmpeg's deband as a SECOND "
            "pass over the finished file. It re-encodes the video: roughly double "
            "the rip time and one more generation of lossy encoding.")
        clean_row.append(self.deband_dropdown)
        self.audio_dropdown = Gtk.DropDown.new_from_strings(
            [mode.get("short") or mode["label"] for mode in ripper.AUDIO_MODES])
        self.audio_dropdown.set_tooltip_text(
            "\n".join(mode["label"] for mode in ripper.AUDIO_MODES))
        self.audio_dropdown.set_hexpand(False)
        self.audio_dropdown.set_halign(Gtk.Align.CENTER)
        self.lang_dropdown = Gtk.DropDown.new_from_strings(
            [lang.get("short") or lang["label"] for lang in ripper.AUDIO_LANGUAGES])
        self.lang_dropdown.set_tooltip_text(
            "Which audio tracks to take from the disc when it carries more than one "
            "— a Bleach disc has the Japanese track and the English dub.")
        self.lang_dropdown.set_hexpand(False)
        self.lang_dropdown.set_halign(Gtk.Align.CENTER)
        self.sub_dropdown = Gtk.DropDown.new_from_strings(
            [mode.get("short") or mode["label"] for mode in ripper.SUB_MODES])
        self.sub_dropdown.set_hexpand(False)
        self.sub_dropdown.set_halign(Gtk.Align.CENTER)
        self.name_entry = Gtk.Entry()
        self.name_entry.set_text("Disc")
        self.name_entry.set_tooltip_text(
            "This will automatically name the show once u load the disk, "
            "or manually name it whatever you want.")
        self.name_entry.set_width_chars(26)
        self.name_entry.set_hexpand(False)
        self.name_entry.set_halign(Gtk.Align.START)
        self.name_entry.add_css_class("source-entry")
        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.show_entry = Gtk.Entry()
        self.show_entry.set_placeholder_text("Type ur show and hit find")
        self.show_entry.set_tooltip_text(
            "Type the name of the show and hit Find, choose your show for it "
            "to auto name episodes.")
        self.show_entry.add_css_class("source-entry")
        self.show_entry.set_width_chars(26)
        self.show_entry.set_hexpand(False)
        self.show_entry.connect("activate", lambda *_: self.lookup_show())
        find_row.append(self.show_entry)
        self.find_button = icon_button("Find", "edit-find-symbolic")
        self.find_button.add_css_class("orange-button")
        self.find_button.set_tooltip_text("Look the show up and fetch its episode list")
        self.find_button.connect("clicked", lambda *_: self.lookup_show())
        find_row.set_halign(Gtk.Align.FILL)
        find_row.set_hexpand(False)
        # C0D3D (2026-11-10): the show dropdown lives in the right-hand column,
        # in the empty space beside the two name boxes — that way the left column
        # never changes width and FIRST EPISODE cannot move.
        # Always on show, starting with a placeholder, so the space between the
        # name boxes and FIRST EPISODE is filled instead of an empty gap
        # (C0D3D, 2026-11-10) and nothing moves when a show loads.
        self.show_dropdown = Gtk.DropDown(
            model=Gtk.StringList.new(["Show name…"]))
        self.show_dropdown.set_halign(Gtk.Align.START)
        self.show_dropdown.set_sensitive(False)
        self.show_dropdown.connect("notify::selected", lambda *_: self.on_show_selected())
        folder_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        folder_row.set_hexpand(True)
        self.output_entry = Gtk.Entry()
        self.output_entry.set_text(self.state.get("output_dir")
                                   or ripper.DEFAULT_OUTPUT_DIR)
        self.output_entry.set_width_chars(42)
        self.output_entry.set_hexpand(False)
        self.output_entry.add_css_class("source-entry")
        folder_row.append(self.output_entry)
        pick = Gtk.Button(label="…")
        pick.set_tooltip_text("Choose the output folder")
        pick.connect("clicked", lambda *_: self.pick_output_folder())
        folder_row.append(pick)
        folder_row.set_halign(Gtk.Align.START)
        folder_row.set_hexpand(False)

        # C0D3D (2026-11-10): SAVE TO lives at the top, under the source row.
        save_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        save_row.append(caption("SAVE TO"))
        save_row.append(folder_row)
        # the source status rides at the right-hand end of this row, under the
        # buttons (C0D3D, 2026-11-11), so the card keeps two lines
        if hasattr(self, "source_status"):
            save_row.append(self.source_status)
        if hasattr(self, "top_status_box"):
            self.top_status_box.append(save_row)
        modes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        modes.set_halign(Gtk.Align.CENTER)
        mode_group = None
        self.mode_buttons = {}
        for key, text, icon in (("whole", "Whole title", "media-optical-symbolic"),
                                ("chapters", "By chapters", "view-paged-symbolic"),
                                ("timestamps", "By timestamps", "alarm-symbolic")):
            # an icon beside the label, so the three modes read at a glance
            # (C0D3D, 2026-11-12)
            button = icon_button(text, icon, toggle=True)
            button.add_css_class("mode-button")
            button.add_css_class("compact-button")
            button.add_css_class("crimson-button")
            button.add_css_class("orange-button")
            if mode_group is not None:
                button.set_group(mode_group)
            else:
                mode_group = button
            button.connect("toggled", lambda *_: self.split_mode_changed())
            # A re-click on the mode that is already active never emits "toggled",
            # so the empty box stayed empty (C0D3D, 2026-11-10). Refresh on click too.
            button.connect("clicked", lambda _b, k=key: self.on_mode_clicked(k))
            modes.append(button)
            self.mode_buttons[key] = button
        self.mode_buttons["whole"].set_active(True)
        _block = []
        _blocks["QUALITY"] = _block
        _block.append(caption_centred_temp("QUALITY"))
        _block.append(self.preset_dropdown)
        # the preset blurb is gone from the window (C0D3D, 2026-11-12); it is
        # kept as a tooltip on the dropdown instead
        self.preset_note = plain("", "dim")
        self.preset_note.set_wrap(True)
        self.preset_note.set_xalign(0.5)
        self.preset_note.set_visible(False)


        _block = []
        _blocks["RESOLUTION"] = _block
        _block.append(caption_centred_temp("RESOLUTION"))
        _block.append(self.resolution_dropdown)


        _block = []
        _blocks["ANIME CLEAN-UP"] = _block
        _block.append(caption_centred_temp("ANIME CLEAN-UP"))
        self.hug_children(clean_row)
        clean_row.set_margin_top(0)
        clean_row.set_margin_bottom(0)
        _block.append(clean_row)


        _block = []
        _blocks["AUDIO"] = _block
        _block.append(caption_centred_temp("AUDIO"))
        _block.append(self.audio_dropdown)


        _block = []
        _blocks["LANGUAGE"] = _block
        _block.append(caption_centred_temp("LANGUAGE"))
        _block.append(self.lang_dropdown)


        _block = []
        _blocks["SUBTITLES"] = _block
        _block.append(caption_centred_temp("SUBTITLES"))
        _block.append(self.sub_dropdown)

        # C0D3D (2026-11-11): the disc's English subtitles translate the
        # Japanese script, so they do not say what the English dub says. This
        # listens to the dub in the rip itself and writes subtitles from it.
        self.transcript_dropdown = Gtk.DropDown.new_from_strings(
            [mode["short"] for mode in ripper.TRANSCRIPT_MODES])
        self.transcript_dropdown.set_tooltip_text(
            "Speech-to-text over the English audio in the rip, so the subtitles "
            "say exactly what the dub says. Runs on the GPU after the encode "
            "(a minute or so an episode) and becomes the default subtitle track; "
            "the disc's translation is kept as a second track.")
        self.transcript_dropdown.set_hexpand(False)
        self.transcript_dropdown.set_halign(Gtk.Align.CENTER)
        self.transcript_dropdown.set_size_request(210, -1)
        # its own block so audio, subtitles and transcript share one line
        # (C0D3D, 2026-11-12)
        _block = []
        _blocks["TRANSCRIPT"] = _block
        _block.append(caption_centred_temp("TRANSCRIPT"))
        _block.append(self.transcript_dropdown)


        _block = []
        _blocks["FILE NAME"] = _block
        # C0D3D (2026-11-10): the file name and show name boxes stack, with the
        # show dropdown beside them on the right.
        names_left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        names_left.set_halign(Gtk.Align.START)
        # C0D3D (2026-11-11): both boxes start on the same left edge, and each
        # caption sits centred over its own box.
        file_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        file_col.set_halign(Gtk.Align.START)
        file_col.append(caption_centred_temp("FILE NAME"))
        file_col.append(self.name_entry)
        names_left.append(file_col)
        self.names_left = names_left

        # right-hand side of the block: FIRST EPISODE and the ticks
        start_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        start_row.set_halign(Gtk.Align.START)
        start_row.append(caption_centred_temp("FIRST EPISODE"))
        self.episode_start = NumberBox(1, 5000, 1)
        self.episode_start.set_value(1)
        self.start_is_manual = False
        self.auto_setting_start = False
        self.episode_start.connect("value-changed", self.on_start_changed)
        start_row.append(self.round_stepper(self.episode_start))
        browse = icon_button("List…", "view-list-symbolic")
        browse.add_css_class("orange-button")
        browse.set_tooltip_text("See every episode and pick the starting one")
        browse.connect("clicked", lambda *_: self.open_episode_list(browse))
        self.episode_list_button = browse
        self.browse_button = browse

        names_right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        names_right.set_halign(Gtk.Align.START)
        names_right.append(start_row)

        names_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=26)
        names_row.set_halign(Gtk.Align.START)
        names_row.append(names_left)
        names_row.append(names_right)
        # Both rows live in one box that is centred as a whole, and each row
        # starts at the same left edge — so the FILE NAME box and the show box
        # line up, while FIRST EPISODE stays exactly where it was, beside them.
        self.names_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.names_box.set_halign(Gtk.Align.CENTER)
        self.names_box.append(names_row)
        _block.append(self.names_box)

        number_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.numbering = Gtk.CheckButton(label="Number files")
        self.numbering.set_active(True)
        self.numbering.set_tooltip_text("Add 01, 02 … to the file names")
        number_row.append(self.numbering)

        self.markers = Gtk.CheckButton(label="Chapter markers")
        self.markers.set_active(True)
        self.markers.set_tooltip_text(
            "Untick to strip the disc's chapter markers from the finished file")
        self.markers.set_tooltip_text(
            "Untick to strip the disc's chapter markers out of the finished file. "
            "The disc menu itself is never ripped — HandBrake writes only the "
            "title's video.")
        number_row.append(self.markers)
        number_row.set_halign(Gtk.Align.START)
        # C0D3D (2026-11-10): the ticks sit right under the FIRST EPISODE row.
        names_right.append(number_row)
        # C0D3D (2026-11-11): the show box gets its own centred EPISODE NAMES
        # caption and sits on the same left edge as the file name box, with
        # Find, the show list and List… level with it on the same line. The
        # FIRST EPISODE row above is left exactly where it was.
        find_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        find_row.set_halign(Gtk.Align.START)
        episode_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        episode_col.set_halign(Gtk.Align.START)
        episode_col.append(caption_centred_temp("EPISODE NAMES"))
        episode_col.append(self.show_entry)
        find_row.append(episode_col)
        for widget in (self.find_button, self.show_dropdown, self.browse_button):
            widget.set_valign(Gtk.Align.END)
            find_row.append(widget)
        self.names_box.append(find_row)


        # C0D3D (2026-11-10): the chapter-times dump and the episode status line
        # were clutter in this column. The hint is gone entirely and the status
        # text now reports at the top, under the source row.
        self.episode_status = plain("", "dim")
        self.episode_status.set_wrap(True)
        self.episode_status.set_xalign(0.0)
        self.episode_status.set_ellipsize(Pango.EllipsizeMode.END)
        if hasattr(self, "top_status_box"):
            self.top_status_box.append(self.episode_status)


        # The three split actions used to live here; C0D3D removed them (2026-11-10)
        # — the mode buttons fill the box by themselves now.

        # the episode count, used to work out the chapter ranges / cut times
        parts_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        parts_row.set_halign(Gtk.Align.CENTER)
        parts_row.add_css_class("parts-row")
        parts_row.append(caption_centred_temp("EPISODES"))
        self.episode_parts = NumberBox(2, 20, 4)
        self.episode_parts.set_value(4)
        self.episode_parts.set_tooltip_text(
            "How many episodes this disc holds — four is usual for Bleach.")
        parts_row.append(self.round_stepper(self.episode_parts))


        # C0D3D (2026-11-10): the episode count shares the line with the mode
        # buttons. Done with a plain Box — a FlowBox here swallowed the clicks.
        parts_group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        parts_group.append(Gtk.Box())          # small gap before the count
        child = parts_row.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            parts_row.remove(child)
            parts_group.append(child)
            child = following
        del parts_row

        self.split_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.split_row.set_halign(Gtk.Align.CENTER)
        self.split_row.append(modes)
        self.split_row.append(parts_group)

        _block = []
        _blocks["SPLIT INTO SEPARATE FILES"] = _block
        _block.append(caption_centred_temp("SPLIT INTO SEPARATE FILES"))
        _block.append(self.split_row)

        # C0D3D (2026-11-12): say out loud that the automatic cut points are only a
        # starting guess, and how to get exact ones.
        self.split_note = Gtk.Label(xalign=0.5, label=(
            "Sometimes the automatic timestamps or chapters aren't always 100% "
            "accurate. You might have to input them manually. Ripping the file as "
            "\u201cWhole title\u201d and opening it up in your media player will "
            "show you your timestamps."))
        self.split_note.set_wrap(True)
        self.split_note.set_max_width_chars(64)
        self.split_note.set_justify(Gtk.Justification.CENTER)
        self.split_note.add_css_class("dim")
        self.split_note.add_css_class("split-note")
        _block.append(self.split_note)


        self.lossless = Gtk.CheckButton(label="Lossless split")
        self.lossless.set_tooltip_text(
            "Only for an already-ripped video file: the pieces are copied straight "
            "out of the file instead of being encoded again, so it takes seconds and "
            "nothing is lost. Cut points land on the nearest keyframe (usually a "
            "second or two), unlike a re-encode which is frame-exact.")
        self.lossless.set_visible(False)
        _block.append(self.lossless)

        self.split_scroller = Gtk.ScrolledWindow()
        self.split_scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.split_scroller.set_min_content_height(150)
        self.split_scroller.set_visible(False)
        self.split_text = Gtk.TextView()
        self.split_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.split_text.set_monospace(True)
        self.split_text.add_css_class("split-editor")
        self.split_text.get_buffer().connect("changed", lambda *_: self.split_text_changed())
        self.split_scroller.set_child(self.split_text)
        _block.append(self.split_scroller)


        self.preview_label = plain("", "preview")
        self.preview_label.set_wrap(True)
        self.preview_label.set_xalign(0.5)

        settings_scroller = Gtk.ScrolledWindow()
        settings_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        settings_scroller.set_child(settings)
        settings_scroller.add_css_class("settings-scroller")
        settings_scroller.set_overlay_scrolling(False)
        settings_scroller.set_vexpand(True)
        # cap the column's minimum height: it scrolls, so it should never force
        # the queue box to be squeezed when the window gets short
        settings_scroller.set_min_content_height(140)
        self.settings_scroller = settings_scroller



        # one width for every dropdown so the column does not taper
        # only the audio/subtitle pair is trimmed, by half an inch between them
        pair_width = 200
        for _dropdown in (self.audio_dropdown, self.sub_dropdown,
                          self.transcript_dropdown):
            _dropdown.set_size_request(pair_width, -1)
        for _dropdown in (self.resolution_dropdown, self.lang_dropdown):
            _dropdown.set_size_request(290, -1)
        # quality sits alone above the trio: about an inch (96 px) narrower
        self.preset_dropdown.set_size_request(pair_width * 3 + 36 - 96, -1)
        for _dropdown in (self.denoise_dropdown, self.deblock_dropdown,
                          self.deband_dropdown):
            _dropdown.set_size_request(160, -1)          # all three on one line

        # audio, quality and subtitles share one line
        def _column(title, items):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            column.set_halign(Gtk.Align.CENTER)
            column.append(caption_centred_temp(title))
            for item in items[1:]:        # first item is the old caption
                column.append(item)
            return column

        _merged_names = ("AUDIO", "QUALITY", "SUBTITLES", "TRANSCRIPT")
        if all(name in _blocks for name in _merged_names):
            stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            stack.set_halign(Gtk.Align.CENTER)

            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            top.set_halign(Gtk.Align.CENTER)
            top.append(_column("QUALITY", _blocks.pop("QUALITY")))
            stack.append(top)

            # audio, subtitles and transcript all on one even line
            # (C0D3D, 2026-11-12)
            bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            bottom.set_halign(Gtk.Align.CENTER)
            for name in ("AUDIO", "SUBTITLES", "TRANSCRIPT"):
                bottom.append(_column(name, _blocks.pop(name)))
            stack.append(bottom)

            _blocks["AUDIO / QUALITY / SUBTITLES"] = [stack]

        _pair_names = ("LANGUAGE", "RESOLUTION")
        if all(name in _blocks for name in _pair_names):
            pair = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            pair.set_halign(Gtk.Align.CENTER)
            for name in _pair_names:
                pair.append(_column(name, _blocks.pop(name)))
            _blocks["LANGUAGE / RESOLUTION"] = [pair]

        _naming_names = ("FILE NAME", "EPISODE NAMES")
        if all(name in _blocks for name in _naming_names):
            naming = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
            naming.set_halign(Gtk.Align.CENTER)
            for name in _naming_names:
                naming.append(_column(name, _blocks.pop(name)))
            _blocks["FILE NAME / EPISODE NAMES"] = [naming]

        def _block_width(items):
            widest = 0
            for item in items:
                try:
                    _minimum, natural, _a, _b = item.measure(
                        Gtk.Orientation.HORIZONTAL, -1)
                except Exception:
                    natural = 0
                widest = max(widest, natural)
            return widest

        # a fixed, sensible order: the settings you pick first at the top
        _order = ["AUDIO / QUALITY / SUBTITLES", "LANGUAGE / RESOLUTION",
                  "FILE NAME", "ANIME CLEAN-UP", "FIRST EPISODE",
                  "SPLIT INTO SEPARATE FILES"]
        _ordered = [(_name, _blocks[_name]) for _name in _order if _name in _blocks]
        _ordered += [(name, items) for name, items in _blocks.items()
                     if name not in _order]

        settings.append(self.preview_label)
        self.preview_rule = self.section_rule()
        settings.append(self.preview_rule)

        # sections sit shoulder to shoulder: no air above or below, and the
        # hairlines between them carry no padding of their own
        # (C0D3D, 2026-11-12: "move all of this up ... just move it all up")
        settings.set_spacing(0)
        _first = True
        for _name, _items in _ordered:
            if not _first:
                rule = self.section_rule()
                rule.set_margin_top(0)
                rule.set_margin_bottom(0)
                settings.append(rule)
            _first = False
            group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            group.set_margin_top(0)
            group.set_margin_bottom(0)
            for _item in _items:
                group.append(_item)
            settings.append(group)

        paned.set_end_child(settings_scroller)
        self.preset_changed()
        self.split_text_changed()
        return paned

    # ---------------------------------------------------------------- queue
    def build_queue_card(self):
        box = card(2)   # C0D3D, 2026-11-11: compact queue card
        box.add_css_class("queue-card")

        # Caption and buttons share one row (C0D3D, 2026-11-11) so the buttons sit
        # right at the top edge of the card and the list starts under them.
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        head.append(caption("RIP QUEUE"))

        buttons = Gtk.FlowBox()
        buttons.add_css_class("queue-buttons")
        buttons.set_selection_mode(Gtk.SelectionMode.NONE)
        buttons.set_max_children_per_line(6)
        buttons.set_min_children_per_line(1)
        buttons.set_column_spacing(6)
        buttons.set_row_spacing(4)
        buttons.set_homogeneous(False)
        buttons.set_halign(Gtk.Align.CENTER)
        buttons.set_valign(Gtk.Align.CENTER)
        buttons.set_hexpand(True)

        self.start_button = icon_button("Start", "media-playback-start-symbolic")
        self.start_button.add_css_class("compact-button")
        self.start_button.add_css_class("orange-button")
        self.start_button.add_css_class("primary-action")
        self.start_button.connect("clicked", lambda *_: self.start_queue())
        buttons.append(self.start_button)

        self.stop_button = icon_button("Stop", "media-playback-stop-symbolic")
        self.stop_button.add_css_class("compact-button")
        self.stop_button.add_css_class("orange-button")
        self.stop_button.set_sensitive(False)
        self.stop_button.connect("clicked", lambda *_: self.stop_queue())
        buttons.append(self.stop_button)

        remove = icon_button("Remove", "list-remove-symbolic")
        remove.set_tooltip_text("Remove the ticked rips (Delete)")
        remove.add_css_class("compact-button")
        remove.add_css_class("orange-button")
        remove.connect("clicked", lambda *_: self.remove_selected())
        buttons.append(remove)

        remove_all = icon_button("Remove all", "edit-delete-symbolic")
        remove_all.set_tooltip_text("Empty the whole queue")
        remove_all.add_css_class("compact-button")
        remove_all.add_css_class("orange-button")
        remove_all.connect("clicked", lambda *_: self.remove_all())
        buttons.append(remove_all)

        clear = icon_button("Clear finished", "edit-clear-symbolic")
        clear.add_css_class("compact-button")
        clear.add_css_class("orange-button")
        clear.connect("clicked", lambda *_: self.clear_finished())
        buttons.append(clear)

        # C0D3D, 2026-11-12: redo the speech-to-text pass without re-ripping.
        self.retry_button = icon_button("Retry transcript",
                                        "view-refresh-symbolic")
        self.retry_button.set_tooltip_text(
            "Re-run the transcribe pass on a rip that is already finished "
            "(tick it, or click the row first)")
        self.retry_button.add_css_class("compact-button")
        self.retry_button.add_css_class("orange-button")
        self.retry_button.connect("clicked", lambda *_: self.retry_transcript())
        buttons.append(self.retry_button)

        self.hug_children(buttons)
        head.append(buttons)
        box.append(head)

        self.queue_list = Gtk.ListBox()
        self.queue_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.queue_list.add_css_class("queue-list")
        self.queue_list.connect("row-selected", self.on_job_selected)
        queue_scroller = Gtk.ScrolledWindow()
        queue_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        queue_scroller.set_min_content_height(96)
        queue_scroller.set_vexpand(True)      # take the room the card is given
        queue_scroller.set_child(self.queue_list)
        self.queue_scroller = queue_scroller
        box.append(queue_scroller)

        return box

    def build_progress_strip(self):
        """Always-visible progress strip along the bottom of the window."""
        strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        strip.add_css_class("progress-strip")

        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        strip.append(self.spinner)

        self.progress = Gtk.ProgressBar()
        self.progress.set_hexpand(True)
        self.progress.add_css_class("rip-progress")
        strip.append(self.progress)

        self.progress_label = plain("idle", "progress-text")
        self.progress_label.set_width_chars(12)
        self.progress_label.set_hexpand(True)
        self.progress_label.set_ellipsize(Pango.EllipsizeMode.END)
        strip.append(self.progress_label)

        self.counter_label = plain("", "counter")
        self.counter_label.set_width_chars(10)
        strip.append(self.counter_label)

        self.queue_summary = plain("Nothing queued.", "dim", ellipsize=True)
        self.queue_summary.set_width_chars(10)
        self.queue_summary.set_max_width_chars(52)
        self.queue_summary.set_xalign(1.0)
        self.queue_summary.set_ellipsize(Pango.EllipsizeMode.END)
        self.queue_summary.set_margin_start(10)
        strip.append(self.queue_summary)
        return strip

    # only these change value when the wheel passes over them
    WHEEL_SENSITIVE = (Gtk.SpinButton, Gtk.DropDown, Gtk.Scale)

    def freeze_wheel(self, widget):
        """The wheel must never change a number or a picker — but must scroll.

        GTK's own wheel handling on these widgets is switched off, and a
        capture-phase controller of our own scrolls the panel instead.
        Scrolled windows are left completely alone.
        """
        if isinstance(widget, self.WHEEL_SENSITIVE):
            mine = getattr(widget, "wheel_guard", None)
            if mine is None:
                for controller in list(widget.observe_controllers()):
                    if isinstance(controller, Gtk.EventControllerScroll):
                        controller.set_propagation_phase(
                            Gtk.PropagationPhase.NONE)
                guard = Gtk.EventControllerScroll(
                    flags=Gtk.EventControllerScrollFlags.VERTICAL)
                guard.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
                guard.connect("scroll", self.on_wheel_over_control)
                widget.add_controller(guard)
                widget.wheel_guard = guard

        child = widget.get_first_child()
        while child is not None:
            self.freeze_wheel(child)
            child = child.get_next_sibling()

    def sky_frame_dropdowns(self, widget):
        """Light blue frame on every picker (C0D3D, 2026-11-12)."""
        if isinstance(widget, Gtk.DropDown):
            widget.add_css_class("sky-frame")
        child = widget.get_first_child()
        while child is not None:
            self.sky_frame_dropdowns(child)
            child = child.get_next_sibling()

    def install_wheel_fallback(self):
        """Catch the wheel only for the pane the pointer is actually over.

        C0D3D (2026-11-11): "i should only be able to scroll, where the pink
        square is, when hovered over that section, but no matter where im
        hovered, that part scrolls". The old fallback walked a fixed list of
        panes and always landed on the settings column, so the whole window
        drove it. It now scrolls the nearest scroller under the pointer, and
        nothing at all when that one has nothing to scroll.
        """
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self.remember_pointer)
        motion.connect("leave", self.forget_pointer)
        self.add_controller(motion)
        self.pointer = None
        # C0D3D (2026-11-12): "when i click top source/browse and search an mkv
        # file, and then i click below in the settings portion, the top portion
        # doesnt auto hide". The file chooser swallows the pointer motion, so
        # the cached position stayed at the last spot over the SOURCE card and
        # the card thought it was still hovered. A press is a reliable update
        # that no popup can eat, so clicks refresh the position too. A legacy
        # controller is used on purpose: it never claims the sequence, so no
        # button in the window loses its own click.
        press = Gtk.GestureClick()
        press.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        press.connect("pressed", self.on_pointer_press)
        self.add_controller(press)
        controller = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL)
        controller.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        controller.connect("scroll", self.on_wheel_fallback)
        self.add_controller(controller)

    def remember_pointer(self, _controller, x, y):
        self.pointer = (x, y)

    def forget_pointer(self, _controller):
        # pointer left the window: nothing is hovered any more
        self.pointer = None

    def on_pointer_press(self, _gesture, _n_press, x, y):
        """Take the pointer position from a click as well as from motion."""
        self.pointer = (x, y)
        if self.dead or not hasattr(self, "source_card"):
            return
        if self.point_over_source(x, y):
            return
        # A click away from the card ends any focus hold on it, even when the
        # widget clicked does not take focus away from the source entry.
        self.source_hold_until = 0.0
        self.source_focus_released = True
        self.source_last_over = time.monotonic()

    # ---------------------------------------------------------- auto-hiding
    # C0D3D (2026-11-11): "can we make this top part auto hide, with a smooth
    # slow hide animation" / "when i hover over it it opens" / "when i unhover
    # over it, i want a 2 second delay before it hides". The SOURCE / SAVE TO
    # card slides up out of the way and gives its height to the panes below.
    SOURCE_HIDE_DELAY = 2.0     # seconds after the pointer leaves
    SOURCE_REVEAL_ZONE = 56     # px from the top of the window that opens it

    def install_source_autohide(self):
        self.source_last_over = time.monotonic()
        self.source_hold_until = 0.0
        self.source_focus_released = False
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", self.on_source_focus_in)
        focus.connect("leave", self.on_source_focus_out)
        self.source_card.add_controller(focus)
        GLib.timeout_add(120, self.watch_source_autohide)

    def on_source_focus_in(self, _controller):
        # typing a path must never yank the card away
        self.source_focus_released = False
        self.source_hold_until = time.monotonic() + 30.0

    def on_source_focus_out(self, _controller):
        self.source_hold_until = 0.0
        self.source_last_over = time.monotonic()

    def source_is_shown(self):
        return bool(self.source_revealer.get_reveal_child())

    def set_source_shown(self, shown):
        if self.dead or self.source_is_shown() == shown:
            return
        self.source_revealer.set_reveal_child(shown)

    def point_over_source(self, x, y):
        """True when that window point is the card, or in the strip that opens it."""
        # The top band both opens a hidden card and keeps a shown one open, so
        # hovering there cannot make it flicker open/closed every 2 seconds.
        if y <= self.SOURCE_REVEAL_ZONE:
            return True
        if not self.source_is_shown():
            return False
        widget = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while widget is not None:
            if widget is self.source_card or widget is self.source_revealer:
                return True
            widget = widget.get_parent()
        return False

    def pointer_over_source(self):
        """True when the pointer is over the card, or in the strip that opens it."""
        if self.pointer is None:
            return False
        return self.point_over_source(self.pointer[0], self.pointer[1])

    def focus_inside_source(self):
        widget = self.get_focus()
        while widget is not None:
            if widget is self.source_card:
                return True
            widget = widget.get_parent()
        return False

    def watch_source_autohide(self):
        if self.dead:
            return False
        now = time.monotonic()
        over = self.pointer_over_source()
        popover_open = getattr(self, "theme_popover", None) is not None \
            and self.theme_popover.get_visible()
        focused = self.focus_inside_source() and not self.source_focus_released
        if (over or popover_open or focused
                or now < self.source_hold_until):
            self.source_last_over = now
            self.set_source_shown(True)
        elif self.source_is_shown() and \
                now - self.source_last_over >= self.SOURCE_HIDE_DELAY:
            self.set_source_shown(False)
        return True

    def scroller_under_pointer(self):
        if self.pointer is None:
            return None
        widget = self.pick(self.pointer[0], self.pointer[1],
                           Gtk.PickFlags.DEFAULT)
        while widget is not None:
            if isinstance(widget, Gtk.ScrolledWindow):
                return widget
            widget = widget.get_parent()
        return None

    def on_wheel_fallback(self, _controller, _dx, dy):
        scroller = self.scroller_under_pointer()
        if scroller is None:
            return False
        adjustment = scroller.get_vadjustment()
        if adjustment is None:
            return False
        if adjustment.get_upper() <= adjustment.get_page_size() + 1:
            return False
        step = adjustment.get_step_increment() or 24.0
        adjustment.set_value(adjustment.get_value() + dy * step * 2)
        return True

    def on_wheel_over_control(self, controller, _dx, dy):
        """Send the scroll to the panel instead of changing this control."""
        widget = controller.get_widget()
        panel = None
        if widget is not None:
            parent = widget.get_parent()
            while parent is not None:
                if isinstance(parent, Gtk.ScrolledWindow):
                    panel = parent
                    break
                parent = parent.get_parent()
        if panel is not None:
            adjustment = panel.get_vadjustment()
            if adjustment is not None:
                step = adjustment.get_step_increment() or 24.0
                adjustment.set_value(adjustment.get_value() + dy * step * 2)
        return True

    # ---------------------------------------------------------------- keys
    def save_split(self):
        """Remember the divider position in pixels — nothing clever."""
        if self.dead or not hasattr(self, "paned"):
            return
        if self.paned.get_orientation() != Gtk.Orientation.HORIZONTAL:
            return
        self.state["split_position"] = int(self.paned.get_position())
        save_state(self.state)

    def match_dropdown_height(self):
        """Give the show dropdown the same height as the buttons beside it."""
        button = getattr(self, "browse_button", None)
        if button is None:
            return False
        target = max(button.measure(Gtk.Orientation.VERTICAL, -1).minimum,
                     self.show_dropdown.measure(Gtk.Orientation.VERTICAL, -1).minimum)
        if target > 0:
            self.show_dropdown.set_size_request(-1, target)
            button.set_size_request(-1, target)
        return False

    def restore_split(self):
        if self.dead or not hasattr(self, "paned"):
            return False
        if self.paned.get_orientation() != Gtk.Orientation.HORIZONTAL:
            return False
        saved = int(self.state.get("split_position") or 0)
        width = self.paned.get_width()
        if saved > 0 and width > 0:
            self.paned.set_position(max(240, min(saved, max(240, width - 320))))
        return False

    def save_queue_split(self):
        if self.dead or not hasattr(self, "queue_paned"):
            return
        height = self.queue_paned.get_height()
        if height <= 0:
            return
        queue_height = max(90, height - self.queue_paned.get_position())
        if abs(queue_height - int(self.state.get("queue_height") or 0)) > 2:
            self.state["queue_height"] = int(queue_height)
            save_state(self.state)

    def restore_queue_split(self):
        if self.dead or not hasattr(self, "queue_paned"):
            return False
        saved = int(self.state.get("queue_height") or 0)
        height = self.queue_paned.get_height()
        if saved > 0 and height > 0:
            self.queue_paned.set_position(max(120, height - saved))
        return False

    def watch_split(self):
        """Keep both dividers where he put them.

        A re-tile (switching tabs and back) hands the panes a different size;
        GTK then clamps the divider to fit and never restores it. So on any size
        change we re-apply the remembered split and record whatever GTK ends up
        with as the baseline — only movement *away* from that baseline at a
        steady size is him dragging, and only that is saved.
        """
        if self.dead or not hasattr(self, "paned"):
            return False
        now = time.monotonic()

        # --- sidebar / settings column (horizontal)
        if self.paned.get_orientation() == Gtk.Orientation.HORIZONTAL:
            width = self.paned.get_width()
            if width > 0 and self.get_width() > 400:
                saved = int(self.state.get("split_position") or 0)
                if width != getattr(self, "last_paned_width", None):
                    self.last_paned_width = width
                    self.paned_resized_at = now
                    if saved > 0:
                        self.restore_split()
                    self.split_baseline = self.paned.get_position()
                elif (now - getattr(self, "paned_resized_at", 0.0) >= 0.8
                      and self.paned.get_position() != getattr(self, "split_baseline", None)):
                    position = self.paned.get_position()
                    if position > 0:
                        self.state["split_position"] = int(position)
                        save_state(self.state)
                        ripper.log("split saved: %d" % position)
                    self.split_baseline = position

        # --- rip queue (vertical)
        if hasattr(self, "queue_paned"):
            height = self.queue_paned.get_height()
            if height > 0:
                saved_queue = int(self.state.get("queue_height") or 0)
                if height != getattr(self, "last_queue_height", None):
                    self.last_queue_height = height
                    self.queue_resized_at = now
                    if saved_queue > 0:
                        self.restore_queue_split()
                    self.queue_baseline = self.queue_paned.get_position()
                elif (now - getattr(self, "queue_resized_at", 0.0) >= 0.8
                      and self.queue_paned.get_position() != getattr(self, "queue_baseline", None)):
                    position = self.queue_paned.get_position()
                    self.queue_baseline = position
                    current = height - position
                    if current > 0:
                        self.save_queue_split()
        return True

    def watch_drive(self):
        """A USB reader can appear at any time — pick it up without a restart."""
        if self.dead:
            return False
        sources = ripper.list_sources()
        current = self.source_entry.get_text().strip()
        if sources and not current:
            self.source_entry.set_text(sources[0])
            self.source_status.set_text(
                "Disc drive detected: %s — press Scan disc." % sources[0])
        elif sources and current.startswith("/dev/sr") and current not in sources:
            self.source_entry.set_text(sources[0])
            self.source_status.set_text(
                "Drive changed — now using %s." % sources[0])
        return True

    def watch_width(self):
        """GTK4 has no size-allocate signal a binding can hook, so poll cheaply."""
        if self.dead:
            return False
        self.on_resized(self.get_width(), self.get_height())
        return True

    def on_resized(self, width, height):
        """Below ~980px the two columns stop fitting: stack them instead."""
        if width <= 0 or not hasattr(self, "paned"):
            return
        want_vertical = width < 1180
        if want_vertical != getattr(self, "compact", None):
            self.compact = want_vertical
            self.apply_layout(want_vertical)

    def apply_layout(self, compact):
        """Wide: two columns with the settings scrolling inside.
        Narrow: one long page that scrolls as a whole, so nothing is ever clipped."""
        self.paned_save_guard = True
        try:
            self._apply_layout(compact)
        finally:
            self.paned_save_guard = False

    def _apply_layout(self, compact):
        if compact:
            width = max(self.get_width() - 48, 320)
            _minimum, natural, _a, _b = self.settings_card.measure(
                Gtk.Orientation.VERTICAL, width)
            natural = max(natural, 520)
            self.settings_scroller.set_policy(Gtk.PolicyType.NEVER,
                                              Gtk.PolicyType.NEVER)
            self.page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.paned.set_orientation(Gtk.Orientation.VERTICAL)
            self.paned.set_position(200)
            self.paned.set_size_request(-1, 200 + natural)
            _q_min, queue_natural, _qc, _qd = self.queue_card.measure(
                Gtk.Orientation.VERTICAL, width)
            self.queue_paned.set_size_request(-1, 200 + natural + queue_natural)
            self.queue_paned.set_position(200 + natural)
            self.titles_scroller.set_min_content_height(120)
            self.queue_scroller.set_min_content_height(96)
        else:
            self.paned.set_size_request(-1, -1)
            self.queue_paned.set_size_request(-1, -1)
            self.page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.NEVER)
            self.settings_scroller.set_policy(Gtk.PolicyType.NEVER,
                                              Gtk.PolicyType.AUTOMATIC)
            self.paned.set_orientation(Gtk.Orientation.HORIZONTAL)
            self.titles_scroller.set_min_content_height(120)
            self.queue_scroller.set_min_content_height(56)

    def build_keys(self):
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self.on_key)
        self.add_controller(controller)

    def on_key(self, _controller, keyval, _keycode, state):
        ctrl = state & Gdk.ModifierType.CONTROL_MASK
        if keyval == Gdk.KEY_F5:
            self.start_scan()
            return True
        if ctrl and keyval in (Gdk.KEY_o, Gdk.KEY_O):
            self.browse_source()
            return True
        if ctrl and keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.start_queue()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace) and (
                self.window_focus_is_queue()):
            self.remove_selected()
            return True
        return False

    def window_focus_is_queue(self):
        widget = self.get_focus()
        while widget is not None:
            if widget is self.queue_list:
                return True
            widget = widget.get_parent()
        return False

    # ---------------------------------------------------------------- bootstrap
    def bootstrap(self):
        # restore the saved settings
        saved = self.state
        for index, preset in enumerate(ripper.PRESETS):
            if preset["key"] == saved.get("preset"):
                self.preset_dropdown.set_selected(index)
        for index, mode in enumerate(ripper.AUDIO_MODES):
            if mode["key"] == saved.get("audio"):
                self.audio_dropdown.set_selected(index)
        for index, mode in enumerate(ripper.SUB_MODES):
            if mode["key"] == saved.get("subs"):
                self.sub_dropdown.set_selected(index)
        for index, mode in enumerate(ripper.AUDIO_LANGUAGES):
            if mode["key"] == saved.get("audio_lang"):
                self.lang_dropdown.set_selected(index)
        for index, mode in enumerate(ripper.RESOLUTIONS):
            if mode["key"] == saved.get("resolution"):
                self.resolution_dropdown.set_selected(index)
        for index, mode in enumerate(ripper.DENOISE_MODES):
            if mode["key"] == saved.get("denoise"):
                self.denoise_dropdown.set_selected(index)
        for index, mode in enumerate(ripper.DEBLOCK_MODES):
            if mode["key"] == saved.get("deblock"):
                self.deblock_dropdown.set_selected(index)
        for index, mode in enumerate(ripper.DEBAND_MODES):
            if mode["key"] == saved.get("deband"):
                self.deband_dropdown.set_selected(index)
        wanted = saved.get("transcript") or "best"
        for index, mode in enumerate(ripper.TRANSCRIPT_MODES):
            if mode["key"] == wanted:
                self.transcript_dropdown.set_selected(index)
        if saved.get("anime"):
            self.anime_check.set_active(True)
        self.set_theme(saved.get("theme") or "matrix", remember=False)
        if saved.get("markers") is False:
            self.markers.set_active(False)
        if saved.get("episode_show"):
            self.show_entry.set_text(saved["episode_show"])
            if saved.get("episode_start"):
                self.episode_start.set_value(int(saved["episode_start"]))
        # the file name is a fresh-session thing, like the scanned titles
        self.name_entry.set_text("Disc")
        self.preset_changed()
        self.apply_layout(self.get_width() < 1180)
        GLib.timeout_add(300, self.watch_width)
        GLib.timeout_add(400, self.restore_split)
        GLib.timeout_add(1400, self.restore_split)
        GLib.timeout_add(2600, self.restore_split)
        GLib.timeout_add(450, self.restore_queue_split)
        GLib.timeout_add(1500, self.restore_queue_split)
        GLib.timeout_add(2700, self.restore_queue_split)
        GLib.timeout_add(300, self.watch_split)
        GLib.timeout_add(400, self.match_dropdown_height)
        GLib.timeout_add(2000, self.watch_drive)

        # a fresh session: nothing scanned, nothing remembered
        self.titles = []
        self.rebuild_titles()
        self.source_entry.set_text("")
        self.source = ""
        self.state.pop("source", None)
        self.state.pop("name", None)
        save_state(self.state)
        drive = (ripper.list_sources() or [""])[0]
        if drive:
            self.source_entry.set_text(drive)
            self.source_status.set_text(
                "Ready — disc drive %s. Press Scan disc." % drive)
        else:
            self.source_status.set_text(
                "No optical drive found. Plug one in, or browse to an ISO / VIDEO_TS folder.")
        # Do not leave the caret parked in the source path: a focused widget
        # holds the auto-hiding SOURCE card open (C0D3D, 2026-11-11), so the
        # window would never hide it until something else took focus.
        self.set_focus(None)
        return False

    # ---------------------------------------------------------------- scan
    def start_scan(self):
        source = self.source_entry.get_text().strip()
        if not source:
            self.flash_status("Pick a source first — a drive, an ISO, or a VIDEO_TS folder.")
            return
        if self.running:
            self.flash_status("A rip is running; stop it before rescanning.")
            return
        if not os.path.exists(source):
            self.flash_status("That path does not exist: %s" % source)
            return

        self.scan_generation += 1
        token = self.scan_generation
        self.source = source
        self.state["source"] = source
        self.state["output_dir"] = self.output_entry.get_text().strip()
        save_state(self.state)

        self.titles = []
        self.rebuild_titles()
        self.source_status.set_text("Scanning %s …" % source)
        self.scan_now.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        self.progress.set_fraction(0.0)
        self.progress_label.set_text("scanning titles…")
        self.append_log("scan: %s" % source)

        command = ripper.scan_command(source)
        ripper.log("scan start: %s" % " ".join(command))
        threading.Thread(target=self.scan_worker, args=(command, source, token),
                         daemon=True).start()

    def scan_worker(self, command, source, token):
        collected = []
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True,
                                       bufsize=1, start_new_session=True)
        except OSError as error:
            GLib.idle_add(self.scan_failed,
                          "HandBrake would not start: %s" % error, token)
            return

        def read_stdout():
            for line in process.stdout:
                collected.append(line)

        def read_stderr():
            for line in process.stderr:
                GLib.idle_add(self.append_log_line, line.rstrip())

        out_thread = threading.Thread(target=read_stdout, daemon=True)
        err_thread = threading.Thread(target=read_stderr, daemon=True)
        out_thread.start()
        err_thread.start()
        process.wait()
        out_thread.join(timeout=2)
        err_thread.join(timeout=2)
        text = "".join(collected)
        data = ripper.parse_scan(text)
        if data is None or not data["titles"]:
            GLib.idle_add(self.scan_failed,
                          "No titles found. Is there really a disc in the drive?",
                          token)
            return
        GLib.idle_add(self.scan_done, data, source, token)

    def scan_done(self, data, source, token=None):
        self.start_is_manual = False
        if self.dead:
            return
        if token is not None and token != self.scan_generation:
            # a newer scan already started; this result is stale
            return False
        self.titles = data["titles"]
        self.main_feature = data["main"]
        self.rebuild_titles()
        self.scan_now.set_sensitive(True)
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.progress_label.set_text("idle")
        self.progress.set_fraction(0.0)
        self.name_entry.set_text(self.disc_label(source))
        self.source_status.set_text(
            "%s — %d titles · main feature is title %d"
            % (source, len(self.titles), self.main_feature or
               (self.longest_title().number if self.longest_title() else 0)))
        self.append_log("scan finished: %d titles" % len(self.titles))
        self.suggest_episode_count()
        return False

    def scan_failed(self, message, token=None):
        if self.dead:
            return
        if token is not None and token != self.scan_generation:
            return False
        self.scan_now.set_sensitive(True)
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.progress_label.set_text("idle")
        self.source_status.set_text(message)
        self.append_log(message)
        return False

    def disc_label(self, source):
        if re.match(r"^/dev/sr\d+$", source):
            try:
                out = subprocess.run(["blkid", "-o", "value", "-s", "LABEL", source],
                                     capture_output=True, text=True, timeout=6)
                label = (out.stdout or "").strip().splitlines()
                if label:
                    return ripper.safe_filename(label[0], "Disc")
            except (OSError, subprocess.SubprocessError):
                pass
            return "Disc"
        base = os.path.basename(source.rstrip("/"))
        if base.upper() == "VIDEO_TS":
            base = os.path.basename(os.path.dirname(source.rstrip("/")))
        if base.lower().endswith((".iso", ".img")) or ripper.is_video_file(base):
            base = os.path.splitext(base)[0]
        return ripper.safe_filename(base, "Disc")

    def longest_title(self):
        return max(self.titles, key=lambda t: t.duration) if self.titles else None

    # ---------------------------------------------------------------- titles list
    def clear_titles(self):
        if self.running:
            self.flash_status("Stop the rip before clearing the titles.")
            return
        self.titles = []
        self.main_feature = 0
        self.rebuild_titles()
        self.preview_label.set_visible(False)
        if hasattr(self, "preview_rule"):
            self.preview_rule.set_visible(False)
        self.source_status.set_text("Title list cleared — scan a disc to load another.")

    def rebuild_titles(self):
        while True:
            child = self.titles_list.get_first_child()
            if child is None:
                break
            self.titles_list.remove(child)

        longest = self.longest_title()
        # A TV disc usually carries the episodes plus a "play all" playlist that
        # runs them back to back. Ticking that by default would rip the whole
        # disc as one 2-hour file, so on a disc with several episode-length
        # titles the episodes get ticked and the long one is left alone.
        episodes = [title for title in self.titles if 900 <= title.duration <= 5400]
        play_all = [title for title in self.titles if title.duration > 5400]
        tv_disc = len(episodes) >= 2
        default_on = {title.number for title in episodes} if tv_disc else set()
        if not tv_disc and longest is not None:
            default_on = {longest.number}
        for title in self.titles:
            row = Gtk.ListBoxRow()
            row.add_css_class("title-row")
            row.title = title
            # 6px of spacing, not 10: in a narrow titles column (the 1080p at
            # half width) the row used to come out ~28px wider than the pane, so
            # the last deadline column sat flush against the clip edge and the
            # badge was squeezed (C0D3D, 2026-11-11).
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

            check = Gtk.CheckButton()
            check.add_css_class("title-check")
            if title.number in default_on:
                check.set_active(True)
            check.title_info = title
            check.connect("toggled", lambda *_: self.title_ticked())
            line.append(check)

            number = Gtk.Label(label="%02d" % title.number, xalign=0.5, width_chars=2)
            number.add_css_class("title-number")
            line.append(number)

            name = Gtk.Label(xalign=0.0, label=title.name or ("Title %d" % title.number))
            name.add_css_class("title-name")
            name.set_hexpand(True)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            line.append(name)

            if tv_disc and title in play_all:
                badge = Gtk.Label(label="PLAY ALL")
                badge.add_css_class("badge")
                badge.add_css_class("warn-badge")
                line.append(badge)
            elif not tv_disc and longest is not None \
                    and title.number == longest.number:
                badge = Gtk.Label(label="MAIN")
                badge.add_css_class("badge")
                line.append(badge)

            summary = Gtk.Label(label=title.summary(), xalign=1.0)
            summary.add_css_class("title-summary")
            summary.set_ellipsize(Pango.EllipsizeMode.END)
            # cap the natural width so the row can shrink instead of pushing the
            # size column into the card edge
            summary.set_max_width_chars(20)
            line.append(summary)
            row.summary_label = summary
            row.name_label = name
            row.mapped_episode = ""

            estimated = Gtk.Label(label=ripper.fmt_bytes(title.size_estimate()),
                                  xalign=1.0, width_chars=9)
            estimated.add_css_class("title-size")
            estimated.set_ellipsize(Pango.EllipsizeMode.END)
            line.append(estimated)

            row.set_child(line)
            self.titles_list.append(row)

        self.titles_count.set_text("%d title%s" % (
            len(self.titles), "" if len(self.titles) == 1 else "s"))
        if self.titles:
            self.titles_hint.set_visible(False)
        if tv_disc:
            self.titles_hint.set_text(
                "%d episodes found. The long PLAY ALL title is left unticked — "
                "ticking it would rip the whole disc as one file."
                % len(episodes))
            self.titles_hint.set_visible(True)
        self.split_mode_changed()

    def checked_titles(self):
        picked = []
        child = self.titles_list.get_first_child()
        while child is not None:
            box = child.get_child()
            check = box.get_first_child() if box is not None else None
            if check is not None and hasattr(check, "title_info") and check.get_active():
                picked.append(check.title_info)
            child = child.get_next_sibling()
        return picked

    def focused_title(self):
        picked = self.checked_titles()
        if picked:
            return picked[0]
        return self.longest_title()

    # ---------------------------------------------------------------- settings
    def preset_changed(self):
        index = self.preset_dropdown.get_selected()
        if index < 0 or index >= len(ripper.PRESETS):
            index = 1
        preset = ripper.PRESETS[index]
        self.preset_note.set_text(preset["note"])
        child = self.titles_list.get_first_child()
        while child is not None:
            box = child.get_child()
            labels = []
            inner = box.get_first_child() if box is not None else None
            while inner is not None:
                labels.append(inner)
                inner = inner.get_next_sibling()
            if len(labels) >= 2 and hasattr(child, "title"):
                labels[-1].set_text(ripper.fmt_bytes(child.title.size_estimate(preset["key"])))
            child = child.get_next_sibling()

    def current_preset(self):
        index = max(0, self.preset_dropdown.get_selected())
        return ripper.PRESETS[min(index, len(ripper.PRESETS) - 1)]

    def current_audio(self):
        index = max(0, self.audio_dropdown.get_selected())
        return ripper.AUDIO_MODES[min(index, len(ripper.AUDIO_MODES) - 1)]["key"]

    def current_resolution(self):
        index = max(0, self.resolution_dropdown.get_selected())
        return ripper.RESOLUTIONS[
            min(index, len(ripper.RESOLUTIONS) - 1)]["key"]

    def current_denoise(self):
        index = max(0, self.denoise_dropdown.get_selected())
        return ripper.DENOISE_MODES[
            min(index, len(ripper.DENOISE_MODES) - 1)]["key"]

    def current_deband(self):
        index = max(0, self.deband_dropdown.get_selected())
        return ripper.DEBAND_MODES[
            min(index, len(ripper.DEBAND_MODES) - 1)]["key"]

    def current_transcript(self):
        index = max(0, self.transcript_dropdown.get_selected())
        return ripper.TRANSCRIPT_MODES[
            min(index, len(ripper.TRANSCRIPT_MODES) - 1)]["key"]

    def current_deblock(self):
        index = max(0, self.deblock_dropdown.get_selected())
        return ripper.DEBLOCK_MODES[
            min(index, len(ripper.DEBLOCK_MODES) - 1)]["key"]

    def current_audio_lang(self):
        index = max(0, self.lang_dropdown.get_selected())
        return ripper.AUDIO_LANGUAGES[
            min(index, len(ripper.AUDIO_LANGUAGES) - 1)]["key"]

    def current_subs(self):
        index = max(0, self.sub_dropdown.get_selected())
        return ripper.SUB_MODES[min(index, len(ripper.SUB_MODES) - 1)]["key"]

    def current_mode(self):
        for key, button in self.mode_buttons.items():
            if button.get_active():
                return key
        return "whole"

    def use_lossless(self):
        box = getattr(self, "lossless", None)
        return (box is not None and box.get_active()
                and self.current_mode() != "whole"
                and ripper.is_video_file(self.source_entry.get_text().strip()))

    def on_mode_clicked(self, key):
        """A mode button was clicked: make sure it is the active one, then refill."""
        button = self.mode_buttons.get(key)
        if button is not None and not button.get_active():
            button.set_active(True)          # fires toggled -> split_mode_changed
        self.split_mode_changed(key)

    def split_mode_changed(self, mode=None):
        mode = mode or self.current_mode()
        scroller = getattr(self, "split_scroller", None)
        if scroller is not None:
            scroller.set_visible(mode != "whole")
        box = getattr(self, "lossless", None)
        if box is not None:
            box.set_visible(mode != "whole"
                            and ripper.is_video_file(
                                self.source_entry.get_text().strip()))
        if mode == "chapters":
            self.split_text.set_tooltip_text(
                'Chapter ranges, comma separated — e.g. "1-4, 5-8" makes two files. '
                "Each range is encoded on its own so every file starts exactly on "
                "the chapter.")
        elif mode == "timestamps":
            self.split_text.set_tooltip_text(
                "One line per file: START [- END] then a name — e.g. "
                "00:22:10-00:44:30 Second episode. Leave END out to run to the end "
                "of the title.")
        if hasattr(self, "split_text"):
            # Switching to a different split mode always rewrites the box — chapter
            # ranges out, timestamps in, and the other way round (C0D3D, 2026-11-10).
            # Re-clicking the mode you are already on only fills it if it is empty,
            # so a stray click cannot wipe times he has edited by hand.
            switched = mode != getattr(self, "_last_fill_mode", None)
            self._last_fill_mode = mode
            if mode != "whole" and (switched or not self.split_text_value().strip()):
                self.fill_split_for_mode(mode)
            self.split_text_changed()
        if getattr(self, "compact", False) and hasattr(self, "queue_paned"):
            self._apply_layout(True)

    def fill_split_for_mode(self, mode):
        """Write the default cut points into the box for the chosen split mode."""
        title = self.focused_title()
        if title is None or not getattr(title, "duration", 0):
            # Silence here looked like a dead button (C0D3D, 2026-11-10).
            self.flash_status("Scan a disc and tick a title first — "
                              "there is nothing to cut up yet.")
            return
        parts = max(1, int(self.episode_parts.get_value()))
        chapters = len(title.chapters)
        if mode == "chapters":
            if chapters < 2:
                return
            parts = min(parts, chapters)
            step = chapters / float(parts)
            ranges = []
            for index in range(parts):
                first = int(round(index * step)) + 1
                last = int(round((index + 1) * step))
                last = max(last, first)
                ranges.append("%d-%d" % (first, last) if last > first else "%d" % first)
            self.split_text.get_buffer().set_text(", ".join(ranges) + "\n")
            return
        total = float(title.duration)
        step = total / parts
        starts = [value for value in title.chapter_starts if 0.0 < value < total]
        edges = [0.0]
        for index in range(1, parts):
            target = step * index
            if starts:
                nearest = min(starts, key=lambda value: abs(value - target))
                if abs(nearest - target) <= 45.0:
                    target = nearest
            edges.append(target)
        edges.append(total)
        lines = ["%s-%s part %02d" % (ripper.fmt_clock(edges[index]),
                                      ripper.fmt_clock(edges[index + 1]), index + 1)
                 for index in range(parts)]
        self.split_text.get_buffer().set_text("\n".join(lines) + "\n")

    def split_text_value(self):
        buffer = self.split_text.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

    def split_text_changed(self):
        titles = self.checked_titles()
        mode = self.current_mode()
        preset = self.current_preset()
        if not titles:
            self.planned_jobs = 0
            self.preview_label.set_visible(False)
            if hasattr(self, "preview_rule"):
                self.preview_rule.set_visible(False)
            self.refresh_start()
            return
        if mode == "whole":
            count = len(titles)
            total = sum(title.size_estimate(preset["key"]) for title in titles)
            self.preview_label.set_text(
                "%d file%s, about %s total (estimate)."
                % (count, "" if count == 1 else "s", ripper.fmt_bytes(total)))
        else:
            pieces = 0
            total = 0.0
            for title in titles:
                jobs = ripper.segment_jobs(
                    title, mode, self.split_text_value(), "x",
                    self.split_text_value())
                for job in jobs:
                    if job.get("start") is not None:
                        span = (job["stop"] or title.duration) - job["start"]
                    elif job.get("chapters"):
                        low, _, high = job["chapters"].partition("-")
                        starts = title.chapter_starts
                        first = max(0, int(low) - 1)
                        last = min(len(title.chapters) - 1, int(high) - 1)
                        span = sum(title.chapters[first:last + 1])
                    else:
                        span = title.duration
                    total += title.size_estimate(preset["key"]) * (
                        span / max(1.0, title.duration))
                    pieces += 1
            if pieces == 0:
                self.planned_jobs = 0
                self.refresh_start()
                self.preview_label.set_text(
                    "Nothing to split yet — add chapter ranges or timestamps.")
            elif self.use_lossless():
                self.preview_label.set_text(
                    "%d files, cut straight out of the file with no re-encode — "
                    "seconds, not minutes, and the picture is untouched."
                    % pieces)
            else:
                self.preview_label.set_text(
                    "%d files across %d title%s, about %s total (estimate)."
                    % (pieces, len(titles), "" if len(titles) == 1 else "s",
                       ripper.fmt_bytes(total)))
        self.planned_jobs = count if mode == "whole" else pieces
        if hasattr(self, "preview_label"):
            self.preview_label.set_visible(True)
            if hasattr(self, "preview_rule"):
                self.preview_rule.set_visible(True)

        mapping = {}
        if mode == "whole":
            ordered = sorted(titles, key=lambda item: item.number)
            for position, entry in enumerate(ordered):
                names = self.episode_labels(len(ordered))
                if position < len(names):
                    mapping[entry.number] = names[position]
        child = self.titles_list.get_first_child()
        while child is not None:
            title = getattr(child, "title", None)
            label = getattr(child, "summary_label", None)
            if title is not None and label is not None:
                mapped = mapping.get(title.number)
                name_label = getattr(child, "name_label", None)
                label.set_text(title.summary())
                if mapped and name_label is not None:
                    name_label.set_text(mapped)
                    name_label.add_css_class("mapped-name")
                elif name_label is not None:
                    name_label.set_text(title.name or ("Title %d" % title.number))
                    name_label.remove_css_class("mapped-name")
            child = child.get_next_sibling()

        if mode == "whole":
            labels = self.episode_labels(len(titles))
            if labels:
                preview = "; ".join(labels[:3])
                if len(labels) > 3:
                    preview += "; plus %d more" % (len(labels) - 3)
                self.preview_label.set_text(
                    "%d file%s — %s" % (len(labels),
                                        "" if len(labels) == 1 else "s", preview))
        self.refresh_start()

    # ---------------------------------------------------------------- episodes
    def refresh_numbering_visibility(self):
        if hasattr(self, "numbering"):
            self.numbering.set_visible(not bool(self.episode_rows))

    def on_start_changed(self, *_args):
        if not self.auto_setting_start:
            self.start_is_manual = True
        self.split_text_changed()

    def set_start_episode(self, value):
        """Set the number on his behalf, without marking it as his choice."""
        self.auto_setting_start = True
        try:
            self.episode_start.set_value(max(1, int(value)))
        finally:
            self.auto_setting_start = False

    def name_style_key(self):
        return self.detected_style

    def selected_season(self):
        return None

    def lookup_show(self):
        query = self.show_entry.get_text().strip()
        if not query:
            self.episode_status.set_text("Type a show name first.")
            return
        self.episode_status.set_text("Searching for “%s”…" % query)
        threading.Thread(target=self.search_worker, args=(query,),
                         daemon=True).start()

    def search_worker(self, query):
        shows = episode_names.search(query)
        GLib.idle_add(self.apply_shows, shows, query)

    def apply_shows(self, shows, query):
        if self.dead:
            return False
        if not shows:
            self.episode_status.set_text(
                "No shows found for “%s” — check the name or your connection." % query)
            return False
        self.episode_shows = shows
        self.episode_runtime = int(shows[0].get("runtime") or 0)
        labels = ["%s (%s)" % (show["name"],
                               (show["premiered"] or "")[:4] or "?")
                  for show in shows]
        self.show_dropdown.set_model(Gtk.StringList.new(labels))
        self.show_dropdown.set_sensitive(True)
        self.show_dropdown.set_selected(0)
        self.episode_status.set_text(
            "%d match%s — pick one in the list below."
            % (len(shows), "" if len(shows) == 1 else "es"))
        self.load_episodes(shows[0]["id"], shows[0]["name"])
        return False

    def on_show_selected(self):
        if not self.episode_shows:
            return
        index = self.show_dropdown.get_selected()
        if 0 <= index < len(self.episode_shows):
            show = self.episode_shows[index]
            self.episode_runtime = int(show.get("runtime") or 0)
            self.load_episodes(show["id"], show["name"])

    def load_episodes(self, show_id, show_name):
        self.episode_show = show_name
        self.episode_status.set_text("Fetching the episode list for %s…" % show_name)
        threading.Thread(target=self.episodes_worker, args=(show_id, show_name),
                         daemon=True).start()

    def episodes_worker(self, show_id, show_name):
        rows = episode_names.episodes(show_id)
        GLib.idle_add(self.apply_episodes, rows, show_name)

    def apply_episodes(self, rows, show_name):
        if self.dead:
            return False
        self.episode_rows = rows
        if not rows:
            self.episode_status.set_text(
                "No episode list came back for %s." % show_name)
            self.split_text_changed()
            return False

        # long runners (Bleach) are filed by year-seasons and restart numbering
        # every year, so absolute numbering is the correct style there
        year_seasons = all(
            isinstance(row.get("season"), int) and row["season"] > 1900
            for row in rows if row.get("season") is not None)
        self.detected_style = (episode_names.STYLE_ABSOLUTE if year_seasons
                               else episode_names.STYLE_SEASON)
        self.episode_status.set_text(
            "%s — %d episodes. Set the first episode on this disc."
            % (show_name, len(rows)))
        self.apply_auto_start()
        self.suggest_episode_count()
        self.split_text_changed()
        return False

    def current_disc_label(self):
        if not self.source:
            return ""
        try:
            return self.disc_label(self.source)
        except Exception:
            return ""

    def remember_episode_progress(self, count):
        if not self.episode_show or count <= 0:
            return
        start = int(self.episode_start.get_value())
        self.state["episode_progress"] = {
            "show": self.episode_show,
            "disc": self.current_disc_label(),
            "next": start + count,
            "count": count,
        }
        save_state(self.state)

    def open_episode_list(self, button=None):
        if not self.episode_rows:
            self.episode_status.set_text("Look a show up first.")
            return
        popover = EpisodeListPopover(
            self.episode_show, self.episode_rows, self.name_style_key(),
            self.selected_season(), self.pick_start_episode)
        popover.set_parent(button or self.episode_list_button)
        self.episode_dialog = popover
        popover.popup()

    def pick_start_episode(self, number):
        self.set_start_episode(number)
        self.start_is_manual = True
        self.split_text_changed()

    def suggest_episode_count(self):
        """Work out how many episodes the disc holds, from the disc itself."""
        episodes = [title for title in self.titles if 900 <= title.duration <= 5400]
        longs = [title for title in self.titles if title.duration > 900]

        if len(episodes) >= 2:
            self.episode_parts.set_value(min(20, len(episodes)))
            self.episode_status.set_text(
                "%d episode-length titles on this disc — so %d episodes."
                % (len(episodes), len(episodes)))
            return

        if len(longs) != 1:
            return
        title = longs[0]

        # one long title: the chapter marks tell us where the episodes break
        count = ripper.best_episode_count(title)
        if count:
            self.episode_parts.set_value(count)
            cuts = [ripper.fmt_hms(title.chapter_starts[index])
                    for index in range(1, len(title.chapter_starts))
                    if any(abs(title.chapter_starts[index]
                               - title.duration * step / count) <= 45
                           for step in range(1, count))]
            self.episode_status.set_text(
                "One title of %s, %d episodes — cuts fall at %s."
                % (ripper.fmt_hms(title.duration), count,
                   ", ".join(cuts[:6]) or "even points"))
            return

        runtime = int(self.episode_runtime or 0) * 60
        if runtime:
            count = max(1, min(12, int(round(title.duration / float(runtime)))))
            self.episode_parts.set_value(count)
            self.episode_status.set_text(
                "Roughly %d episode%s on %s — worth checking before you start."
                % (count, "" if count == 1 else "s", ripper.fmt_hms(title.duration)))

    def episodes_per_disc(self):
        """How many episodes a disc of this show holds, for label maths."""
        long_titles = [title for title in self.titles if title.duration >= 900]
        if long_titles:
            return len(long_titles)
        progress = self.state.get("episode_progress") or {}
        if progress.get("count"):
            return int(progress["count"])
        return None

    def apply_auto_start(self):
        """Read the disc label ("BLEACH_DISC_03") and work out the episode."""
        if not self.episode_rows:
            return
        if self.start_is_manual:
            return              # he has told us where this disc starts
        disc = episode_names.disc_number(self.current_disc_label())
        per_disc = self.episodes_per_disc()
        if disc and per_disc and per_disc > 1:
            start = (disc - 1) * per_disc + 1
            self.set_start_episode(start)
            self.episode_status.set_text(
                "%s — disc %d of the set, so episodes %d-%d."
                % (self.episode_show, disc, start, start + per_disc - 1))
            return
        self.resume_episode_start()

    def resume_episode_start(self):
        """Pick up where the last disc of this show finished, if it was a different one."""
        progress = self.state.get("episode_progress") or {}
        if not progress or progress.get("show") != self.episode_show:
            return
        if progress.get("disc") == self.current_disc_label():
            return              # same disc: leave his number alone
        next_episode = int(progress.get("next") or 0)
        if next_episode > 0:
            self.set_start_episode(next_episode)
            self.episode_status.set_text(
                "%s — %d episodes. Carrying on from episode %d (last disc ended "
                "there)." % (self.episode_show, len(self.episode_rows or []),
                             next_episode))

    def episode_labels(self, count):
        """Names for `count` titles, from the looked-up list (or [])."""
        if not self.episode_rows:
            return []
        style = self.name_style_key()
        rows = episode_names.pick(self.episode_rows, self.selected_season(),
                                  int(self.episode_start.get_value()),
                                  count, style)
        show = ripper.safe_filename(self.episode_show or "Show", "Show")
        return [episode_names.label(show, row, style, self.selected_season())
                for row in rows]

    def pick_output_folder(self):
        dialog = Gtk.FileDialog()
        dialog.set_title("Where should the rips go?")
        current = self.output_entry.get_text().strip() or ripper.DEFAULT_OUTPUT_DIR
        try:
            os.makedirs(current, exist_ok=True)
            dialog.set_initial_folder(Gio.File.new_for_path(current))
        except OSError:
            pass

        def done(chooser, result):
            try:
                folder = chooser.select_folder_finish(result)
            except GLib.Error:
                return
            if folder is not None and folder.get_path():
                self.output_entry.set_text(folder.get_path())
                self.state["output_dir"] = folder.get_path()
                save_state(self.state)

        dialog.select_folder(self, None, done)

    # ---------------------------------------------------------------- queue building
    def add_to_queue(self, auto_start=True):
        titles = self.checked_titles()
        if not titles:
            self.flash_status("Tick a title to rip.")
            return 0
        mode = self.current_mode()
        base = ripper.safe_filename(self.name_entry.get_text().strip(), "Disc")
        out_dir = self.output_entry.get_text().strip() or ripper.DEFAULT_OUTPUT_DIR
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as error:
            self.flash_status("Cannot create %s: %s" % (out_dir, error))
            return

        preset = self.current_preset()
        ext = preset["ext"]
        split_text = self.split_text_value()
        numbering = self.numbering.get_active()
        copy_mode = self.use_lossless() and ripper.is_video_file(self.source)
        if copy_mode:
            ext = os.path.splitext(self.source)[1].lstrip(".").lower() or "mkv"
        added = 0
        ordered_titles = sorted(titles, key=lambda item: item.number)
        if mode == "whole":
            expected = len(ordered_titles)
        else:
            expected = sum(len(ripper.segment_jobs(title, mode, split_text, base,
                                                   split_text))
                           for title in titles)
        episode_labels = self.episode_labels(expected)
        pending_episode_names = list(episode_labels)
        episode_by_title = {entry.number: episode_labels[position]
                            for position, entry in enumerate(ordered_titles)
                            if position < len(episode_labels)}
        for title in titles:
            jobs = ripper.segment_jobs(title, mode, split_text, base, split_text)
            for job_spec in jobs:
                label = job_spec["label"]
                if mode == "whole":
                    if title.number in episode_by_title:
                        label = episode_by_title[title.number]
                    elif len(titles) > 1:
                        if numbering:
                            label = "%s - %02d" % (base, added + 1)
                        else:
                            label = "%s - %s" % (
                                base, title.name or ("Title %d" % title.number))
                elif pending_episode_names:
                    label = pending_episode_names.pop(0)
                elif len(titles) > 1:
                    rest = label[len(base):].strip(" -") if label.startswith(base) else label
                    if numbering:
                        label = "%s - T%02d - %s" % (base, title.number, rest)
                    else:
                        label = "%s - %s - %s" % (
                            base, title.name or ("Title %d" % title.number), rest)
                path = os.path.join(out_dir, ripper.safe_filename(label, "Rip") + "." + ext)
                path = self.unique_path(path)
                start = job_spec.get("start")
                stop = job_spec.get("stop")
                chapters = job_spec.get("chapters")
                if copy_mode:
                    if chapters:
                        span = ripper.chapter_span(title, chapters)
                        if span is None:
                            continue
                        start, stop = span
                    if start is None:
                        continue
                    if stop is None:
                        stop = title.duration
                    chapters = None
                job = Job(self.source, title, label, path, preset["key"],
                          self.current_audio(), self.current_subs(),
                          start, stop, chapters,
                          method="copy" if copy_mode else "encode",
                          audio_lang=self.current_audio_lang(),
                          markers=self.markers.get_active(),
                          resolution=self.current_resolution(),
                          size=ripper.target_size(title, self.current_resolution()),
                          anime=self.anime_check.get_active(),
                          denoise=self.current_denoise(),
                          deblock=self.current_deblock(),
                          deband=self.current_deband(),
                          transcript=self.current_transcript())
                self.jobs.append(job)
                added += 1
        if episode_by_title:
            self.remember_episode_progress(len(episode_by_title))
        self.save_split()
        self.state.update({"output_dir": out_dir, "preset": preset["key"],
                           "audio": self.current_audio(), "subs": self.current_subs(),
                           "audio_lang": self.current_audio_lang(),
                           "resolution": self.current_resolution(),
                           "anime": self.anime_check.get_active(),
                           "denoise": self.current_denoise(),
                           "deblock": self.current_deblock(),
                           "deband": self.current_deband(),
                           "transcript": self.current_transcript(),
                           "markers": self.markers.get_active(),
                           "episode_show": self.episode_show,
                           "episode_style": self.name_style_key(),
                           "episode_season": self.selected_season(),
                           "episode_start": int(self.episode_start.get_value())})
        save_state(self.state)
        self.rebuild_queue()
        if added:
            self.append_log("queued %d rip%s" % (added, "" if added == 1 else "s"))
        else:
            self.flash_status(
                "Nothing queued — check the split settings for that title.")
        if auto_start and added and not self.running:
            self.start_queue()
        return added

    @staticmethod
    def unique_path(path):
        if not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(path)
        counter = 2
        while os.path.exists("%s (%d)%s" % (stem, counter, ext)):
            counter += 1
        return "%s (%d)%s" % (stem, counter, ext)

    def rebuild_queue(self):
        self.close_job_menu()
        while True:
            child = self.queue_list.get_first_child()
            if child is None:
                break
            self.queue_list.remove(child)
        self.rows = []
        for job in self.jobs:
            row = Gtk.ListBoxRow()
            row.job = job
            row.add_css_class("job-row")
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

            tick = Gtk.CheckButton()
            tick.add_css_class("job-check")
            tick.set_active(bool(getattr(job, "checked", False)))
            tick.connect("toggled",
                         lambda button, target=job: setattr(
                             target, "checked", button.get_active()))
            line.append(tick)
            row.tick = tick

            state_label = Gtk.Label(label="", width_chars=9, xalign=0.0)
            state_label.add_css_class("job-state")
            state_label.add_css_class(job.status)
            state_label.set_text(job.status.upper())
            line.append(state_label)

            name = Gtk.Label(label=job.label, xalign=0.0)
            name.add_css_class("job-name")
            name.set_hexpand(True)
            name.set_width_chars(34)
            name.set_max_width_chars(60)
            name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            name.set_tooltip_text(job.path)
            line.append(name)

            # a per-row progress bar (C0D3D, 2026-11-12: "can u put a loading bar
            # next to each queue item") so the running job's place in its own file
            # is visible without reading the percentage text
            bar = Gtk.ProgressBar()
            bar.add_css_class("job-bar")
            bar.set_valign(Gtk.Align.CENTER)
            bar.set_hexpand(False)
            bar.set_halign(Gtk.Align.FILL)
            bar.set_size_request(120, -1)
            bar.set_fraction(1.0 if job.status == "done" else
                             (job.fraction if job.status == "running" else 0.0))
            if job.status in ("queued",):
                bar.add_css_class("job-bar-idle")
            elif job.status in ("failed", "cancelled"):
                bar.add_css_class("job-bar-failed")
            # a fixed-width slot keeps every row's bar in the same place, whatever
            # the label lengths are (C0D3D, 2026-11-12: "line up the loading bars")
            bar_slot = Gtk.Box()
            bar_slot.set_size_request(120, -1)
            bar_slot.set_valign(Gtk.Align.CENTER)
            bar_slot.append(bar)
            line.append(bar_slot)
            row.bar = bar

            mode = Gtk.Label(label=job.mode_text(), xalign=0.0, width_chars=22)
            mode.add_css_class("job-mode")
            # a long span (or a "copy 00:00:00 → 00:23:20") must shrink, not
            # spill past the card edge and get chopped mid-glyph on a narrow screen
            mode.set_ellipsize(Pango.EllipsizeMode.END)
            line.append(mode)

            detail = Gtk.Label(label=self.job_detail_text(job), xalign=1.0, width_chars=26)
            detail.add_css_class("job-detail")
            detail.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            line.append(detail)
            row.detail_label = detail

            row.set_child(line)
            # right-click a row for a per-job action (C0D3D, 2026-11-12)
            right = Gtk.GestureClick()
            right.set_button(Gdk.BUTTON_SECONDARY)
            right.connect("pressed",
                          lambda gesture, n, x, y, target=row:
                          self.open_job_menu(target))
            row.add_controller(right)
            self.queue_list.append(row)
            self.rows.append(row)
        queued = sum(1 for job in self.jobs if job.status == "queued")
        done = sum(1 for job in self.jobs if job.status == "done")
        total = sum(job.size for job in self.jobs if job.status == "done")
        if not self.jobs:
            self.queue_summary.set_text("Nothing queued.")
        else:
            self.queue_summary.set_text(
                "%d job%s · %d done · %d waiting · %s written"
                % (len(self.jobs), "" if len(self.jobs) == 1 else "s",
                   done, queued, ripper.fmt_bytes(total)))
        self.update_counter()
        self.refresh_start()

    def title_ticked(self):
        """A title was ticked: refresh the chapter list, preview and Start state."""
        # The tick handler has always called this, but the method never existed -
        # the AttributeError was swallowed by GTK, so nothing refreshed.
        self.split_text_changed()
        self.refresh_start()

    def refresh_start(self):
        """Start is live if jobs are waiting *or* the current settings could be queued."""
        if not hasattr(self, "start_button"):
            return
        ready = any(job.status == "queued" for job in self.jobs)
        if not ready:
            ready = getattr(self, "planned_jobs", 0) > 0
        self.start_button.set_sensitive(bool(ready) and not self.running)

    def job_detail_text(self, job):
        if job.status == "running":
            return "%.0f%% · %s" % (job.fraction * 100, job.detail or "starting")
        if job.status == "done":
            return ripper.fmt_bytes(job.size) if job.size else "finished"
        if job.status in ("failed", "cancelled"):
            return job.detail or job.status
        # queued: the row's label already carries the name, so no filename here
        # (C0D3D, 2026-11-12: "why is the names shown on the left side and the right")
        return ""

    def on_job_selected(self, _listbox, row):
        self.selected_job = row.job if row is not None else None

    def remove_selected(self):
        """Delete the ticked jobs; with none ticked, the highlighted one."""
        targets = self.queue_targets()
        if not targets:
            return
        if any(job.status == "running" for job in targets):
            self.flash_status("That one is encoding right now — stop the queue first.")
            return
        self.jobs = [job for job in self.jobs if job not in targets]
        self.selected_job = None
        self.rebuild_queue()

    def remove_all(self):
        if self.running:
            self.flash_status("Stop the rip before clearing the whole queue.")
            return
        if not self.jobs:
            return
        self.jobs = []
        self.selected_job = None
        self.rebuild_queue()
        self.append_log_line("queue cleared")

    def clear_finished(self):
        self.jobs = [job for job in self.jobs
                     if job.status not in ("done", "failed", "cancelled")]
        self.rebuild_queue()

    def queue_targets(self):
        """The jobs a queue action acts on: ticked first, else the highlighted row."""
        targets = [job for job in self.jobs if getattr(job, "checked", False)]
        if not targets and self.selected_job is not None:
            targets = [self.selected_job]
        return targets

    def retry_transcript(self, job=None):
        """Re-run just the speech-to-text pass on a file that is already ripped.

        Saves re-encoding an episode because the subtitle pass fell over.
        """
        if job is None:
            finished = [item for item in self.queue_targets()
                        if item.status in ("done", "failed", "cancelled")]
            if not finished:
                self.flash_status(
                    "Tick the finished rip whose transcript you want redone.")
                return
            job = finished[0]
        if self.running:
            self.flash_status("A rip is running — let it finish or stop it first.")
            return
        if job.status == "running":
            self.flash_status("That one is encoding right now.")
            return
        if not ripper.asr_available():
            self.flash_status("The transcribe venv is missing — can't run the pass.")
            return
        if not os.path.exists(job.path):
            self.flash_status("The file is gone: %s" % job.path)
            return
        if job.transcript in (None, "", "off"):
            job.transcript = "best"     # asking for a retry is an explicit ask
        ripper.log("transcript retry requested for %s" % job.path)
        self.cancel_requested = False
        self.running = True
        self.current_job = job
        self.stop_button.set_sensitive(True)
        self.start_button.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        job.status = "running"
        job.fraction = 0.0
        job.detail = "transcribing"
        self.rebuild_queue()
        threading.Thread(target=self.transcript_worker, args=(job,),
                         daemon=True).start()

    def transcript_worker(self, job):
        GLib.idle_add(self.progress_label.set_text,
                      "%s — transcribing the dub" % job.label)
        result = self.run_transcript_pass(job)
        self.current_job = None
        GLib.idle_add(self.job_finished, job, result)
        GLib.idle_add(self.queue_finished)

    def open_job_menu(self, row):
        """Right-click a queue row: redo that file's transcript."""
        self.close_job_menu()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("job-menu")
        retry = icon_button("Retry transcript", "view-refresh-symbolic")
        retry.set_halign(Gtk.Align.FILL)
        retry.add_css_class("compact-button")
        retry.set_tooltip_text("Re-run the transcribe pass on this file")
        retry.set_sensitive(row.job.status in ("done", "failed", "cancelled"))
        retry.connect("clicked", lambda *_: self.retry_from_menu(row.job))
        box.append(retry)
        pop = Gtk.Popover()
        pop.set_child(box)
        pop.set_has_arrow(False)
        pop.set_parent(row)
        pop.popup()
        self.job_menu = pop
        return False

    def retry_from_menu(self, job):
        self.close_job_menu()
        self.retry_transcript(job)

    def close_job_menu(self):
        pop = getattr(self, "job_menu", None)
        self.job_menu = None
        if pop is None:
            return
        try:
            pop.popdown()
        except Exception:
            pass
        try:
            pop.unparent()
        except Exception:
            pass

    # ---------------------------------------------------------------- running
    def start_queue(self):
        if self.running:
            return
        if not any(job.status == "queued" for job in self.jobs):
            # nothing staged yet: queue whatever is set up on screen and go
            if not self.add_to_queue(auto_start=False):
                return
        self.cancel_requested = False
        self.running = True
        self.stop_button.set_sensitive(True)
        self.start_button.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        threading.Thread(target=self.queue_worker, daemon=True).start()

    def stop_queue(self):
        self.cancel_requested = True
        process = self.current_proc
        if process is not None and process.poll() is None:
            self.append_log("stopping encoder…")
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

    def queue_worker(self):
        while True:
            if self.cancel_requested:
                break
            job = next((item for item in self.jobs if item.status == "queued"), None)
            if job is None:
                break
            self.current_job = job
            GLib.idle_add(self.job_started, job)
            result = self.run_job(job)
            self.current_job = None
            GLib.idle_add(self.job_finished, job, result)
            if self.cancel_requested:
                break
        GLib.idle_add(self.queue_finished)

    def run_job(self, job):
        command = job.command()
        ripper.log("encode start: %s" % " ".join(command))
        GLib.idle_add(self.append_log_line, "$ " + " ".join(command))
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True,
                                       bufsize=1, start_new_session=True)
        except OSError as error:
            job.detail = str(error)
            return "failed"
        self.current_proc = process

        def handle_json(label, payload):
            if label == "Progress":
                values = ripper.progress_values(payload)
                if values["state"] == "working":
                    GLib.idle_add(self.job_progress, job, values)
                elif values["state"] == "scanning":
                    GLib.idle_add(self.job_progress, job,
                                  {"fraction": 0.0, "eta": 0, "rate": 0,
                                   "scanning": values})

        parser = ripper.JsonStreamParser(handle_json)
        span = max(0.5, job.span())

        def read_stdout():
            if job.method == "copy":
                for line in process.stdout:
                    seconds = ripper.parse_copy_progress(line)
                    if seconds is None:
                        continue
                    GLib.idle_add(self.job_progress, job, {
                        "fraction": min(1.0, seconds / span), "copy": True})
                return
            for line in process.stdout:
                parser.feed(line)

        out_thread = threading.Thread(target=read_stdout, daemon=True)
        out_thread.start()
        for line in process.stderr:
            text = line.rstrip()
            if text:
                GLib.idle_add(self.append_log_line, text)
        process.wait()
        out_thread.join(timeout=3)
        self.current_proc = None

        if self.cancel_requested:
            job.detail = "stopped"
            return "cancelled"
        if process.returncode == 0 and job.deband not in (None, "", "off"):
            if self.run_deband_pass(job) != "done":
                job.detail = "deband pass failed"
                return "failed"
        if (process.returncode == 0
                and job.transcript not in (None, "", "off")):
            if self.run_transcript_pass(job) != "done":
                job.detail = "transcript pass failed"
                return "failed"
        if process.returncode != 0:
            job.detail = "exit %s" % process.returncode
            return "failed"
        try:
            job.size = os.path.getsize(job.path)
        except OSError:
            job.size = 0
        return "done"

    def update_counter(self):
        if not hasattr(self, "counter_label") or not self.jobs:
            return
        done = sum(1 for item in self.jobs if item.status == "done")
        total = len(self.jobs)
        running = 1 if any(item.status == "running" for item in self.jobs) else 0
        position = min(total, done + running)
        self.counter_label.set_text("%d / %d files" % (position, total))

    def run_deband_pass(self, job):
        """ffmpeg deband over the finished file, then swap it into place."""
        # Hidden temp, so the output folder never shows a second copy of the
        # episode while the second pass is still writing it (C0D3D, 2026-11-10).
        temporary = os.path.join(os.path.dirname(job.path),
                                 "." + os.path.basename(job.path) + ".deband.mkv")
        command = ripper.deband_command(job.path, temporary, job.deband)
        if not command:
            return "done"
        ripper.log("deband start: %s" % " ".join(command))
        GLib.idle_add(self.progress_label.set_text,
                      "%s — debanding (second pass)" % job.label)
        try:
            run = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1,
                                   start_new_session=True)
        except OSError as error:
            ripper.log("deband failed to start: %s" % error)
            return "failed"
        self.current_proc = run
        span = max(0.5, job.span())
        for line in run.stdout:
            seconds = ripper.parse_copy_progress(line)
            if seconds is None:
                continue
            GLib.idle_add(self.job_progress, job, {
                "fraction": min(1.0, seconds / span), "copy": True})
        for line in run.stderr:
            text = line.rstrip()
            if text and ("error" in text.lower() or "Error" in text):
                GLib.idle_add(self.append_log_line, text)
        run.wait()
        self.current_proc = None
        if run.returncode != 0:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            return "failed"
        try:
            os.replace(temporary, job.path)
        except OSError as error:
            ripper.log("deband swap failed: %s" % error)
            return "failed"
        return "done"

    def run_transcript_pass(self, job):
        """Listen to the dub in the finished file and write matching subs."""
        if not ripper.asr_available():
            ripper.log("transcript pass unavailable: ASR venv missing")
            return "failed"
        mode = ripper.TRANSCRIPT_BY_KEY.get(job.transcript) or {}
        model = mode.get("model")
        if not model:
            return "done"
        folder = os.path.dirname(job.path)
        base = os.path.basename(job.path)
        srt = os.path.join(folder, "." + base + ".srt")
        temporary = os.path.join(folder, "." + base + ".transcript.mkv")
        command = ripper.transcript_command(job.path, srt, model)
        ripper.log("transcript start: %s" % " ".join(command))
        try:
            run = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, bufsize=1,
                                   start_new_session=True)
        except OSError as error:
            ripper.log("transcript failed to start: %s" % error)
            return "failed"
        self.current_proc = run
        for line in run.stdout:
            percent = ripper.parse_transcript_progress(line)
            if percent is not None:
                GLib.idle_add(self.progress_label.set_text,
                              "%s — transcribing the dub %d%%"
                              % (job.label, percent))
                GLib.idle_add(self.job_progress, job,
                              {"fraction": percent / 100.0, "transcript": True})
                continue
            text = line.rstrip()
            if text:
                ripper.log("transcript: %s" % text)
        for line in run.stderr:
            text = line.rstrip()
            if text:
                ripper.log("transcript: %s" % text)
        run.wait()
        self.current_proc = None
        if self.cancel_requested:
            for path in (srt, temporary):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            return "cancelled"
        if run.returncode != 0 or not os.path.exists(srt):
            for path in (srt, temporary):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            return "failed"
        GLib.idle_add(self.progress_label.set_text,
                      "%s — adding the transcript" % job.label)
        mux = ripper.mux_transcript_command(job.path, srt, temporary,
                                           keep_disc=job.sub_key != "none")
        result = subprocess.run(mux, capture_output=True, text=True)
        if result.returncode != 0:
            ripper.log("transcript mux failed: %s" % result.stderr[-400:])
            for path in (srt, temporary):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            return "failed"
        try:
            os.replace(temporary, job.path)
        except OSError as error:
            ripper.log("transcript swap failed: %s" % error)
            return "failed"
        try:
            os.unlink(srt)
        except OSError:
            pass
        ripper.log("transcript written for %s" % base)
        return "done"

    def job_started(self, job):
        if self.dead:
            return False
        job.status = "running"
        job.fraction = 0.0
        job.detail = ""
        self.rebuild_queue()
        self.update_counter()
        self.progress.set_fraction(0.0)
        self.progress_label.set_text("encoding %s" % job.label)
        return False

    def job_progress(self, job, values):
        if self.dead:
            return False
        if "scanning" in values:
            scanning = values["scanning"]
            self.progress_label.set_text("scanning title %s of %s"
                                         % (scanning.get("title") or "?",
                                            scanning.get("total") or "?"))
            return False
        fraction = values.get("fraction", 0.0)
        job.fraction = fraction
        self.progress.set_fraction(fraction)
        if values.get("copy"):
            job.detail = "copying"
            self.progress_label.set_text("%s — %.0f%% (lossless copy)"
                                         % (job.label, fraction * 100))
        elif values.get("transcript"):
            job.detail = "transcribing"
            self.progress_label.set_text("%s — transcribing the dub %.0f%%"
                                         % (job.label, fraction * 100))
        else:
            eta = ripper.fmt_hms(values.get("eta") or 0)
            rate = values.get("rate") or 0
            job.detail = "ETA %s · %.0f fps" % (eta, rate)
            self.progress_label.set_text(
                "%s — %.0f%% · ETA %s · %.0f fps"
                % (job.label, fraction * 100, eta, rate))
        for row in self.rows:
            if row.job is job:
                if hasattr(row, "detail_label"):
                    row.detail_label.set_text(self.job_detail_text(job))
                if hasattr(row, "bar"):
                    row.bar.set_fraction(fraction)
        return False

    def job_finished(self, job, result):
        if self.dead:
            return False
        job.status = result
        self.progress.set_fraction(1.0 if result == "done" else 0.0)
        self.progress_label.set_text(
            ("done: %s (%s)" % (os.path.basename(job.path), ripper.fmt_bytes(job.size)))
            if result == "done" else "%s: %s" % (result, job.label))
        self.rebuild_queue()
        self.update_counter()
        if result == "done":
            self.append_log("finished %s (%s)" % (job.path, ripper.fmt_bytes(job.size)))
        return False

    def queue_finished(self):
        if self.dead:
            return False
        self.running = False
        self.current_job = None
        self.update_counter()
        self.spinner.stop()
        self.spinner.set_visible(False)
        self.stop_button.set_sensitive(False)
        self.rebuild_queue()
        if self.cancel_requested:
            self.progress_label.set_text("stopped")
            self.append_log("queue stopped")
        else:
            self.progress_label.set_text("idle")
            self.append_log("queue finished")
        return False

    # ---------------------------------------------------------------- log
    def append_log_line(self, text):
        """The window has no log pane any more; everything still lands in the file."""
        if self.dead:
            return False
        text = str(text).rstrip()
        if text:
            ripper.log(text)
        return False

    def append_log(self, text):
        self.append_log_line(text)

    def flash_status(self, text):
        self.source_status.set_text(text)
        self.append_log_line(text)

    def open_folder(self):
        path = self.output_entry.get_text().strip() or ripper.DEFAULT_OUTPUT_DIR
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as error:
            self.flash_status("Cannot create %s: %s" % (path, error))
            return
        try:
            Gio.AppInfo.launch_default_for_uri("file://" + path, None)
            return
        except GLib.Error as error:
            ripper.log("launch_default_for_uri failed: %s" % error.message)
        # the app runs with its own XDG_CONFIG_HOME, so fall back to a launcher
        # that sees the real one rather than a broken mimeapps lookup
        environment = dict(os.environ)
        environment["XDG_CONFIG_HOME"] = os.path.join(
            os.path.expanduser("~"), ".config")
        for launcher in (["xdg-open", path],
                         ["/home/jimmy/bin/strata-crimson", path]):
            try:
                subprocess.Popen(launcher, env=environment,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                return
            except OSError:
                continue
        self.flash_status("No file manager could be opened for %s" % path)

    def do_close_request(self):
        self.save_split()
        if self.running:
            self.stop_queue()
        self.dead = True
        return False


class RipperApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = RipperWindow(self)
        self.window.present()


def css_path(name):
    folder = os.path.join(os.environ.get("XDG_CONFIG_HOME", ""), "gtk-4.0")
    path = os.path.join(folder, THEME_FILES.get(name, "gtk.css"))
    if os.path.exists(path):
        return path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "gtk.css")


def apply_theme(name):
    """Swap the whole stylesheet — Matrix, or one of the plain themes."""
    global _theme_provider, _current_theme
    _current_theme = name
    try:
        refresh_icon_tints()
    except Exception:
        pass
    display = Gdk.Display.get_default()
    if display is None:
        return
    if _theme_provider is not None:
        Gtk.StyleContext.remove_provider_for_display(display, _theme_provider)
        _theme_provider = None
    path = css_path(name)
    if not os.path.exists(path):
        return
    provider = Gtk.CssProvider()
    provider.load_from_path(path)
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    _theme_provider = provider


def load_css():
    apply_theme("matrix")


def main():
    use_matrix_icons()
    load_css()
    return RipperApp().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
