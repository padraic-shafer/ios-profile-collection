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
  - **scan**, the mono is flying: off by default (gap 0), because a scan has its absorption edge instead.
* An **absorption edge** while the mono flies (:meth:`BeamModel.edge_gains`): a step with a small white line,
  a function of the energy. Its position is a fraction of the fly range (40 % from the low end by default), or,
  when ``IOS_SIM_EDGE_TABLE=1``, the lowest edge of a table of real edge energies (:data:`REAL_EDGES`) that lies
  inside the range. At the edge PD/I0 falls (transmission), TEY/I0 rises, ROI 4 (the resonant line, PFY) rises
  and ROI 3 (the non-resonant line) dips, so that IPFY = I0/ROI 3 rises: the same absorption, seen four ways.
  Outside a scan the edge is not applied, so the Counter stays flat except for its events.

Settings (environment): ``IOS_SIM_SEED`` (an integer; the default is the time at the start, which
the IOC logs), ``IOS_SIM_PEAK_GAP_IDLE`` / ``IOS_SIM_PEAK_FWHM_IDLE`` (30 / 6 s),
``IOS_SIM_PEAK_GAP_SCAN`` / ``IOS_SIM_PEAK_FWHM_SCAN`` (0 / 100 s). A gap of 0 or less switches
the events of that schedule off. ``IOS_SIM_EDGE_FRACTION`` (0.4), ``IOS_SIM_EDGE_WIDTH`` (eV; 0 is
3 % of the fly range, at least 0.2), ``IOS_SIM_EDGE_TABLE`` (0; 1 uses real edge energies).
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

# The edge: how far each signal moves at the top of the absorption (a = 1), as a factor on its background.
PD_ABSORPTION = 0.9  # PD x exp(-0.9 a): the transmission falls
TEY_RISE = 2.0  # TEY x (1 + 2 a)
ROI4_RISE = 3.0  # the resonant line x (1 + 3 a)
ROI3_DIP = 1.5  # the non-resonant line / (1 + 1.5 a), so that I0/ROI 3 is 1 + 1.5 a
WHITE_LINE = 0.6  # a small peak on the step, 1.5 widths above the edge

# L-edge (and a few K-edge) energies in eV, for IOS_SIM_EDGE_TABLE=1.
REAL_EDGES = {
    "C K": 284.2, "Ca L3": 346.2, "Sc L3": 398.7, "N K": 409.9, "Ti L3": 453.8, "V L3": 512.1, "O K": 543.1,
    "Cr L3": 574.1, "Mn L3": 638.7, "Fe L3": 706.8, "Co L3": 778.1, "Ni L3": 852.7, "Cu L3": 932.7,
    "Zn L3": 1021.8, "Mg K": 1303.0, "Al K": 1559.6,
}

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
        SCAN: PeakSchedule(_float_env("IOS_SIM_PEAK_GAP_SCAN", 0.0), _float_env("IOS_SIM_PEAK_FWHM_SCAN", 100.0)),
    }


@dataclass(frozen=True)
class EdgeSettings:
    """Where the absorption edge of a scan is: a fraction of the fly range, or a real edge energy."""

    fraction: float = 0.4
    width: float = 0.0  # eV; 0 is 3 % of the fly range
    use_table: bool = False


@dataclass(frozen=True)
class EdgeGains:
    """Factors on the backgrounds of the signals at one energy; all 1 away from a scan."""

    pd: float = 1.0
    tey: float = 1.0
    roi3: float = 1.0
    roi4: float = 1.0


def edge_from_environment() -> EdgeSettings:
    return EdgeSettings(
        fraction=min(max(_float_env("IOS_SIM_EDGE_FRACTION", 0.4), 0.0), 1.0),
        width=max(_float_env("IOS_SIM_EDGE_WIDTH", 0.0), 0.0),
        use_table=_float_env("IOS_SIM_EDGE_TABLE", 0.0) > 0,
    )


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

    def __init__(
        self,
        seed: int | None = None,
        schedules: dict[str, PeakSchedule] | None = None,
        edge: EdgeSettings | None = None,
    ):
        self.seed = int(time.time()) if seed is None else int(seed)
        schedules = schedules if schedules is not None else schedules_from_environment()
        self.edge = edge if edge is not None else edge_from_environment()
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

    def edge_energy(self, low: float, high: float) -> float:
        """Where the edge is for a fly from ``low`` to ``high`` eV (either order)."""
        low, high = min(low, high), max(low, high)
        if self.edge.use_table:
            margin = 0.1 * (high - low)
            inside = sorted(e for e in REAL_EDGES.values() if low + margin <= e <= high - margin)
            if inside:
                return inside[0]
        return low + self.edge.fraction * (high - low)

    def absorption(self, energy: float, low: float, high: float) -> float:
        """The absorption at ``energy``: 0 well below the edge, 1 well above it, and a white line on the step."""
        width = self.edge.width if self.edge.width > 0 else max(0.03 * abs(high - low), 0.2)
        edge = self.edge_energy(low, high)
        step = 0.5 * (1.0 + math.erf((energy - edge) / (math.sqrt(2.0) * width)))
        line = WHITE_LINE * math.exp(-0.5 * ((energy - edge - 1.5 * width) / (1.2 * width)) ** 2)
        return step + line

    def edge_gains(self, energy: float, low: float, high: float) -> EdgeGains:
        a = self.absorption(energy, low, high)
        return EdgeGains(
            pd=math.exp(-PD_ABSORPTION * a),
            tey=1.0 + TEY_RISE * a,
            roi3=1.0 / (1.0 + ROI3_DIP * a),
            roi4=1.0 + ROI4_RISE * a,
        )


_START = time.monotonic()
_beam: BeamModel | None = None
_scanning = False
_fly_range: tuple[float, float] | None = None
_energy = 0.0


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


def set_fly_range(low: float, high: float) -> None:
    """The mono fly sets the range it flies over, which is where the edge is."""
    global _fly_range
    _fly_range = (float(low), float(high))


def set_energy(energy: float) -> None:
    """The mono sets its energy readback here."""
    global _energy
    _energy = float(energy)


def edge_gains() -> EdgeGains:
    """The factors of the edge at the mono's energy; all 1 unless the mono is flying."""
    if not _scanning or _fly_range is None:
        return EdgeGains()
    return get_beam().edge_gains(_energy, *_fly_range)


def intensity() -> float:
    return get_beam().intensity(now())


def pd_gain() -> float:
    return get_beam().pd_gain(now(), _scanning)


def tey_gain() -> float:
    return get_beam().tey_gain(now(), _scanning)
