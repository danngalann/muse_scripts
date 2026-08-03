# Connection and setup notes

## Chosen interface: Muse LSL

[Muse LSL](https://github.com/alexandrebarachant/muse-lsl) is an open-source
Python package that supports Muse 2, Muse S, and the original Muse. It connects
over BLE and exposes each sensor type as a local
[Lab Streaming Layer (LSL)](https://labstreaminglayer.readthedocs.io/) stream.
It is both a Python library and a CLI. This project uses its library API:

```python
from muselsl import stream

stream(address, ppg_enabled=True, lsl_time=True, retries=-1)
```

`stream()` is synchronous, which is why `muse_monitor.py` runs it in a daemon
thread and consumes its LSL output in the main/UI thread.

## Discovery and connection

The easiest first connection on Linux is:

```bash
uv run muselsl list
uv run python muse_monitor.py --address AA:BB:CC:DD:EE:FF
```

Providing `--address` bypasses discovery and is generally more reliable. The
Muse LSL README also supports `--name Muse-XXXX`; its device name is printed on
the inside of the left earpiece. Only one application can normally use the BLE
connection at a time, so close the Muse app before running the monitor.

This project loads `MUSE_ADDRESS` from its `.env` file as the default address.
Set that variable in the shell or pass `--address` to override it temporarily.

Normal Muse LSL operation scans and connects through BLE; OS-level Bluetooth
pairing is not a prerequisite. Treat `muselsl list` followed by a successful
stream as the connection check rather than an OS pairing dialog.

Muse LSL recommends its `bleak` backend by default. This project leaves the
backend as `auto`, or it can be selected explicitly:

```bash
uv run python muse_monitor.py --backend bleak --address AA:BB:CC:DD:EE:FF
```

On Windows, Muse LSL recommends
[BlueMuse](https://github.com/kowalej/BlueMuse/tree/master/Dist) for interactive
device discovery and connection. Start EEG and PPG there, then run:

```bash
uv run python muse_monitor.py --external-lsl
```

## Linux troubleshooting

- Confirm the Bluetooth adapter is enabled before discovery.
- On Arch Linux, install `bluez` (and optionally `bluez-utils` for
  `bluetoothctl`) and enable its daemon once:

  ```bash
  sudo systemctl enable --now bluetooth
  ```

  The daemon owns the D-Bus service `org.bluez` required by the default
  `bleak` backend. An error containing `NameHasNoOwner` and `org.bluez` means
  that daemon is not running.
- If the device is not found, use the MAC address shown by `uv run muselsl
  list` and ensure no phone/app remains connected.
- Muse LSL documents legacy `pygatt`/`gatt` permission and adapter issues.
  Prefer the default `bleak` backend before attempting those workarounds.
- An LSL outlet creation failure on Linux may need the Muse LSL-documented
  `pylsl==1.10.5`; that is the version currently resolved in `uv.lock`.

## Sources

- Muse LSL README: <https://github.com/alexandrebarachant/muse-lsl>
- Muse LSL package metadata and requirements:
  <https://pypi.org/project/muselsl/>
- LSL stream-inlet reference:
  <https://labstreaminglayer.readthedocs.io/projects/liblsl/ref/inlet.html>
