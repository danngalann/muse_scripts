# API and signal-processing notes

## Streams provided by Muse LSL

For a Muse 2, enabling `ppg_enabled=True` creates separate local LSL streams:

| LSL type | Channels used here | Nominal rate | Purpose |
| --- | --- | ---: | --- |
| `EEG` | TP9, AF7, AF8, TP10 | 256 Hz | Live EEG plot |
| `PPG` | PPG1, PPG2, PPG3 | 64 Hz | Optical pulse signal |

Muse LSL's current source declares a fifth EEG channel (`Right AUX`), but this
monitor intentionally displays the standard four headband electrodes. Its
source also labels `PPG2` as infrared; that is the channel this monitor uses
for its pulse estimate. PPG values are raw optical samples. Muse LSL's LSL
metadata calls their unit `mmHg`, but the decoder does not calibrate them to
pressure, so this project treats them only as a waveform.

The program resolves streams using `pylsl.resolve_byprop("type", ...)`, creates
`StreamInlet` objects, and calls `pull_chunk()` every 50 ms. LSL buffers and
time-synchronizes the samples, while the plot only retains a short rolling
window for responsiveness.

## Heart-rate estimate

The PPG estimate is deliberately simple and visible:

1. Retain the latest 12 seconds of PPG2 (infrared) data.
2. Remove the DC component and apply a 0.5–4 Hz band-pass filter, corresponding
   approximately to 30–240 BPM.
3. Normalize the signal and use SciPy `find_peaks` with a 0.3-second minimum
   peak separation (maximum 200 BPM).
4. Reject implausible 0.3–2.0 second beat intervals, then calculate BPM from
   their median.
5. Report a signal-confidence value from the interval variability.

This is a convenience estimate, not a validated clinical measurement. Movement,
loose sensor contact, skin/hair interference, and ambient light can produce an
incorrect rate. Do not use it for medical decisions.

## Sources

- Muse LSL README and source:
  <https://github.com/alexandrebarachant/muse-lsl>
- Muse LSL `muse.py` stream descriptors and Bluetooth characteristics:
  <https://github.com/alexandrebarachant/muse-lsl/blob/master/muselsl/muse.py>
- Muse LSL `constants.py` (256 Hz EEG, 64 Hz PPG and PPG channel roles):
  <https://github.com/alexandrebarachant/muse-lsl/blob/master/muselsl/constants.py>
- SciPy peak finder reference:
  <https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.find_peaks.html>
