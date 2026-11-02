# SPIDriver Python driver

Control SPIDriver, SPIDriver2, and SPIDriverQ over USB from Python 3.10 or newer
on Windows, macOS, or Linux. The only runtime dependency is pySerial.

```sh
python -m pip install spidriver
```

The same class detects all three products. Existing method names and lists of
byte values remain supported:

```python
from spidriver import SPIDriver

with SPIDriver("/dev/ttyUSB0") as spi:  # e.g. COM3 on Windows
    spi.sel()
    try:
        spi.write([0x9f])
        device_id = spi.read(3)
    finally:
        spi.unsel()
    print(device_id.hex())
```

## SPIDriverQ

All Q extensions are available on the single public `SPIDriver` class. When
migrating scripts from the standalone `SPIDriverQ.py` module, use
`from spidriver import SPIDriver` and construct `SPIDriver(port)`.
Q-specific operations raise `NotImplementedError` on older hardware.

```python
from spidriver import SPIDriver

with SPIDriver("/dev/ttyACM0") as spi:
    print(spi.build_info())
    spi.unsel()
    spi.set_width(1)
    spi.set_speed(12_500_000)
    spi.setmode(0)
```

- `set_width(0 | 1 | 2 | 4 | 11)`: 3-wire, single, dual, quad, or hardware SPI0.
  Deselect before switching between PIO and SPI0. SPI0 supports mode 0 only;
  selecting it forces mode 0, and firmware ignores other mode requests.
- `set_speed(hz)`: request a clock between 1 Hz and 25 MHz. Actual frequency
  depends on hardware clock divisors.
- `set2(level)`, `set3(level)`: control IO2/IO3; ignored in quad mode.
- `bulk_write(data)`, `bulk_read(size)`: TX-only/RX-only transfers in blocks up
  to 65,536 bytes. These preserve CS and do not update the firmware CCITT CRC.
  `bulk_write` accepts contiguous bytes-like buffers.
- `readings()`, `tare()`, `save_config(timeout=5)`: raw INA226 readings,
  zero-current calibration, and persistent settings. Saving waits for a pending
  tare and checks the firmware acknowledgement.
- `build_info()`: firmware metadata, queried explicitly without startup output.
- `snapshot()`, `display_state(state)`: capture/upload firmware-specific binary
  display state. Upload currently requires a matching 440-byte DeviceData layout.
- `screenshot(slot)`, `lcd_test_pattern()`, `lcd_test_card()`, `lcd_test_loop()`:
  firmware display diagnostics.
- `enter_sink()`: discard USB input until hardware reset.
- `enter_bootloader()`: reboot into UF2/BOOTSEL.

In 3-wire, dual, and quad modes, `read` releases the data lines and `writeread`
is receive-only (transmitted values are ignored). Width changes do not toggle CS.
Frozen display scenes and test modes may require reset to resume normal operation.
After an interrupted display upload or a layout mismatch, reset before sending
more commands. Optional firmware features can time out on older Q firmware.

## Connection and error handling

`SPIDriver(port, timeout=1, write_timeout=1)` opens a port at 460800 baud.
An already open serial-compatible object can be supplied instead; its timeouts
are preserved. The driver takes responsibility for closing either transport on
initialization failure, context-manager exit, or `close()`.
Closing does not deassert CS or alter outputs; use `unsel()` in a `finally` block
when a transaction must end even after an exception.

Reads return the requested number of bytes or raise `TimeoutError`; writes retry
partial transfers and raise on timeout. pySerial errors also propagate. Timeouts
apply to serial operations, not to the entire multi-block transfer. A timeout can
leave the protocol mid-command: reset/reconnect before continuing when framing
is uncertain. Status attributes reflect the last `getstatus()` call.

## Migration from 1.x

Version 2 requires Python 3.10+; Python 2 support has been removed. Invalid modes,
GPIO levels, and negative read sizes now raise explicit exceptions, including
when Python runs with `-O`. Incomplete reads raise instead of silently returning
truncated data. Normal connection no longer prints echo failures; exceptions
include the diagnostic details. The existing `read(l)`, `write(bb)`,
`writeread(bb)`, `seta(v)`, `setb(v)`, and `setmode(m)` keyword names are retained.

## Development

Internally, the driver uses capability mixins:

```python
class SPIDriver(_SPIDriverQMixin, _SPIDriver2Mixin, _SPIDriverBase):
    ...
```

The base owns serial transport, connection lifetime, and common commands.
The SPIDriver2 mixin implements SPI mode selection and mode status for both
SPIDriver2 and Q. The Q mixin holds Q-only commands. These classes are private;
callers always construct `SPIDriver`. Hardware checks use the product reported
by the device, and unsupported commands fail before writing to it.

From the repository root:

```sh
python -m pip install -e './python[docs]' build
python -m unittest discover -s python/tests -v
python -m build python
python -m sphinx -W -b html python/docs python/docs/_build/html
```

Tests use simulated serial responses and need no hardware. Optional integration
tests also run against `spidriverq_sim` when that firmware simulator is on
`PYTHONPATH`. Full API documentation: https://spidriver.readthedocs.io/en/latest/.
