"""GTK views for the couch lobby: player panels, name keyboard and backdrop.

Views are built once and updated in place. Rebuilding every widget on each
button press made panels flash, and a panel larger than its screen region makes
GTK and the KWin layout script fight over the window size every second. Every
view must fit the smallest region a valid configuration allows (a 640x360
quadrant); tests/test_picker_gui.py checks each layout. GTK 3.24 doubles the
height of an unellipsized label that uses CSS letter-spacing, so only
ellipsized labels use it.
"""

import hashlib

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, Pango

# Grass, diamond, gold, amethyst.
ACCENTS = {1: "#62d46f", 2: "#4fb0ff", 3: "#ffb238", 4: "#b98aff"}
AVATARS = [
    "#3e8e4c",
    "#2f6fa8",
    "#b0762a",
    "#7a52b3",
    "#a9493f",
    "#2b8a86",
    "#8d6b3a",
    "#56697a",
]
NEW, SIT_OUT = "＋ New profile", "Sit out"
NAME_LIMIT = 16
KEY_ROWS = [
    [(c, 1) for c in "1234567890"],
    [(c, 1) for c in "QWERTYUIOP"],
    [(c, 1) for c in "ASDFGHJKL_"],
    [("shift", 1)] + [(c, 1) for c in "ZXCVBNM"] + [("erase", 2)],
    [("cancel", 5), ("done", 5)],
]
KEY_LABELS = {"shift": "⇧", "erase": "⌫", "cancel": "✕  Cancel", "done": "✓  Done"}

