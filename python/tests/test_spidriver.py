"""Protocol regression tests: no attached hardware is accessed."""

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from spidriver import SPIDriver


def status(product="spidriverq", mode=3):
    body = f"{product} TEST1234 123 4.890 038 25.0 1 0 1 a55a"
    if product != "spidriver1":
        body += f" {mode}"
    return b"[" + body.encode().ljust(78) + b"]"


class Serial:
    """Scripted replies with independently fragmented reads and writes."""

    def __init__(self, reply=b"", read_limit=7, write_limit=11):
        self.reply = bytearray(reply)
        self.sent = bytearray()
        self.read_limit = read_limit
        self.write_limit = write_limit
        self.timeout = 1
        self.is_open = True
        self.flushes = 0
        self.read_timeouts = []

    @property
    def in_waiting(self):
        # Constructor replies model responses arriving only after a command.
        return 0

    def read(self, size=1):
        self.read_timeouts.append(self.timeout)
        count = min(size, self.read_limit)
        result = bytes(self.reply[:count])
        del self.reply[:count]
        return result

    def write(self, data):
        count = min(len(data), self.write_limit)
        self.sent.extend(data[:count])
        return count

    def flush(self):
        self.flushes += 1

    def close(self):
        self.is_open = False


def driver(reply=b"", product="spidriverq"):
    transport = Serial(b"\x55\x00\xff\xaa" + status(product))
    spi = SPIDriver(transport)
    transport.sent.clear()
    transport.reply.extend(reply)
    return spi


class ConnectionTests(unittest.TestCase):
    def test_all_products(self):
        for product in ("spidriver1", "spidriver2", "spidriverq"):
            with self.subTest(product=product):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    spi = driver(product=product)
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(spi.product, product)
                self.assertEqual(spi.mode, 0 if product == "spidriver1" else 3)
                self.assertEqual((spi.voltage, spi.current, spi.temp), (4.89, 38, 25))
                self.assertEqual(
                    (spi.a, spi.b, spi.cs, spi.ccitt_crc), (1, 0, 1, 0xA55A)
                )
                self.assertIn("TEST1234", repr(spi))

    def test_port_configuration_and_handshake(self):
        transport = Serial(b"\x55\x00\xff\xaa" + status())
        with patch("spidriver.serial.Serial", return_value=transport) as opened:
            spi = SPIDriver(Path("/dev/example"), timeout=2, write_timeout=3)
        opened.assert_called_once_with(
            "/dev/example", 460800, timeout=2, write_timeout=3
        )
        self.assertEqual(transport.sent, b"@" * 64 + b"e\x55e\x00e\xffe\xaa?")
        with self.assertRaisesRegex(RuntimeError, "body"):
            with spi as same:
                self.assertIs(same, spi)
                raise RuntimeError("body")
        self.assertFalse(transport.is_open)

    def test_startup_failures_close(self):
        for reply, error in (
            (b"", TimeoutError),
            (b"!", OSError),
            (b"\x55\x00\xff\xaa" + b"X" * 80, ValueError),
        ):
            with self.subTest(reply=reply):
                transport = Serial(reply)
                with self.assertRaises(error):
                    SPIDriver(transport)
                self.assertFalse(transport.is_open)

    def test_status_errors_preserve_previous_attributes(self):
        spi = driver()
        for reply, error in (
            (b"short", TimeoutError),
            (b"[" + b"spidriverq".ljust(78) + b"]", ValueError),
            (b"[" + b"\xff" * 78 + b"]", ValueError),
        ):
            spi.ser.reply.extend(reply)
            with self.assertRaises(error):
                spi.getstatus()
            self.assertEqual(spi.serial, "TEST1234")
            self.assertEqual(spi.ccitt_crc, 0xA55A)

    def test_no_progress_write(self):
        spi = driver()
        spi.ser.write_limit = 0
        with self.assertRaises(TimeoutError):
            spi.sel()


