spidriver
=========

.. image:: /images/spidriver-main-600.jpg
   :target: https://spidriver.com

SPIDriver controls SPI devices over USB on Windows, macOS, and Linux.
The Python driver supports SPIDriver, SPIDriver2, and SPIDriverQ with automatic
product detection. Python 3.10 or newer and pySerial 3.5 or newer are required.

Installation
============

.. code-block:: sh

    python -m pip install spidriver

Quick start
===========

.. code-block:: python

    from spidriver import SPIDriver

    with SPIDriver("/dev/ttyUSB0") as spi:
        spi.sel()
        try:
            spi.write([0x9f])
            print(spi.read(3).hex())
        finally:
            spi.unsel()

Use your device's port, such as ``COM3`` on Windows. Closing a connection does
not change GPIO or CS. The `SPIDriver User Guide
<https://spidriver.com/spidriver.pdf>`_ describes the original hardware.

SPIDriverQ
==========

The same ``SPIDriver`` class exposes all Q operations below. Q-specific methods
raise ``NotImplementedError`` on older products. When migrating scripts from
the standalone Q module, import and construct ``SPIDriver`` instead of
``SPIDriverQ``. Connecting does not print or query firmware details; call
``build_info()`` explicitly.

.. code-block:: python

    from spidriver import SPIDriver

    with SPIDriver("/dev/ttyACM0") as spi:
        print(spi.build_info())
        spi.unsel()
        spi.set_width(1)
        spi.set_speed(12_500_000)
        spi.setmode(0)

Width 0 is 3-wire, 1 is single SPI, 2 is dual, 4 is quad, and 11 is hardware
SPI0. Deselect before switching between PIO and SPI0. SPI0 forces mode 0 and
ignores other mode requests. In 3-wire/dual/quad modes, ``writeread`` is
receive-only. Bulk transfers preserve CS but do not update the firmware CRC.
Display captures use a firmware-specific binary layout; reset after an
interrupted upload or layout mismatch before sending more commands. Older Q
firmware may not implement every diagnostic command.

Migration and errors
====================

Version 2 requires Python 3.10+. Existing method names and byte-list transfer
inputs remain supported. Invalid arguments raise explicit exceptions instead
of assertions. Reads now return all requested bytes or raise ``TimeoutError``;
partial serial writes are retried. pySerial exceptions also propagate. A timeout
can leave a command incomplete; reset/reconnect when framing is uncertain.
Timeouts apply per serial operation, not to the entire multi-block transfer.

Use ``SPIDriver(port, timeout=1, write_timeout=1)`` to configure a new port.
An open serial-compatible transport can be passed instead; its timeouts are
preserved. The driver closes either kind of transport on initialization failure,
``close()``, or context-manager exit. Status attributes update on ``getstatus()``.

Module contents
===============

.. autoclass:: spidriver.SPIDriver
   :member-order: bysource
   :members:
   :inherited-members:
