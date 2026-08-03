# Muse 2 live monitor

This `uv`-managed Python project connects to a Muse 2 over Bluetooth Low Energy,
plots the four EEG channels live, and estimates heart rate from its infrared PPG
sensor. It is a personal visualization tool, not a medical device.

## Quick start

1. Charge and wear the headband, then close the Muse app and any other program
   that could hold its Bluetooth connection.
2. Turn on Bluetooth on this computer.
3. Discover the headband:

   ```bash
   uv run muselsl list
   ```

4. Run the monitor, preferably with the address printed above:

   ```bash
   uv run python muse_monitor.py --address AA:BB:CC:DD:EE:FF
   ```

   Or have Muse LSL discover the first Muse:

   ```bash
   uv run python muse_monitor.py
   ```

Use `uv run python muse_monitor.py --help` for all options. The first 8–12 seconds of
PPG are used to establish a heart-rate estimate. Keep the headband still and
well seated while it does so.

   The project `.env` sets `MUSE_ADDRESS` to the discovered headband, so the
   address argument is optional. A shell `MUSE_ADDRESS` value or `--address`
   overrides it.

## Project commands

```bash
uv sync
uv run python muse_monitor.py --address AA:BB:CC:DD:EE:FF
```

`uv` created `.venv` and locks the resolved dependencies in `uv.lock`; do not
activate the environment manually to run this project.

## How it works

The script starts Muse LSL as a managed child process with EEG and PPG enabled.
Muse LSL turns the Bluetooth data into local Lab Streaming Layer (LSL) streams.
The plotting process consumes their `EEG` and `PPG` streams. This separation
also allows the display to attach to BlueMuse or a separately started
`muselsl stream --ppg` process:

```bash
uv run python muse_monitor.py --external-lsl
```

Close the graph window or press `Ctrl+C` to stop the monitor. It terminates the
Muse LSL child process rather than leaving a background BLE connection running.

See [connection notes](docs/connection.md) and
[API and signal-processing notes](docs/api-and-signals.md) for the researched
details and source links.
