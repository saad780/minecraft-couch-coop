"""Small Linux evdev/uinput interface using the documented kernel UAPI.

This avoids compiling Python extension modules on SteamOS. Numeric constants
are Linux input ABI values, not copies of a third-party driver implementation.
"""

from dataclasses import dataclass
import errno
import fcntl
import os
from pathlib import Path
import struct
import time
from types import SimpleNamespace

E = SimpleNamespace(
    EV_SYN=0,
    EV_KEY=1,
    EV_ABS=3,
    SYN_REPORT=0,
    SYN_DROPPED=3,
    BTN_SOUTH=304,
    BTN_EAST=305,
    BTN_NORTH=307,
    BTN_WEST=308,
    BTN_TL=310,
    BTN_TR=311,
    BTN_SELECT=314,
    BTN_START=315,
    BTN_MODE=316,
    BTN_THUMBL=317,
    BTN_THUMBR=318,
    BTN_DPAD_UP=544,
    BTN_DPAD_DOWN=545,
    BTN_DPAD_LEFT=546,
    BTN_DPAD_RIGHT=547,
    ABS_X=0,
    ABS_Y=1,
    ABS_Z=2,
    ABS_RX=3,
    ABS_RY=4,
    ABS_RZ=5,
    ABS_HAT0X=16,
    ABS_HAT0Y=17,
    BUS_USB=3,
)
KEYS = [
    E.BTN_SOUTH,
    E.BTN_EAST,
    E.BTN_NORTH,
    E.BTN_WEST,
    E.BTN_TL,
    E.BTN_TR,
    E.BTN_SELECT,
    E.BTN_START,
    E.BTN_MODE,
    E.BTN_THUMBL,
    E.BTN_THUMBR,
]
STICKS = [E.ABS_X, E.ABS_Y, E.ABS_RX, E.ABS_RY]
TRIGGERS = [E.ABS_Z, E.ABS_RZ]
HATS = [E.ABS_HAT0X, E.ABS_HAT0Y]
EVENT = struct.Struct("@llHHi")


def ioctl_number(direction, kind, number, size=0):
    return (direction << 30) | (size << 16) | (ord(kind) << 8) | number


@dataclass
class AbsInfo:
    value: int
    min: int
    max: int
    fuzz: int = 0
    flat: int = 0
    resolution: int = 0


@dataclass
class Event:
    sec: int
    usec: int
    type: int
    code: int
    value: int

    def timestamp(self):
        return self.sec + self.usec / 1_000_000


class InputDevice:
    def __init__(self, path):
        self.path = str(path)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        device = Path("/sys/class/input") / Path(path).name / "device"
        try:
            self.name = (device / "name").read_text().strip()
            self.uniq = (device / "uniq").read_text().strip()
            self.phys = (device / "phys").read_text().strip()
        except OSError:
            self.close()
            raise
        self._abs = {}

    def read(self):
        data = os.read(self.fd, EVENT.size * 128)
        if not data:
            raise OSError(errno.ENODEV, "Controller disconnected")
        if len(data) % EVENT.size:
            raise OSError("Unexpected evdev packet size")
        return [
            Event(*EVENT.unpack_from(data, i)) for i in range(0, len(data), EVENT.size)
        ]

    def absinfo(self, axis):
        if axis not in self._abs:
            data = bytearray(24)
            fcntl.ioctl(self.fd, ioctl_number(2, "E", 0x40 + axis, 24), data, True)
            self._abs[axis] = AbsInfo(*struct.unpack("@6i", data))
        return self._abs[axis]

    def grab(self):
        fcntl.ioctl(self.fd, ioctl_number(1, "E", 0x90, 4), 1)

    def ungrab(self):
        fcntl.ioctl(self.fd, ioctl_number(1, "E", 0x90, 4), 0)

    def close(self):
        if getattr(self, "fd", -1) >= 0:
            os.close(self.fd)
            self.fd = -1