CSS = """
window.couch { background-color: #0d1417; color: #edf3f1; font-size: 18px;
  font-family: "Adwaita Sans", "Inter", "Noto Sans", "Cantarell", sans-serif; }
window.seat { background-image: linear-gradient(180deg, #16252c 0%, #0d1417 100%); }
window.lobby { background-image: linear-gradient(160deg, #15303a 0%, #0d1719 55%, #0a0f11 100%); }

.accentbar { min-height: 6px; }
.badge { border-radius: 8px; padding: 1px 10px; font-weight: 800; font-size: 15px; color: #0d1417; }
.seat-title { font-weight: 800; font-size: 20px; }
.state { color: #8fa4aa; font-size: 15px; }
.prompt { color: #c9d6d6; font-size: 17px; }
.more { color: #6f868c; font-size: 13px; letter-spacing: 1px; }

button { background-image: none; box-shadow: none; text-shadow: none; -gtk-icon-shadow: none;
  outline-width: 0; color: #edf3f1; }
button.row { background-color: alpha(#ffffff, 0.045); border: 2px solid transparent;
  border-radius: 12px; padding: 4px 12px; min-height: 40px; }
button.row:hover { background-color: alpha(#ffffff, 0.08); }
.avatar { border-radius: 8px; min-width: 34px; min-height: 34px; font-weight: 800;
  font-size: 17px; color: #ffffff; }
.avatar.new { background-color: alpha(#ffffff, 0.10); color: #cfe0dd; }
.avatar.away { background-color: alpha(#ffffff, 0.06); color: #8fa4aa; font-size: 14px; }
.row-name { font-size: 19px; font-weight: 600; }
.row.away .row-name { color: #a9b9bd; font-weight: 500; }
.tag { font-size: 11px; font-weight: 800; color: #0d1417;
  border-radius: 6px; padding: 1px 7px; background-color: #cfe0dd; }

.field { background-color: #081012; border: 2px solid alpha(#ffffff, 0.12);
  border-radius: 12px; padding: 4px 16px; min-height: 46px; }
.field-text { font-size: 26px; font-weight: 700; }
.field-text.empty { color: #5d7177; font-weight: 500; }
.caret { font-size: 26px; font-weight: 300; }
.count { color: #6f868c; font-size: 13px; }

button.key { background-color: alpha(#ffffff, 0.06); border: 2px solid alpha(#ffffff, 0.07);
  border-radius: 9px; padding: 0; min-height: 40px; min-width: 30px;
  font-size: 19px; font-weight: 700; }
button.key:hover { background-color: alpha(#ffffff, 0.11); }
button.key.wide { font-size: 15px; }
button.key.done { background-color: alpha(#62d46f, 0.16); }
button.key.sel { color: #0d1417; }

.chip { border-radius: 999px; min-width: 22px; min-height: 22px; padding: 0 6px;
  font-size: 12px; font-weight: 800; color: #0d1417; background-color: #cfe0dd; }
.chip.a { background-color: #5dbb46; color: #ffffff; }
.chip.b { background-color: #e0483b; color: #ffffff; }
.chip.x { background-color: #3d8fe0; color: #ffffff; }
.chip.y { background-color: #f0c02c; }
.hint { color: #9fb2b6; font-size: 14px; }

.error { color: #ffd2c7; background-color: alpha(#e0483b, 0.22); border-radius: 10px;
  padding: 4px 12px; font-size: 15px; }
.avatar.big { min-width: 84px; min-height: 84px; border-radius: 16px; font-size: 40px; }
.status-name { font-size: 28px; font-weight: 800; }
.status-text { font-size: 19px; color: #c9d6d6; }
.status-detail { font-size: 15px; color: #8fa4aa; }
spinner { min-width: 28px; min-height: 28px; }
.warn-icon { font-size: 54px; color: #ffb238; }

.full .badge { font-size: 22px; padding: 2px 14px; border-radius: 10px; }
.full .seat-title { font-size: 30px; }
.full .state { font-size: 20px; }
.full .prompt { font-size: 24px; }
.full button.row { min-height: 62px; border-radius: 16px; padding: 6px 18px; }
.full .avatar { min-width: 50px; min-height: 50px; font-size: 24px; border-radius: 11px; }
.full .avatar.away { font-size: 19px; }
.full .row-name { font-size: 27px; }
.full .tag { font-size: 14px; padding: 2px 9px; }
.full .field { min-height: 72px; border-radius: 16px; padding: 6px 24px; }
.full .field-text, .full .caret { font-size: 40px; }
.full .count { font-size: 18px; }
.full button.key { min-height: 70px; font-size: 30px; border-radius: 13px; }
.full button.key.wide { font-size: 23px; }
.full .chip { min-width: 30px; min-height: 30px; font-size: 16px; padding: 0 9px; }
.full .hint { font-size: 19px; }
.full .error { font-size: 21px; padding: 6px 16px; }
.full .avatar.big { min-width: 128px; min-height: 128px; font-size: 60px; border-radius: 22px; }
.full .status-name { font-size: 42px; }
.full .status-text { font-size: 27px; }
.full .status-detail { font-size: 20px; }

.title { font-size: 92px; font-weight: 900; color: #f3f7f2;
  text-shadow: 0 6px 0 #2c5a2f, 0 10px 18px alpha(#000000, 0.55); }
.lobby-sub { font-size: 26px; color: #9fd8a5; font-weight: 600; letter-spacing: 3px; }
.card { background-color: alpha(#ffffff, 0.045); border-radius: 16px; min-width: 250px;
  min-height: 118px; }
.card.taken { background-color: alpha(#ffffff, 0.085); }
.card-name { font-size: 22px; font-weight: 800; }
.card-state { font-size: 15px; color: #8fa4aa; }
.card.open .card-name { color: #6f868c; }
.lobby-note { color: #8fa4aa; font-size: 17px; }
button.quit { background-color: alpha(#ffffff, 0.07); border: 2px solid alpha(#ffffff, 0.12);
  border-radius: 12px; padding: 8px 22px; font-size: 17px; font-weight: 700; }
button.quit:hover { background-color: alpha(#e0483b, 0.35); }
.corner .title { font-size: 54px; }
.corner .lobby-sub { font-size: 18px; }
.corner .card { min-width: 140px; min-height: 92px; }
.corner .card-name { font-size: 18px; }
.corner .card-state { font-size: 13px; }
.corner.tiny .title { font-size: 40px; }
.corner.tiny .lobby-sub { font-size: 13px; }
.corner.tiny .card { min-height: 64px; }
.corner.tiny .card-name { font-size: 15px; }
.corner.tiny .card-state { font-size: 11px; }

.tiny .accentbar { min-height: 4px; }
.tiny .badge { font-size: 11px; padding: 0 7px; border-radius: 6px; }
.tiny .seat-title { font-size: 14px; }
.tiny .state { font-size: 11px; }
.tiny .prompt { font-size: 13px; }
.tiny .more { font-size: 10px; }
.tiny button.row { min-height: 24px; padding: 1px 8px; border-radius: 8px; }
.tiny .avatar { min-width: 22px; min-height: 22px; font-size: 12px; border-radius: 5px; }
.tiny .avatar.away { font-size: 10px; }
.tiny .row-name { font-size: 14px; }
.tiny .tag { font-size: 9px; padding: 0 5px; }
.tiny .field { min-height: 28px; padding: 1px 10px; border-radius: 8px; }
.tiny .field-text, .tiny .caret { font-size: 18px; }
.tiny .count { font-size: 10px; }
.tiny button.key { min-height: 24px; min-width: 20px; font-size: 13px; border-radius: 6px; }
.tiny button.key.wide { font-size: 11px; }
.tiny .chip { min-width: 16px; min-height: 16px; font-size: 9px; padding: 0 4px; }
.tiny .hint { font-size: 11px; }
.tiny .error { font-size: 11px; padding: 2px 8px; }
.tiny .avatar.big { min-width: 52px; min-height: 52px; font-size: 26px; border-radius: 10px; }
.tiny .status-name { font-size: 19px; }
.tiny .status-text { font-size: 14px; }
.tiny .status-detail { font-size: 11px; }
.tiny spinner { min-width: 18px; min-height: 18px; }
.tiny .warn-icon { font-size: 34px; }
"""


