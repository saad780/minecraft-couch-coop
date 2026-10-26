import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from mc_couch.linux_input import (
    E,
    EVENT,
    Event,
    VirtualGamepad,
    enumerate_pads,
    ioctl_number,
)


class DiscoveryTests(unittest.TestCase):
    def test_periodic_discovery_never_opens_evdev(self):
        # evdev close may wait for kernel RCU grace periods. Opening eleven
        # devices every scan previously stalled all players for ~150 ms.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            device = root / "js0/device"
            device.mkdir(parents=True)
            for name, value in [
                ("name", "Microsoft X-Box 360 pad 0"),
                ("uniq", ""),
                ("phys", "steam/0"),
            ]:
                (device / name).write_text(value)
            (device / "event42").mkdir()
            original_glob = Path.glob

            def glob(path, pattern):
                return (
                    original_glob(root, pattern)
                    if path == Path("/sys/class/input")
                    else original_glob(path, pattern)
                )

            with (
                patch.object(Path, "glob", glob),
                patch("os.access", return_value=True),
                patch(
                    "os.open", side_effect=AssertionError("evdev must not be opened")
                ),
            ):
                self.assertEqual(enumerate_pads()[0]["path"], "/dev/input/event42")

    def test_native_64bit_input_layout(self):
        self.assertEqual(EVENT.size, 24)
        packet = EVENT.pack(123, 456, E.EV_KEY, E.BTN_SOUTH, 1)
        self.assertEqual(Event(*EVENT.unpack(packet)).value, 1)
        self.assertEqual(ioctl_number(1, "E", 0x90, 4), 0x40044590)
        self.assertEqual(struct.calcsize("@H2x6i"), 28)


@unittest.skipUnless(
    os.environ.get("MC_COUCH_UINPUT_TEST") == "1",
    "requires explicit root/device integration opt-in",
)
class KernelIntegrationTests(unittest.TestCase):
    def test_proxy_keeps_identity_across_source_reconnection(self):
        import time
        from mc_couch.linux_input import InputDevice

        physical = VirtualGamepad(96, test=True)
        proxy = VirtualGamepad(97, test=True)
        try:
            for _ in range(50):
                if proxy.ready() and physical.ready():
                    break
                time.sleep(0.02)
            self.assertTrue(proxy.ready())
            self.assertTrue(physical.ready())
            node = proxy.event
            source = InputDevice(physical.event)
            listener = InputDevice(proxy.event)
            try:
                physical.write(E.EV_KEY, E.BTN_SOUTH, 1)
                physical.syn()
                time.sleep(0.03)
                for event in source.read():
                    proxy.forward(event, source)
                time.sleep(0.03)
                events = listener.read()
                self.assertTrue(
                    any(e.code == E.BTN_SOUTH and e.value == 1 for e in events)
                )
                proxy.reset()
            finally:
                source.close()
                listener.close()
            # Remove and recreate the source device; the client-facing proxy
            # remains alive at the same node instead of becoming a new gamepad.
            physical.close()
            physical = VirtualGamepad(96, test=True)
            reopened = InputDevice(physical.event)
            try:
                physical.write(E.EV_KEY, E.BTN_EAST, 1)
                physical.syn()
                time.sleep(0.03)
                for event in reopened.read():
                    proxy.forward(event, reopened)
            finally:
                reopened.close()
            self.assertEqual(proxy.event, node)
        finally:
            physical.close()
            proxy.close()


if __name__ == "__main__":
    unittest.main()
