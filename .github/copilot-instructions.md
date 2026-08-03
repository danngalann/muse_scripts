# Copilot instructions

## Project

- This is a Python 3.12 project managed with `uv`; use `uv run` for project
  commands and keep dependency changes in `pyproject.toml` and `uv.lock`.
- `muse_monitor.py` starts a Muse LSL child process, reads local LSL `EEG` and
  `PPG` streams, and displays live signals with Matplotlib.
- The default Muse Bluetooth address is configured in `.env` as
  `MUSE_ADDRESS`. Do not replace it with a hard-coded value.
- EEG state labels and PPG heart rate are descriptive heuristics only. Preserve
  their non-clinical wording and document any changes to their signal
  processing in `docs/api-and-signals.md`.

## Changes and commits

- Keep changes focused and validate them with targeted `uv run` commands.
- Write short, imperative commit subjects, for example `Add EEG band display`.
- Never add a `Co-authored-by` trailer to commits.