class TransferTests(unittest.TestCase):
    def test_legacy_transfer_boundaries_and_inputs(self):
        for size in (0, 1, 63, 64, 65, 128, 129):
            payload = bytes(i % 256 for i in range(size))
            for convert in (bytes, bytearray, list, tuple, memoryview):
                with self.subTest(size=size, convert=convert):
                    spi = driver()
                    spi.write(bb=convert(payload))
                    expected = b"".join(
                        bytes((0xC0 + len(payload[i : i + 64]) - 1,))
                        + payload[i : i + 64]
                        for i in range(0, size, 64)
                    )
                    self.assertEqual(spi.ser.sent, expected)
                    spi = driver(payload)
                    self.assertEqual(spi.writeread(bb=convert(payload)), payload)
                    self.assertEqual(
                        spi.ser.sent,
                        b"".join(
                            bytes((0x80 + len(payload[i : i + 64]) - 1,))
                            + payload[i : i + 64]
                            for i in range(0, size, 64)
                        ),
                    )
            spi = driver(payload)
            self.assertEqual(spi.read(l=size), payload)
            self.assertEqual(
                spi.ser.sent,
                b"".join(
                    bytes((0x80 + min(size - i, 64) - 1,)) + b"\xff" * min(size - i, 64)
                    for i in range(0, size, 64)
                ),
            )

    def test_bulk_boundaries(self):
        for size in (0, 1, 65535, 65536, 65537, 131073):
            with self.subTest(size=size):
                payload = bytes(i % 256 for i in range(size))
                spi = driver(payload)
                spi.bulk_write(payload)
                expected = b"".join(
                    b"w"
                    + (len(payload[i : i + 65536]) - 1).to_bytes(2, "big")
                    + payload[i : i + 65536]
                    for i in range(0, size, 65536)
                )
                self.assertEqual(spi.ser.sent, expected)
                spi.ser.sent.clear()
                self.assertEqual(spi.bulk_read(size), payload)
                self.assertEqual(
                    spi.ser.sent,
                    b"".join(
                        b"r" + (min(size - i, 65536) - 1).to_bytes(2, "big")
                        for i in range(0, size, 65536)
                    ),
                )

    def test_incomplete_reads_fail(self):
        for method, argument in (("read", 2), ("writeread", b"ab"), ("bulk_read", 2)):
            spi = driver(b"x")
            with self.assertRaises(TimeoutError):
                getattr(spi, method)(argument)

    def test_invalid_arguments_send_nothing(self):
        cases = [
            ("setmode", -1),
            ("setmode", 4),
            ("setmode", 1.5),
            ("seta", 2),
            ("setb", -1),
            ("set2", 2),
            ("set3", 0.5),
            ("set_width", 3),
            ("set_width", 1.0),
            ("set_speed", 0),
            ("set_speed", 25000001),
            ("set_speed", 100.5),
            ("read", -1),
            ("read", 1.5),
            ("bulk_read", -1),
            ("write", 5),
            ("write", [256]),
            ("writeread", [1, -1]),
            ("screenshot", 10),
            ("screenshot", -1),
            ("screenshot", 2.5),
            ("display_state", b"short"),
            ("save_config", 0),
            ("save_config", float("nan")),
            ("save_config", float("inf")),
        ]
        for method, argument in cases:
            with self.subTest(method=method, argument=argument):
                spi = driver()
                with self.assertRaises((ValueError, TypeError)):
                    getattr(spi, method)(argument)
                self.assertEqual(spi.ser.sent, b"")

    def test_legacy_controls_and_mode(self):
        spi = driver()
        spi.sel()
        spi.unsel()
        spi.detach()
        spi.seta(v=0)
        spi.setb(v=1)
        for mode in range(4):
            spi.setmode(m=mode)
        self.assertEqual(spi.ser.sent, b"suxa\x00b\x01m\x00m\x01m\x02m\x03")
        spi = driver(product="spidriver1")
        spi.setmode(0)
        with self.assertRaises(OSError):
            spi.setmode(1)
        self.assertEqual(spi.ser.sent, b"")
        spi = driver(product="spidriver2")
        spi.setmode(2)
        self.assertEqual(spi.ser.sent, b"m\x02")


