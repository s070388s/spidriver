"""Optional integration tests against SPIDriverQ's compiled firmware simulator.

Run with the simulator build directory on PYTHONPATH using its Python ABI.
"""

import unittest

from spidriver import SPIDriver

try:
    import spidriverq_sim as sim
except ModuleNotFoundError as exc:
    if exc.name != "spidriverq_sim":
        raise
    sim = None


@unittest.skipIf(sim is None, "SPIDriverQ firmware simulator is not installed")
class SimulatorTests(unittest.TestCase):
    def test_products_modes_and_legacy_transfers(self):
        # Q firmware can emit the original status format, but does not emulate
        # SPIDriver2's mode field. SPIDriver2 is covered by scripted replies.
        for product in ("spidriver1", "spidriverq"):
            dd = sim.DeviceData(product=product)
            with SPIDriver(sim.SimSerial(dd)) as spi:
                for mode in range(1) if product == "spidriver1" else range(4):
                    spi.setmode(mode)
                    spi.sel()
                    spi.write(list(range(65)))
                    self.assertEqual(spi.read(65), b"\xff" * 65)
                    self.assertEqual(spi.writeread(bytes(65)), b"\xff" * 65)
                    spi.unsel()
                    spi.getstatus()
                    self.assertEqual((spi.mode, spi.cs), (mode, 1))

    def test_q_widths_bulk_and_status_framing(self):
        for width in (0, 1, 2, 4, 11):
            with self.subTest(width=width):
                dd = sim.DeviceData()
                with SPIDriver(sim.SimSerial(dd)) as spi:
                    spi.set_width(width)
                    spi.set_speed(12500000)
                    spi.sel()
                    dd.crc = 0xA55A
                    spi.bulk_write(b"\x55\xaa" * 32769)
                    self.assertEqual(spi.bulk_read(65537), b"\xff" * 65537)
                    spi.unsel()
                    spi.getstatus()
                    self.assertEqual(spi.ccitt_crc, 0xA55A)
                    self.assertEqual(dd.spi_width, width)
                    self.assertEqual(dd.spi_speed_hz, 12500000)
                    self.assertEqual(spi.cs, 1)

    def test_gpio_json_display_and_save(self):
        dd = sim.DeviceData()
        with SPIDriver(sim.SimSerial(dd)) as spi:
            spi.set2(0)
            spi.set3(0)
            self.assertEqual(dd.io_gpio_low_mask, 12)
            self.assertIn("revision", spi.build_info())
            self.assertIsInstance(spi.readings(), dict)
            spi.tare()
            # The simulator deliberately reports flash persistence failure.
            with self.assertRaisesRegex(OSError, "Failed to save"):
                spi.save_config()
            spi.getstatus()
            state = spi.snapshot()
            self.assertEqual(len(state), 440)
            spi.display_state(state)
            self.assertEqual(dd.screenshot_slot, 13)
            self.assertEqual(len(spi.snapshot()), 440)


if __name__ == "__main__":
    unittest.main()