class VirtualGamepad:
    def __init__(self, number, *, test=False):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        self.name = f"MC Test Controller {number}" if test else f"MC Couch Pad {number}"
        self.event = self.js = None
        self.keys = set()
        try:
            for kind in [E.EV_KEY, E.EV_ABS]:
                fcntl.ioctl(self.fd, ioctl_number(1, "U", 100, 4), kind)
            for key in KEYS:
                fcntl.ioctl(self.fd, ioctl_number(1, "U", 101, 4), key)
            axes = [(a, AbsInfo(0, -32768, 32767, 0, 2048)) for a in STICKS]
            axes += [(a, AbsInfo(0, 0, 255)) for a in TRIGGERS]
            axes += [(a, AbsInfo(0, -1, 1)) for a in HATS]
            for axis, info in axes:
                fcntl.ioctl(self.fd, ioctl_number(1, "U", 103, 4), axis)
                values = [
                    info.value,
                    info.min,
                    info.max,
                    info.fuzz,
                    info.flat,
                    info.resolution,
                ]
                fcntl.ioctl(
                    self.fd,
                    ioctl_number(1, "U", 4, 28),
                    struct.pack("@H2x6i", axis, *values),
                )
            physical = f"mc-test/{number}" if test else f"mc-couch/seat{number}"
            fcntl.ioctl(
                self.fd,
                ioctl_number(1, "U", 108, struct.calcsize("P")),
                physical.encode() + b"\0",
            )
            setup = struct.pack(
                "@4H80sI", E.BUS_USB, 0x28DE, 0x11FF, 1, self.name.encode(), 0
            )
            fcntl.ioctl(self.fd, ioctl_number(1, "U", 3, len(setup)), setup)
            fcntl.ioctl(self.fd, ioctl_number(0, "U", 1))
            name = bytearray(128)
            fcntl.ioctl(self.fd, ioctl_number(2, "U", 44, len(name)), name, True)
            self.sys_path = (
                Path("/sys/devices/virtual/input")
                / bytes(name).split(b"\0")[0].decode()
            )
            for _ in range(40):
                found = list(self.sys_path.glob("event*"))
                if found:
                    self.event = "/dev/input/" + found[0].name
                    break
                time.sleep(0.005)
            if not self.event:
                raise RuntimeError("Linux did not create the virtual controller.")
        except Exception:
            self.close()
            raise

    def ready(self):
        found = list(self.sys_path.glob("js*"))
        if found:
            self.js = "/dev/input/" + found[0].name
        return bool(
            self.event
            and self.js
            and os.access(self.event, os.R_OK)
            and os.access(self.js, os.R_OK)
        )

    def write(self, kind, code, value):
        os.write(self.fd, EVENT.pack(0, 0, kind, code, value))

    def syn(self):
        self.write(E.EV_SYN, E.SYN_REPORT, 0)

    def reset(self):
        if getattr(self, "fd", -1) < 0:
            return
        for code in self.keys:
            self.write(E.EV_KEY, code, 0)
        self.keys.clear()
        for axis in STICKS + TRIGGERS + HATS:
            self.write(E.EV_ABS, axis, 0)
        self.syn()

    def forward(self, event, source):
        if event.type == E.EV_SYN:
            self.syn()
        elif event.type == E.EV_KEY and event.code in KEYS:
            self.write(event.type, event.code, event.value)
            if event.value:
                self.keys.add(event.code)
            else:
                self.keys.discard(event.code)
        elif event.type == E.EV_ABS and event.code in STICKS + TRIGGERS + HATS:
            value = event.value
            if event.code in STICKS + TRIGGERS:
                info = source.absinfo(event.code)
                fraction = (value - info.min) / max(1, info.max - info.min)
                value = round(fraction * (65535 if event.code in STICKS else 255))
                if event.code in STICKS:
                    value -= 32768
            self.write(event.type, event.code, max(-32768, min(32767, value)))

    def close(self):
        if getattr(self, "fd", -1) >= 0:
            try:
                fcntl.ioctl(self.fd, ioctl_number(0, "U", 2))
            except OSError:
                pass
            os.close(self.fd)
            self.fd = -1


def enumerate_pads(include_test=False):
    pads = []
    for js in sorted(Path("/sys/class/input").glob("js*")):
        try:
            device = js / "device"
            name = (device / "name").read_text().strip()
            if name.startswith("MC Couch Pad"):
                continue
            events = list(device.glob("event*"))
            if not events:
                continue
            path = "/dev/input/" + events[0].name
            if not os.access(path, os.R_OK):
                continue
            uniq = (device / "uniq").read_text().strip()
            phys = (device / "phys").read_text().strip()
            pads.append(
                {
                    "path": path,
                    "name": name,
                    "key": uniq or phys or name,
                    "virtual": name.startswith("Microsoft X-Box 360 pad "),
                    "test": name.startswith("MC Test Controller"),
                }
            )
        except OSError:
            continue
    virtual = any(p["virtual"] for p in pads)
    return [
        p
        for p in pads
        if (p["virtual"] or not virtual or (include_test and p["test"]))
        and (not p["test"] or include_test)
    ]
