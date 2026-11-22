"""
sim/pvgroups/beam.py
--------------------
A simulated beam for the scaler and the Xspress3: the intensity changes slowly with time, and the sample
signals now and then show an event, so that the signals and their ratios move when someone watches them.

* :meth:`BeamModel.intensity` is the relative intensity of the beam (about 1): a 2 % oscillation
  with a period of about 97 s, a 0.6 % one of about 13 s and a 1 % drift over about 10 min. The
  scaler's I0, PD and TEY and the Xspress3's spectrum are all proportional to it, so a ratio to I0 stays
  flat.
* :meth:`BeamModel.tey_gain` and :meth:`BeamModel.pd_gain` multiply the sample drain current (TEY) and the
  photodiode (PD). Both are 1 (the flat backgrounds of TEY/I0 and PD/I0) except during an event, a Gaussian
  in time. At its top TEY is 2 to 7 times its background and PD is 10 to 80 % below its own: a stronger
  absorption raises the drain current and lowers the transmission at once, so the two are tied (the depth of
  the dip grows linearly with the height of the peak). Events never overlap (the next one comes no sooner than
  two widths after the last) and follow a random schedule with a mean gap. There are two schedules:

  - **idle**, the beamline is not scanning (the Counter, or nothing running): an event about every
    30 s, 6 s wide (full width at half maximum);
  - **scan**, the mono is flying: an event about every 6 min, 100 s wide, which is 10 eV at the
    preset velocity of 0.1 eV/s.

A later version replaces the events in time with an absorption edge that depends on the energy.

Settings (environment): ``IOS_SIM_SEED`` (an integer; the default is the time at the start, which
the IOC logs), ``IOS_SIM_PEAK_GAP_IDLE`` / ``IOS_SIM_PEAK_FWHM_IDLE`` (30 / 6 s),
``IOS_SIM_PEAK_GAP_SCAN`` / ``IOS_SIM_PEAK_FWHM_SCAN`` (360 / 100 s). A gap of 0 or less switches
the events of that schedule off.
"""

from __future__ import annotations

import bisect
import logging
import math
import os
import time
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("ios.sim")

FWHM_TO_SIGMA = 1.0 / (2.0 * math.sqrt(2.0 * math.log(2.0)))
PEAK_HEIGHTS = (2.0, 7.0)  # TEY at the top of an event, times its background
DIP_DEPTHS = (0.10, 0.80)  # PD below its background at the top, tied to the height of the TEY peak
IDLE, SCAN = "idle", "scan"

# (relative amplitude, period in seconds)
OSCILLATIONS = ((0.02, 97.0), (0.006, 13.0), (0.01, 600.0))


@dataclass(frozen=True)
class PeakSchedule:
    """How often and how wide the TEY peaks and PD dips are in one situation."""

    gap: float
    fwhm: float

    @property
    def enabled(self) -> bool:
        return self.gap > 0 and self.fwhm > 0


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        log.warning("%s is not a number; using %s", name, default)
        return default


def schedules_from_environment() -> dict[str, PeakSchedule]:
    return {
        IDLE: PeakSchedule(_float_env("IOS_SIM_PEAK_GAP_IDLE", 30.0), _float_env("IOS_SIM_PEAK_FWHM_IDLE", 6.0)),
        SCAN: PeakSchedule(_float_env("IOS_SIM_PEAK_GAP_SCAN", 360.0), _float_env("IOS_SIM_PEAK_FWHM_SCAN", 100.0)),
    }


class _Peaks:
    """The peaks of one schedule, drawn in order from their own random stream as time passes."""

    def __init__(self, schedule: PeakSchedule, rng: np.random.Generator):
        self.schedule = schedule
        self._rng = rng
        self.centers: list[float] = []
        self.heights: list[float] = []

    def _extend(self, until: float) -> None:
        sigma = self.schedule.fwhm * FWHM_TO_SIGMA
        minimum = 2.0 * self.schedule.fwhm
        mean_extra = max(self.schedule.gap - minimum, 0.0)
        while not self.centers or self.centers[-1] < until + 5.0 * sigma:
            last = self.centers[-1] if self.centers else 0.0
            extra = self._rng.exponential(mean_extra) if mean_extra > 0 else 0.0
            self.centers.append(last + minimum + extra)
            self.heights.append(float(self._rng.uniform(*PEAK_HEIGHTS)))

    def effects(self, t: float) -> tuple[float, float]:
        """The gains of TEY and of PD at ``t``: (peak, dip), both 1 when no event is near."""
        if not self.schedule.enabled:
            return 1.0, 1.0
        self._extend(t)
        sigma = self.schedule.fwhm * FWHM_TO_SIGMA
        index = bisect.bisect_left(self.centers, t)
        tey, pd = 1.0, 1.0
        low, high = PEAK_HEIGHTS
        for k in (index - 1, index):
            if 0 <= k < len(self.centers):
                weight = math.exp(-0.5 * ((t - self.centers[k]) / sigma) ** 2)
                height = self.heights[k]
                depth = DIP_DEPTHS[0] + (DIP_DEPTHS[1] - DIP_DEPTHS[0]) * (height - low) / (high - low)
                tey += (height - 1.0) * weight
                pd -= depth * weight
        return tey, max(pd, 0.02)


class BeamModel:
    """The intensity of the simulated beam and the TEY peaks and PD dips, as functions of the time in seconds."""

    def __init__(self, seed: int | None = None, schedules: dict[str, PeakSchedule] | None = None):
        self.seed = int(time.time()) if seed is None else int(seed)
        schedules = schedules if schedules is not None else schedules_from_environment()
        phases = np.random.default_rng([self.seed, 0]).uniform(0.0, 2.0 * math.pi, len(OSCILLATIONS))
        self._phases = [float(p) for p in phases]
        self._peaks = {
            IDLE: _Peaks(schedules[IDLE], np.random.default_rng([self.seed, 1])),
            SCAN: _Peaks(schedules[SCAN], np.random.default_rng([self.seed, 2])),
        }

    def intensity(self, t: float) -> float:
        return 1.0 + sum(
            amplitude * math.sin(2.0 * math.pi * t / period + phase)
            for (amplitude, period), phase in zip(OSCILLATIONS, self._phases)
        )

    def tey_gain(self, t: float, scanning: bool = False) -> float:
        return self._peaks[SCAN if scanning else IDLE].effects(t)[0]

    def pd_gain(self, t: float, scanning: bool = False) -> float:
        return self._peaks[SCAN if scanning else IDLE].effects(t)[1]


_START = time.monotonic()
_beam: BeamModel | None = None
_scanning = False


def now() -> float:
    """Seconds since the IOC started."""
    return time.monotonic() - _START


def get_beam() -> BeamModel:
    global _beam
    if _beam is None:
        seed = os.environ.get("IOS_SIM_SEED")
        _beam = BeamModel(int(seed) if seed else None)
        log.info("SIM: beam model seed %d (set IOS_SIM_SEED to repeat it)", _beam.seed)
    return _beam


def set_scanning(value: bool) -> None:
    """The mono fly sets this while a scan runs, which picks the peak schedule."""
    global _scanning
    _scanning = bool(value)


def is_scanning() -> bool:
    return _scanning


def intensity() -> float:
    return get_beam().intensity(now())


def pd_gain() -> float:
    return get_beam().pd_gain(now(), _scanning)


def tey_gain() -> float:
    return get_beam().tey_gain(now(), _scanning)
