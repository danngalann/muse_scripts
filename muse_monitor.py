"""Display live EEG and a PPG-derived heart-rate estimate from a Muse 2."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from pylsl import StreamInlet, resolve_byprop
from scipy.signal import butter, find_peaks, sosfiltfilt, welch

EEG_CHANNELS = ("TP9", "AF7", "AF8", "TP10")
EEG_RATE = 256
PPG_RATE = 64
EEG_ANALYSIS_SECONDS = 8
EEG_BAND_HISTORY_INTERVAL = 0.5
EEG_BANDS = {
    "theta": (4.0, 8.0),
    "alpha": (8.0, 12.0),
    "beta": (13.0, 30.0),
}
LOGGER = logging.getLogger(__name__)


def load_project_environment() -> None:
    """Load project defaults without overriding values supplied by the shell."""
    environment_file = Path(__file__).with_name(".env")
    if not environment_file.exists():
        return

    for line in environment_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class HeartRate:
    bpm: float | None
    confidence: float


@dataclass
class EegState:
    label: str
    detail: str
    band_power: dict[str, float] | None


def estimate_eeg_state(samples: np.ndarray) -> EegState:
    """Classify the dominant theta/alpha/beta pattern in a recent EEG window."""
    required_samples = EEG_ANALYSIS_SECONDS * EEG_RATE
    if len(samples) < required_samples:
        return EegState(
            "Acquiring EEG",
            f"Need {EEG_ANALYSIS_SECONDS} seconds of clean EEG data.",
            None,
        )

    window = samples[-required_samples:].astype(float)
    if np.max(np.abs(window)) > 900:
        return EegState(
            "Signal artifact",
            "Large signal excursion; adjust the headband or keep still.",
            None,
        )

    frequencies, spectrum = welch(
        window.T, fs=EEG_RATE, nperseg=EEG_RATE * 2, axis=-1
    )
    power = {}
    for name, (low, high) in EEG_BANDS.items():
        band = (frequencies >= low) & (frequencies < high)
        power[name] = float(np.mean(np.trapezoid(spectrum[:, band], frequencies[band])))

    total_power = sum(power.values())
    if total_power <= 0:
        return EegState("Signal unavailable", "No usable EEG band power.", None)

    relative_power = {name: value / total_power for name, value in power.items()}
    theta = relative_power["theta"]
    alpha = relative_power["alpha"]
    beta = relative_power["beta"]

    if alpha > beta * 1.25 and alpha > theta * 1.1:
        return EegState(
            "Alpha-dominant (relaxed-like)",
            "Alpha power is strongest in this window.",
            relative_power,
        )
    if beta > alpha * 1.25 and beta > theta * 1.1:
        return EegState(
            "Beta-dominant (alert-like)",
            "Beta power is strongest in this window.",
            relative_power,
        )
    if theta > alpha * 1.25 and theta > beta * 1.1:
        return EegState(
            "Theta-dominant",
            "Theta power is strongest in this window.",
            relative_power,
        )
    return EegState(
        "Indeterminate / mixed",
        "No theta, alpha, or beta pattern is clearly dominant.",
        relative_power,
    )


def estimate_heart_rate(samples: np.ndarray) -> HeartRate:
    """Estimate pulse rate from 12 seconds of the Muse 2 infrared PPG signal."""
    if len(samples) < PPG_RATE * 8:
        return HeartRate(None, 0.0)

    signal = samples[-PPG_RATE * 12 :].astype(float)
    signal -= np.mean(signal)
    filtered = sosfiltfilt(
        butter(3, (0.5, 4.0), btype="bandpass", fs=PPG_RATE, output="sos"),
        signal,
    )
    scale = np.std(filtered)
    if scale == 0:
        return HeartRate(None, 0.0)

    normalized = filtered / scale
    peaks, _ = find_peaks(
        normalized,
        distance=int(PPG_RATE * 0.3),  # Do not accept rates above 200 BPM.
        prominence=0.35,
    )
    intervals = np.diff(peaks) / PPG_RATE
    intervals = intervals[(intervals >= 0.3) & (intervals <= 2.0)]
    if len(intervals) < 3:
        return HeartRate(None, 0.0)

    median_interval = float(np.median(intervals))
    bpm = 60.0 / median_interval
    variation = float(np.std(intervals) / median_interval)
    confidence = max(0.0, min(1.0, 1.0 - variation / 0.2))
    return HeartRate(bpm, confidence)


class MuseMonitor:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.eeg: deque[np.ndarray] = deque(
            maxlen=max(int(args.window * EEG_RATE), EEG_ANALYSIS_SECONDS * EEG_RATE)
        )
        self.ppg: deque[float] = deque(maxlen=PPG_RATE * 20)
        self.eeg_inlet: StreamInlet | None = None
        self.ppg_inlet: StreamInlet | None = None
        self.connection_error: str | None = None
        self.received_eeg = False
        self.received_ppg = False
        self.animation: FuncAnimation | None = None
        self.bridge: subprocess.Popen[bytes] | None = None
        self.band_history: dict[str, deque[float]] = {
            name: deque(maxlen=600) for name in EEG_BANDS
        }
        self.band_timestamps: deque[float] = deque(maxlen=600)
        self.last_band_history_update = 0.0
        self.started_at = time.monotonic()

    def start_bridge(self) -> None:
        if self.args.external_lsl:
            return

        command = [
            sys.executable,
            "-m",
            "muselsl",
            "stream",
            "--ppg",
            "--lsltime",
            "--retries",
            "-1",
            "--backend",
            self.args.backend,
        ]
        if self.args.address:
            command.extend(("--address", self.args.address))
        if self.args.name:
            command.extend(("--name", self.args.name))
        self.bridge = subprocess.Popen(command)

    def stop_bridge(self) -> None:
        if self.bridge is None or self.bridge.poll() is not None:
            return

        LOGGER.info("Stopping Muse LSL bridge.")
        self.bridge.terminate()
        try:
            self.bridge.wait(timeout=3)
        except subprocess.TimeoutExpired:
            LOGGER.warning("Muse LSL bridge did not stop; killing it.")
            self.bridge.kill()
            self.bridge.wait()

    @staticmethod
    def _find_inlet(stream_type: str) -> StreamInlet | None:
        matches = resolve_byprop("type", stream_type, timeout=0.1)
        if matches:
            return StreamInlet(matches[0], max_buflen=2, max_chunklen=0)
        return None

    def _read_streams(self) -> None:
        if self.bridge is not None and self.bridge.poll() is not None:
            self.connection_error = (
                f"Muse LSL bridge stopped (exit code {self.bridge.returncode})."
            )
            return

        if self.eeg_inlet is None:
            self.eeg_inlet = self._find_inlet("EEG")
        if self.ppg_inlet is None:
            self.ppg_inlet = self._find_inlet("PPG")

        if self.eeg_inlet is not None:
            samples, _ = self.eeg_inlet.pull_chunk(timeout=0.0, max_samples=256)
            if samples and not self.received_eeg:
                self.received_eeg = True
                LOGGER.info("Receiving EEG samples.")
            self.eeg.extend(np.asarray(sample[:4]) for sample in samples)
        if self.ppg_inlet is not None:
            samples, _ = self.ppg_inlet.pull_chunk(timeout=0.0, max_samples=64)
            if samples and not self.received_ppg:
                self.received_ppg = True
                LOGGER.info("Receiving PPG samples.")
            # Muse LSL labels PPG2 as the infrared channel, used for pulse detection.
            self.ppg.extend(float(sample[1]) for sample in samples)

    def record_band_power(self, band_power: dict[str, float]) -> None:
        """Add one spectral observation at a fixed cadence for the band chart."""
        now = time.monotonic()
        if now - self.last_band_history_update < EEG_BAND_HISTORY_INTERVAL:
            return

        self.last_band_history_update = now
        self.band_timestamps.append(now - self.started_at)
        for name, value in band_power.items():
            self.band_history[name].append(value)

    def run(self) -> None:
        self.start_bridge()
        figure, (eeg_axis, ppg_axis) = plt.subplots(
            2, 1, figsize=(12, 7), height_ratios=(3, 1), sharex=True
        )
        band_figure, band_axis = plt.subplots(figsize=(10, 5))
        if figure.canvas.manager is not None:
            figure.canvas.manager.set_window_title("Muse 2 live monitor")
        if band_figure.canvas.manager is not None:
            band_figure.canvas.manager.set_window_title("Muse 2 EEG band power")
        eeg_lines = [
            eeg_axis.plot([], [], linewidth=0.8, label=channel)[0]
            for channel in EEG_CHANNELS
        ]
        ppg_line = ppg_axis.plot([], [], linewidth=0.8, color="tab:red")[0]
        heart_rate_text = ppg_axis.text(
            0.01, 0.88, "Heart rate: waiting for PPG...", transform=ppg_axis.transAxes
        )
        state_text = eeg_axis.text(
            0.01,
            0.97,
            "EEG state heuristic: acquiring data...",
            transform=eeg_axis.transAxes,
            verticalalignment="top",
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8},
        )
        band_lines = {
            "theta": band_axis.plot([], [], label="Theta (4-8 Hz)", color="tab:purple")[0],
            "alpha": band_axis.plot([], [], label="Alpha (8-12 Hz)", color="tab:green")[0],
            "beta": band_axis.plot([], [], label="Beta (13-30 Hz)", color="tab:orange")[0],
        }
        band_waiting_text = band_axis.text(
            0.5,
            0.5,
            "Waiting for 8 seconds of EEG...",
            transform=band_axis.transAxes,
            horizontalalignment="center",
        )

        eeg_axis.set_ylabel("EEG (microvolts)")
        eeg_axis.legend(loc="upper right", ncols=4)
        eeg_axis.grid(alpha=0.3)
        eeg_axis.set_title("Waiting for the Muse EEG LSL stream...")
        ppg_axis.set_ylabel("PPG2 (IR)")
        ppg_axis.set_xlabel("Seconds ago")
        ppg_axis.grid(alpha=0.3)
        eeg_axis.set_xlim(-self.args.window, 0)
        ppg_axis.set_xlim(-self.args.window, 0)
        band_axis.set_title("Relative EEG band power")
        band_axis.set_xlabel("Seconds since monitor started")
        band_axis.set_ylabel("Relative power")
        band_axis.set_ylim(0, 1)
        band_axis.grid(alpha=0.3)
        band_axis.legend(loc="upper right")
        band_figure.text(
            0.5,
            0.02,
            "Theta: often drowsiness or internal attention.  "
            "Alpha: often relaxed wakefulness.  "
            "Beta: often alert, active cognition.  "
            "These patterns are non-specific and not diagnostic.",
            horizontalalignment="center",
            wrap=True,
        )
        band_figure.subplots_adjust(bottom=0.2)

        def update(_: int) -> list:
            try:
                self._read_streams()
            except KeyboardInterrupt:
                LOGGER.info("Interrupted; closing monitor.")
                self.stop_bridge()
                plt.close(figure)
                return []

            if self.eeg:
                data = np.asarray(self.eeg)
                x_values = np.linspace(-len(data) / EEG_RATE, 0, len(data))
                for index, line in enumerate(eeg_lines):
                    line.set_data(x_values, data[:, index])
                eeg_axis.relim()
                eeg_axis.autoscale_view(scalex=False, scaley=True)
                eeg_axis.set_title("Live EEG")
                eeg_state = estimate_eeg_state(data)
                state_message = f"EEG state heuristic: {eeg_state.label}"
                if eeg_state.band_power:
                    self.record_band_power(eeg_state.band_power)
                    state_message += " | " + ", ".join(
                        f"{name} {value:.0%}"
                        for name, value in eeg_state.band_power.items()
                    )
                state_text.set_text(state_message)
            elif self.connection_error:
                eeg_axis.set_title(self.connection_error)

            if self.ppg:
                data = np.asarray(self.ppg)
                x_values = np.linspace(-len(data) / PPG_RATE, 0, len(data))
                ppg_line.set_data(x_values, data)
                ppg_axis.relim()
                ppg_axis.autoscale_view(scalex=False, scaley=True)
                heart_rate = estimate_heart_rate(data)
                if heart_rate.bpm is None:
                    heart_rate_text.set_text("Heart rate: acquiring a clean PPG signal...")
                else:
                    heart_rate_text.set_text(
                        f"Heart rate: {heart_rate.bpm:.0f} BPM "
                        f"(signal confidence {heart_rate.confidence:.0%})"
                    )
            elif self.connection_error:
                heart_rate_text.set_text(self.connection_error)
            else:
                heart_rate_text.set_text("Waiting for EEG and PPG LSL streams...")

            if self.band_timestamps:
                timestamps = np.asarray(self.band_timestamps)
                for name, line in band_lines.items():
                    line.set_data(timestamps, self.band_history[name])
                band_axis.set_xlim(max(0, timestamps[-1] - 300), max(10, timestamps[-1]))
                band_waiting_text.set_visible(False)
                band_figure.canvas.draw_idle()

            return [
                *eeg_lines,
                ppg_line,
                heart_rate_text,
                state_text,
                *band_lines.values(),
                band_waiting_text,
            ]

        figure.tight_layout()
        self.animation = FuncAnimation(
            figure, update, interval=50, blit=False, cache_frame_data=False
        )
        try:
            plt.show()
        except KeyboardInterrupt:
            LOGGER.info("Interrupted; closing monitor.")
        finally:
            self.stop_bridge()


def parse_args() -> argparse.Namespace:
    load_project_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--address",
        default=os.environ.get("MUSE_ADDRESS"),
        help="Muse Bluetooth MAC address (skips discovery; default: MUSE_ADDRESS).",
    )
    parser.add_argument("--name", help="Muse BLE name, for example Muse-41D2.")
    parser.add_argument(
        "--backend",
        default="auto",
        choices=("auto", "bleak", "gatt", "bgapi", "bluemuse"),
        help="Muse LSL Bluetooth backend (default: auto).",
    )
    parser.add_argument(
        "--external-lsl",
        action="store_true",
        help="Use existing EEG and PPG LSL streams instead of making a BLE connection.",
    )
    parser.add_argument(
        "--window", type=float, default=10.0, help="Visible EEG window in seconds."
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    MuseMonitor(parse_args()).run()


if __name__ == "__main__":
    main()