class QTests(unittest.TestCase):
    def test_q_commands(self):
        spi = driver()
        for width in (0, 1, 2, 4, 11):
            spi.set_width(width)
        spi.set2(0)
        spi.set3(1)
        spi.set_speed(1)
        spi.set_speed(25000000)
        spi.tare()
        spi.enter_sink()
        spi.screenshot(0)
        spi.screenshot(9)
        spi.lcd_test_pattern()
        spi.lcd_test_card()
        spi.lcd_test_loop()
        spi.enter_bootloader()
        self.assertEqual(
            spi.ser.sent,
            b"d0d1d2d4d\x0b2\x003\x01c00000001c25000000"
            b"%SPI%t%SPI%>%SPI%0%SPI%9%SPI%T%SPI%C%SPI%L%SPI%b",
        )
        self.assertEqual(spi.ser.flushes, 1)

    def test_all_q_methods_reject_older_products(self):
        methods = [
            ("set_width", (1,)),
            ("set2", (0,)),
            ("set3", (1,)),
            ("set_speed", (100,)),
            ("bulk_write", (b"a",)),
            ("bulk_read", (1,)),
            ("readings", ()),
            ("build_info", ()),
            ("tare", ()),
            ("save_config", ()),
            ("snapshot", ()),
            ("display_state", (bytes(440),)),
            ("screenshot", ()),
            ("lcd_test_pattern", ()),
            ("lcd_test_card", ()),
            ("lcd_test_loop", ()),
            ("enter_sink", ()),
            ("enter_bootloader", ()),
        ]
        for product in ("spidriver1", "spidriver2"):
            spi = driver(product=product)
            for method, args in methods:
                with self.subTest(product=product, method=method):
                    with self.assertRaises(NotImplementedError):
                        getattr(spi, method)(*args)
                    self.assertEqual(spi.ser.sent, b"")

    def test_json_queries_and_framing(self):
        obj = {"revision": "test", "nested": {"unicode": "\u00e9"}}
        for method, command in (("readings", b"%SPI%n"), ("build_info", b"%SPI%v")):
            spi = driver(json.dumps(obj, ensure_ascii=False).encode() + status())
            self.assertEqual(getattr(spi, method)(), obj)
            self.assertEqual(spi.ser.sent, command)
            spi.getstatus()
        for reply, error in (
            (b"", TimeoutError),
            (b"{", TimeoutError),
            (b"[]", ValueError),
            (b"x" * 65536, ValueError),
        ):
            with self.subTest(reply_length=len(reply)):
                with self.assertRaises(error):
                    driver(reply).build_info()

    def test_save_acknowledgement_and_timeout_restoration(self):
        for reply, error in (
            (b"1", None),
            (b"0", OSError),
            (b"", TimeoutError),
            (b"?", OSError),
        ):
            spi = driver(reply)
            spi.ser.timeout = 0.25
            if error:
                with self.assertRaises(error):
                    spi.save_config(timeout=3)
            else:
                spi.save_config(timeout=3)
            self.assertEqual(spi.ser.timeout, 0.25)
            self.assertEqual(spi.ser.read_timeouts[-1], 3)
            self.assertEqual(spi.ser.sent, b"%SPI%w")
        spi = driver()
        spi.ser.write_limit = 0
        with self.assertRaises(TimeoutError):
            spi.save_config()
        self.assertEqual(spi.ser.timeout, 1)

    def test_snapshot_binary_partial_and_empty(self):
        for payload in (b"", b"\x00\xff\r\n" * 110):
            spi = driver(len(payload).to_bytes(2, "big") + payload + status())
            self.assertEqual(spi.snapshot(), payload)
            self.assertEqual(spi.ser.sent, b"%SPI%s")
            spi.getstatus()
        for reply in (b"", b"\x00", b"\x00\x02X"):
            with self.assertRaises(TimeoutError):
                driver(reply).snapshot()

    def test_display_upload_handshake_and_errors(self):
        payload = bytes(range(220)) * 2
        spi = driver(b"\x01\xb81" + status())
        spi.ser.read_limit = 1
        spi.display_state(payload)
        self.assertEqual(spi.ser.sent, b"%SPI%S" + payload)
        spi.getstatus()
        for reply, error, sent_payload in (
            (b"", TimeoutError, False),
            (b"\x01", TimeoutError, False),
            (b"\x01\xb7", ValueError, False),
            (b"\x01\xb8", TimeoutError, True),
            (b"\x01\xb80", ValueError, True),
            (b"\x01\xb8?", OSError, True),
        ):
            spi = driver(reply)
            with self.assertRaises(error):
                spi.display_state(payload)
            self.assertEqual(
                spi.ser.sent, b"%SPI%S" + (payload if sent_payload else b"")
            )


if __name__ == "__main__":
    unittest.main()