def install_css():
    accents = "".join(
        f"""
.p{n} .accentbar, .p{n} .badge {{ background-color: {c}; }}
.p{n} button.row.sel {{ border-color: {c}; background-color: alpha({c}, 0.17); }}
.p{n} button.key.sel {{ background-color: {c}; border-color: {c}; }}
.p{n} button.key.on {{ border-color: {c}; color: {c}; }}
.p{n} .field.live {{ border-color: alpha({c}, 0.75); }}
.p{n} .caret, .p{n} spinner {{ color: {c}; }}
.p{n} .tag {{ background-color: {c}; }}
"""
        for n, c in ACCENTS.items()
    )
    avatars = "".join(
        f".avatar.c{i} {{ background-color: {c}; }}\n" for i, c in enumerate(AVATARS)
    )
    provider = Gtk.CssProvider()
    provider.load_from_data((CSS + accents + avatars).encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def text(widget, value):
    if widget.get_text() != value:
        widget.set_text(value)


def css_class(widget, name, on=True):
    context = widget.get_style_context()
    if on and not context.has_class(name):
        context.add_class(name)
    elif not on and context.has_class(name):
        context.remove_class(name)


def make_label(value="", *classes, xalign=0.5, ellipsize=True):
    label = Gtk.Label(label=value)
    label.set_xalign(xalign)
    if ellipsize:
        label.set_ellipsize(Pango.EllipsizeMode.END)
    for name in classes:
        label.get_style_context().add_class(name)
    return label


def avatar_color(name):
    return "c%d" % (hashlib.md5(name.lower().encode()).digest()[0] % len(AVATARS))


def set_avatar(label, name):
    for i in range(len(AVATARS)):
        css_class(label, f"c{i}", False)
    css_class(label, "new", name == NEW)
    css_class(label, "away", name == SIT_OUT)
    if name == NEW:
        text(label, "+")
    elif name == SIT_OUT:
        text(label, "Zz")
    else:
        text(label, (name[:1] or "?").upper())
        css_class(label, avatar_color(name))


class Hints(Gtk.Box):
    """Footer of controller glyphs; rebuilt only when the set of hints changes."""

    def __init__(self):
        super().__init__(spacing=16)
        self.set_halign(Gtk.Align.CENTER)
        self.current = None

    def show(self, items):
        items = tuple(items)
        if items == self.current:
            return
        self.current = items
        for child in self.get_children():
            self.remove(child)
        for glyph, words in items:
            pair = Gtk.Box(spacing=6)
            for part in glyph.split("+"):
                chip = make_label(
                    part.upper() if len(part) > 1 else part, "chip", ellipsize=False
                )
                if len(part) == 1:
                    css_class(chip, part.lower())
                chip.set_valign(Gtk.Align.CENTER)
                pair.pack_start(chip, False, False, 0)
            pair.pack_start(make_label(words, "hint"), False, True, 0)
            self.pack_start(pair, False, True, 0)
        self.show_all()


class NameKeyboard(Gtk.Grid):
    """Controller keyboard. A cursor moves over fixed buttons; nothing is rebuilt."""

    def __init__(self, on_click):
        super().__init__(column_spacing=6, row_spacing=6)
        self.set_column_homogeneous(True)
        self.set_row_homogeneous(True)
        self.keys = []
        self.row, self.index, self.column = 1, 0, 0
        for r, row in enumerate(KEY_ROWS):
            buttons, column = [], 0
            for i, (key, span) in enumerate(row):
                button = Gtk.Button(label=KEY_LABELS.get(key, key))
                button.set_can_focus(False)
                button.get_style_context().add_class("key")
                if span > 1:
                    button.get_style_context().add_class("wide")
                if key in ("cancel", "done"):
                    button.get_style_context().add_class(key)
                button.connect("clicked", lambda _b, r=r, i=i: on_click(r, i))
                self.attach(button, column, r, span, 1)
                buttons.append((key, column, span, button))
                column += span
            self.keys.append(buttons)
        self.mark()

    def key(self):
        return self.keys[self.row][self.index][0]

    def mark(self):
        for r, row in enumerate(self.keys):
            for i, (_key, _column, _span, button) in enumerate(row):
                css_class(button, "sel", (r, i) == (self.row, self.index))

    def place(self, row, index):
        self.row, self.index = row, index
        _key, column, span, _button = self.keys[row][index]
        self.column = column + span // 2
        self.mark()

    def move(self, direction, wrap=True):
        row, index = self.row, self.index
        if direction in ("left", "right"):
            step = 1 if direction == "right" else -1
            target = index + step
            if not 0 <= target < len(self.keys[row]):
                if not wrap:
                    return
                target %= len(self.keys[row])
            self.place(row, target)
            return
        target = row + (1 if direction == "down" else -1)
        if not 0 <= target < len(self.keys):
            if not wrap:
                return
            target %= len(self.keys)
        # Keep the remembered column so passing a wide key does not drift sideways.
        column = self.column
        for i, (_key, start, span, _button) in enumerate(self.keys[target]):
            if start <= column < start + span:
                self.row, self.index = target, i
                break
        self.mark()

    def set_case(self, shift):
        for row in self.keys:
            for key, _column, _span, button in row:
                if len(key) == 1 and key.isalpha():
                    button.set_label(key if shift != "off" else key.lower())
                elif key == "shift":
                    button.set_label("⇪" if shift == "lock" else "⇧")
                    css_class(button, "on", shift != "off")


class SeatView:
    """One player's panel. Pages switch instantly; contents update in place."""

    # (margin side, margin top/bottom, spacing, key spacing, rows, max width)
    SIZES = {
        "full": (40, 28, 18, 10, 7, 1240),
        "compact": (22, 12, 10, 6, 5, 720),
        "tiny": (12, 6, 5, 4, 4, 600),
    }

    def __init__(self, number, on_row, on_key, on_field):
        self.number = number
        self.size = None
        self.window = Gtk.Window(title=f"MC Couch Seat {number}")
        self.window.set_decorated(False)
        self.window.set_keep_above(True)
        self.window.connect("delete-event", lambda *_: True)
        for name in ("couch", "seat", f"p{number}"):
            self.window.get_style_context().add_class(name)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window.add(outer)
        bar = Gtk.Box()
        bar.get_style_context().add_class("accentbar")
        outer.pack_start(bar, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.pack_start(self.body, True, True, 0)

        header = Gtk.Box(spacing=12)
        header.pack_start(
            make_label(f"P{number}", "badge", ellipsize=False), False, False, 0
        )
        header.pack_start(
            make_label(f"PLAYER {number}", "seat-title", xalign=0, ellipsize=False),
            False,
            False,
            0,
        )
        self.state = make_label("", "state", xalign=1)
        header.pack_end(self.state, True, True, 0)
        for child in header.get_children():
            child.set_valign(Gtk.Align.CENTER)
        self.body.pack_start(header, False, False, 0)

        self.column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.column.set_halign(Gtk.Align.CENTER)
        self.body.pack_start(self.column, True, True, 0)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.set_vhomogeneous(False)
        self.column.pack_start(self.stack, True, True, 0)

        # Profile picker.
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        menu.pack_start(make_label("Who's playing?", "prompt"), False, False, 0)
        self.above = make_label("", "more")
        menu.pack_start(self.above, False, False, 0)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        menu.pack_start(self.list, False, False, 0)
        self.below = make_label("", "more")
        menu.pack_start(self.below, False, False, 0)
        self.rows = []
        self.on_row = on_row
        self.stack.add_named(menu, "menu")

        # Name entry: a text field plus either our keyboard or Steam's.
        entry = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.entry_prompt = make_label("New profile name", "prompt")
        entry.pack_start(self.entry_prompt, False, False, 0)
        field = Gtk.Button()
        field.set_can_focus(False)
        field.connect("clicked", lambda *_: on_field())
        self.field = field
        css_class(field, "field")
        inner = Gtk.Box(spacing=2)
        self.field_text = make_label("", "field-text", xalign=0)
        self.caret = make_label("▏", "caret", ellipsize=False)
        self.count = make_label("", "count", xalign=1, ellipsize=False)
        inner.pack_start(self.field_text, False, True, 0)
        inner.pack_start(self.caret, False, False, 0)
        inner.pack_end(self.count, False, False, 0)
        field.add(inner)
        entry.pack_start(field, False, False, 0)
        self.keyboard = NameKeyboard(on_key)
        entry.pack_start(self.keyboard, False, False, 0)
        self.osk_note = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.osk_note.pack_start(
            make_label("Type with the Steam keyboard", "status-text"), False, False, 0
        )
        self.osk_note.pack_start(
            make_label(
                "Press Enter on the keyboard to save and join.", "status-detail"
            ),
            False,
            False,
            0,
        )
        entry.pack_start(self.osk_note, False, False, 0)
        self.stack.add_named(entry, "entry")

        # Waiting, starting, leaving, disconnected.
        status = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        status.set_valign(Gtk.Align.CENTER)
        self.big = make_label("", "avatar", "big", ellipsize=False)
        self.big.set_halign(Gtk.Align.CENTER)
        self.warn = make_label("⚠", "warn-icon", ellipsize=False)
        self.status_name = make_label("", "status-name")
        line = Gtk.Box(spacing=12)
        line.set_halign(Gtk.Align.CENTER)
        self.spinner = Gtk.Spinner()
        self.status_text = make_label("", "status-text")
        line.pack_start(self.spinner, False, False, 0)
        line.pack_start(self.status_text, False, True, 0)
        self.status_detail = make_label("", "status-detail")
        for widget in (self.big, self.warn, self.status_name, line, self.status_detail):
            status.pack_start(widget, False, False, 0)
        self.stack.add_named(status, "status")

        self.error = make_label("", "error")
        self.error.set_halign(Gtk.Align.CENTER)
        self.body.pack_start(self.error, False, False, 0)
        self.hints = Hints()
        self.body.pack_end(self.hints, False, False, 0)
        outer.show_all()
        for widget in (self.error, self.osk_note, self.warn):
            widget.set_no_show_all(True)
            widget.hide()

    def set_geometry(self, width, height):
        size = "full" if height >= 1000 else "compact" if height >= 500 else "tiny"
        side, edge, spacing, keys, rows, widest = self.SIZES[size]
        if size != self.size:
            self.size = size
            for name in self.SIZES:
                css_class(self.window, name, name == size)
            self.body.set_margin_start(side)
            self.body.set_margin_end(side)
            self.body.set_margin_top(edge)
            self.body.set_margin_bottom(edge)
            self.body.set_spacing(spacing)
            self.column.set_spacing(spacing)
            self.hints.set_spacing(10 if size == "tiny" else 16)
            self.keyboard.set_column_spacing(keys)
            self.keyboard.set_row_spacing(keys)
            self.build_rows(rows)
        self.column.set_size_request(max(280, min(width - 2 * side, widest)), -1)

    def build_rows(self, count):
        for row in self.rows:
            self.list.remove(row[0])
        self.rows = []
        for i in range(count):
            button = Gtk.Button()
            button.set_can_focus(False)
            css_class(button, "row")
            box = Gtk.Box(spacing=14)
            avatar = make_label("", "avatar", ellipsize=False)
            name = make_label("", "row-name", xalign=0)
            tag = make_label("", "tag", ellipsize=False)
            tag.set_valign(Gtk.Align.CENTER)
            box.pack_start(avatar, False, False, 0)
            box.pack_start(name, True, True, 0)
            box.pack_end(tag, False, False, 0)
            button.add(box)
            button.connect("clicked", lambda _b, slot=i: self.on_row(self.first + slot))
            self.list.pack_start(button, False, False, 0)
            button.show_all()
            tag.set_no_show_all(True)
            self.rows.append((button, avatar, name, tag))
        self.first = 0

    def set_error(self, message):
        text(self.error, message or "")
        self.error.set_visible(bool(message))

    def show_menu(self, choices, chosen, remembered, error):
        self.stack.set_visible_child_name("menu")
        text(self.state, "Choose a profile")
        count = len(self.rows)
        self.first = max(0, min(chosen - count // 2, len(choices) - count))
        for slot, (button, avatar, name, tag) in enumerate(self.rows):
            i = self.first + slot
            button.set_visible(i < len(choices))
            if i >= len(choices):
                continue
            choice = choices[i]
            set_avatar(avatar, choice)
            text(name, "New profile" if choice == NEW else choice)
            css_class(button, "sel", i == chosen)
            css_class(button, "away", choice == SIT_OUT)
            text(tag, "LAST TIME")
            tag.set_visible(choice == remembered)
        text(self.above, f"▲  {self.first} more" if self.first else "")
        hidden = len(choices) - self.first - count
        text(self.below, f"▼  {hidden} more" if hidden > 0 else "")
        self.set_error(error)
        self.hints.show([("D-pad", "Choose"), ("A", "Join"), ("B", "Sit out")])

    def show_entry(self, typed, shift, steam, steam_available, error):
        self.stack.set_visible_child_name("entry")
        text(self.state, "New profile")
        text(self.field_text, typed or "Type a name")
        css_class(self.field_text, "empty", not typed)
        text(self.count, f"{len(typed)}/{NAME_LIMIT}")
        css_class(self.field, "live", True)
        self.keyboard.set_visible(not steam)
        self.osk_note.set_visible(steam)
        self.keyboard.set_case(shift)
        self.set_error(error)
        if steam:
            self.hints.show(
                [("Y", "Steam keyboard"), ("A", "Controller keys"), ("B", "Back")]
            )
        else:
            hints = [("A", "Type"), ("B", "Erase"), ("X", "Shift"), ("Start", "Done")]
            if steam_available:
                hints.insert(3, ("Y", "Steam keyboard"))
            self.hints.show(hints)

    def show_status(self, name, headline, detail, busy, error=""):
        self.stack.set_visible_child_name("status")
        text(self.state, headline)
        self.warn.set_visible(not name)
        self.big.set_visible(bool(name))
        if name:
            set_avatar(self.big, name)
        text(self.status_name, name or "Controller disconnected")
        text(self.status_text, headline if name else "")
        self.status_text.set_visible(bool(name))
        text(self.status_detail, detail)
        self.spinner.set_visible(busy)
        if busy:
            self.spinner.start()
        else:
            self.spinner.stop()
        self.set_error(error)
        self.hints.show([("Back+Start", "Hold 2 s to leave")] if name else [])


class LobbyView:
    """Backdrop behind the players: title, seat cards and help."""

    def __init__(self, server, on_quit):
        self.window = Gtk.Window(title="MC Couch Lobby")
        self.window.set_decorated(False)
        for name in ("couch", "lobby"):
            self.window.get_style_context().add_class(name)
        self.area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=26)
        self.area.set_halign(Gtk.Align.START)
        self.area.set_valign(Gtk.Align.START)
        self.window.add(self.area)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=26)
        inner.set_halign(Gtk.Align.CENTER)
        inner.set_valign(Gtk.Align.CENTER)
        self.area.pack_start(inner, True, True, 0)
        inner.pack_start(
            make_label("MINECRAFT", "title", ellipsize=False), False, False, 0
        )
        inner.pack_start(
            make_label(f"COUCH CO-OP  ·  {server}", "lobby-sub"), False, False, 0
        )
        cards = Gtk.Box(spacing=16)
        cards.set_halign(Gtk.Align.CENTER)
        self.card_row = cards
        self.inner = inner
        self.cards = []
        for n in range(1, 5):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            card.get_style_context().add_class("card")
            holder = Gtk.Box()
            holder.get_style_context().add_class(f"p{n}")
            bar = Gtk.Box()
            bar.get_style_context().add_class("accentbar")
            card.pack_start(bar, False, False, 0)
            body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            body.set_margin_start(16)
            body.set_margin_end(16)
            body.set_margin_top(12)
            body.set_margin_bottom(12)
            top = Gtk.Box(spacing=10)
            top.pack_start(
                make_label(f"P{n}", "badge", ellipsize=False), False, False, 0
            )
            name = make_label("", "card-name", xalign=0)
            top.pack_start(name, True, True, 0)
            state = make_label("", "card-state", xalign=0)
            body.pack_start(top, False, False, 0)
            body.pack_start(state, False, False, 0)
            card.pack_start(body, True, True, 0)
            holder.pack_start(card, True, True, 0)
            cards.pack_start(holder, False, False, 0)
            self.cards.append((card, name, state))
        inner.pack_start(cards, False, False, 0)
        self.help = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        hints = Hints()
        hints.show(
            [
                ("D-pad", "Choose"),
                ("A", "Join"),
                ("B", "Sit out"),
                ("Start", "Rejoin"),
                ("Back+Start", "Hold to leave"),
            ]
        )
        self.help.pack_start(hints, False, False, 0)
        self.help.pack_start(
            make_label(
                "Connect a controller to get a screen. When everyone is sitting out, "
                "press B to return to Steam.",
                "lobby-note",
            ),
            False,
            False,
            0,
        )
        quit_button = Gtk.Button(label="Return to Steam")
        quit_button.set_can_focus(False)
        quit_button.get_style_context().add_class("quit")
        quit_button.set_halign(Gtk.Align.CENTER)
        quit_button.connect("clicked", lambda *_: on_quit())
        self.help.pack_start(quit_button, False, False, 0)
        inner.pack_start(self.help, False, False, 0)
        self.region = None
        self.window.show_all()

    def update(self, region, cards):
        """region is the uncovered rectangle; cards holds (name, state, taken) per slot."""
        if region != self.region:
            self.region = region
            x, y, width, height = region
            self.area.set_margin_start(x)
            self.area.set_margin_top(y)
            self.area.set_size_request(width, height)
            corner, tiny = width < 1200, height < 500
            css_class(self.window, "corner", corner)
            css_class(self.window, "tiny", tiny)
            self.help.set_visible(not corner)
            self.card_row.set_spacing(10 if corner else 16)
            self.inner.set_spacing(12 if tiny else 26)
        for (card, name, state), (title, detail, taken) in zip(self.cards, cards):
            text(name, title)
            text(state, detail)
            css_class(card, "taken", taken)
            css_class(card, "open", not taken)
