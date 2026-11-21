"""Offline checks of the simulated beam (sim/pvgroups/beam.py) and what is built on it: the scaler's PD and I0,
the Xspress3's spectrum and its starting ROI windows. No IOC is started.

The ``qs-sim`` environment has no pytest, so the file also runs as a script,

    pixi run -e qs-sim python acceptance_tests/test_sim_beam.py

and pytest collects the same functions where it is installed.
"""

import asyncio
import pathlib
import sys
import traceback

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.pvgroups import beam  # noqa: E402

SCHEDULES = {
    beam.IDLE: beam.PeakSchedule(gap=30.0, fwhm=6.0),
    beam.SCAN: beam.PeakSchedule(gap=360.0, fwhm=100.0),
}


def model(seed=7, schedules=None):
    return beam.BeamModel(seed=seed, schedules=schedules or SCHEDULES)


def gains(m, seconds, step, scanning):
    times = np.arange(0.0, seconds, step)
    return times, np.array([m.pd_gain(t, scanning) for t in times])


def test_the_intensity_changes_slowly_and_by_a_few_percent():
    m = model()
    values = np.array([m.intensity(t) for t in np.arange(0.0, 1200.0, 1.0)])
    assert 0.95 < values.min() and values.max() < 1.05
    assert values.std() > 0.005  # it does change
    assert abs(m.intensity(10.0) - m.intensity(10.5)) < 0.01  # and it is smooth


def test_the_same_seed_gives_the_same_beam_and_another_seed_another():
    a, b, c = model(1), model(1), model(2)
    assert [a.intensity(t) for t in (3.0, 50.0)] == [b.intensity(t) for t in (3.0, 50.0)]
    assert [a.pd_gain(t) for t in range(0, 600, 3)] == [b.pd_gain(t) for t in range(0, 600, 3)]
    assert [a.pd_gain(t) for t in range(0, 600, 3)] != [c.pd_gain(t) for t in range(0, 600, 3)]


def test_the_pd_is_flat_except_in_peaks_that_reach_two_to_seven_times_the_background():
    m = model()
    _, g = gains(m, 3600.0, 0.25, scanning=False)
    assert g.min() >= 1.0 and g.min() < 1.0 + 1e-6  # the flat background is exactly 1
    assert 2.0 <= g.max() <= 7.01
    peaks = m._peaks[beam.IDLE]
    assert all(2.0 <= h <= 7.0 for h in peaks.heights)
    assert max(peaks.heights) > 5.0 and min(peaks.heights) < 3.0  # the heights are spread over the range


def test_the_peaks_come_at_the_mean_gap_and_never_overlap():
    m = model()
    for mode, expected_gap, fwhm in ((beam.IDLE, 30.0, 6.0), (beam.SCAN, 360.0, 100.0)):
        m.pd_gain(200_000.0, scanning=mode == beam.SCAN)  # draw about 6000 idle peaks
        peaks = m._peaks[mode]
        gaps = np.diff(peaks.centers)
        assert gaps.min() >= 2.0 * fwhm - 1e-9, mode
        assert abs(gaps.mean() - expected_gap) < 0.1 * expected_gap, (mode, gaps.mean())


def test_a_scan_peak_is_ten_ev_wide_at_the_preset_velocity():
    m = model()
    peaks = m._peaks[beam.SCAN]
    m.pd_gain(2000.0, scanning=True)
    center, height = peaks.centers[0], peaks.heights[0]
    half = 1.0 + (height - 1.0) / 2.0
    velocity = 0.1  # eV/s, the preset's
    assert abs(m.pd_gain(center - 50.0, True) - half) < 0.02 * height
    assert abs(m.pd_gain(center + 50.0, True) - half) < 0.02 * height
    assert abs(2 * 50.0 * velocity - 10.0) < 1e-9


def test_a_schedule_with_no_gap_has_no_peaks():
    m = model(schedules={beam.IDLE: beam.PeakSchedule(0.0, 6.0), beam.SCAN: beam.PeakSchedule(360.0, 100.0)})
    _, g = gains(m, 600.0, 1.0, scanning=False)
    assert (g == 1.0).all()


def test_the_scanning_flag_picks_the_schedule():
    beam.set_scanning(True)
    assert beam.is_scanning()
    beam.set_scanning(False)
    assert not beam.is_scanning()


def test_the_xspress3_rois_start_around_the_two_lines_and_the_third_and_fourth_only():
    from sim.pvgroups import xspress3

    assert xspress3.roi_window_default("MCA1ROI:4:MinX") == 775
    assert xspress3.roi_window_default("MCA1ROI:4:SizeX_RBV") == 90
    assert xspress3.roi_window_default("MCA1ROI:3:MinX_RBV") == 414
    assert xspress3.roi_window_default("MCA1ROI:3:SizeX") == 72
    assert xspress3.roi_window_default("MCA1ROI:1:MinX") is None
    assert xspress3.roi_window_default("MCA1ROI:4:Total_RBV") is None
    assert xspress3.roi_window_default("det1:Acquire") is None

    spectrum = xspress3.spectrum(0.5, np.random.default_rng(3))
    for roi, empty_start in ((4, 2000), (3, 2000)):
        low, size = xspress3.ROI_WINDOWS[roi]
        assert spectrum[low : low + size].sum() > 10 * spectrum[empty_start : empty_start + size].sum()


def test_the_spectrum_scales_with_the_beam_intensity():
    from sim.pvgroups import xspress3

    low = xspress3.spectrum(1.0, np.random.default_rng(5), 0.5).sum()
    high = xspress3.spectrum(1.0, np.random.default_rng(5), 1.5).sum()
    assert 2.5 < high / low < 3.5


def test_the_scaler_pd_and_i0_follow_the_beam_and_their_ratio_stays_flat():
    from sim.pvgroups.scaler_signals import ScalerIOC

    beam._beam = model()
    beam.set_scanning(False)
    ioc = ScalerIOC(prefix="X{{Sclr:1}}")

    async def counts():
        rows = []
        for _ in range(60):
            await ioc._fill(0.5)
            rows.append((ioc.S2.value, ioc.S3.value, ioc.S1.value))
        return np.array(rows, dtype=float)

    rows = asyncio.run(counts())
    pd, i0, clock = rows.T
    assert (clock == 0.5 * ioc.FREQ.value).all()
    assert (i0 > 50_000).all() and (pd > 30_000).all()
    ratio = pd / i0
    assert ratio.std() / ratio.mean() < 0.05  # flat, apart from the noise and the peaks of PD


def _flying_mono():
    from sim.pvgroups.positioners import PGMEnergyIOC

    return PGMEnergyIOC(prefix="")


def test_a_new_energy_setpoint_ends_a_fly_where_it_is_and_the_scan_schedule_with_it():
    ioc = _flying_mono()

    async def run():
        await ioc.fly_start_sp.write(400.0)
        await ioc.fly_stop_sp.write(800.0)
        await ioc.fly_velo.write(1.0)  # 400 s if it were not stopped
        ioc._flying = True
        await ioc.scan_sts.write(1)
        task = asyncio.ensure_future(ioc._fly())
        await asyncio.sleep(0.6)
        assert beam.is_scanning()
        where = ioc.enrgy_i.value
        await ioc.enrgy_sp.pvspec.put(ioc, ioc.enrgy_sp, where)  # E_ramp's clean-up after a stop
        await asyncio.wait_for(task, 2.0)
        return where

    where = asyncio.run(run())
    assert not beam.is_scanning()
    assert ioc._flying is False and ioc.scan_sts.value in (0, "Ready")
    assert 400.0 < where < 410.0 and abs(ioc.enrgy_i.value - where) < 1e-6  # it stopped where it was


def test_the_stop_commands_end_a_fly_and_do_nothing_when_there_is_none():
    for command in ("stop_cmd", "fly_stop_cmd"):
        ioc = _flying_mono()
        ioc._stop_fly()  # nothing is flying
        assert not getattr(ioc, "_stop_requested", False)

        async def run():
            await ioc.fly_start_sp.write(400.0)
            await ioc.fly_stop_sp.write(800.0)
            await ioc.fly_velo.write(1.0)
            ioc._flying = True
            await ioc.scan_sts.write(1)
            task = asyncio.ensure_future(ioc._fly())
            await asyncio.sleep(0.3)
            await getattr(ioc, command).pvspec.put(ioc, getattr(ioc, command), 1)
            await asyncio.wait_for(task, 2.0)

        asyncio.run(run())
        assert not beam.is_scanning() and ioc._flying is False


def test_the_xspress3_is_ready_for_the_next_trigger_when_it_reports_done():
    from sim.pvgroups import xspress3

    ioc = xspress3.build()(prefix="")
    pv = {n: ioc.pvdb[xspress3.PREFIX + n] for n in ("det1:Acquire", "det1:Acquire_RBV", "det1:ArrayCounter", "det1:AcquireTime")}
    acquire, readback, counter = pv["det1:Acquire"], pv["det1:Acquire_RBV"], pv["det1:ArrayCounter"]
    again = {"left": 2}
    original = readback.write

    async def spy(value, *args, **kwargs):
        await original(value, *args, **kwargs)
        if int(value) == 0 and again["left"] > 0:
            again["left"] -= 1
            # the plan's next trigger, the moment it hears "done" (a scan triggers every 0.1 s or less)
            await acquire.pvspec.put(ioc, acquire, 1)

    readback.write = spy

    async def run():
        await pv["det1:AcquireTime"].write(0.05)
        await acquire.pvspec.put(ioc, acquire, 1)
        await asyncio.sleep(1.5)

    asyncio.run(run())
    assert counter.value == 3, counter.value  # one trigger and the two that followed their "done"
    assert acquire.value in (0, "Done") and readback.value in (0, "Done")


def test_the_xspress3_put_completes_when_the_acquisition_ends_unless_switched_off():
    import os
    import time

    from sim.pvgroups import xspress3

    os.environ.pop("IOS_SIM_XS3_PUT_COMPLETION", None)  # on by default
    try:
        ioc = xspress3.build()(prefix="")
        acquire = ioc.pvdb[xspress3.PREFIX + "det1:Acquire"]
        readback = ioc.pvdb[xspress3.PREFIX + "det1:Acquire_RBV"]
        seconds = ioc.pvdb[xspress3.PREFIX + "det1:AcquireTime"]

        async def run():
            await seconds.write(0.2)
            start = time.monotonic()
            result = await acquire.pvspec.put(ioc, acquire, 1)
            return time.monotonic() - start, result, readback.value

        elapsed, result, rbv = asyncio.run(run())
    finally:
        pass
    assert 0.15 < elapsed < 1.0, elapsed  # the put returned when the acquisition had ended
    assert result == 0 and rbv in (0, "Done")

    os.environ["IOS_SIM_XS3_PUT_COMPLETION"] = "0"
    try:
        ioc = xspress3.build()(prefix="")
        acquire = ioc.pvdb[xspress3.PREFIX + "det1:Acquire"]

        async def quick():
            await ioc.pvdb[xspress3.PREFIX + "det1:AcquireTime"].write(0.2)
            start = time.monotonic()
            await acquire.pvspec.put(ioc, acquire, 1)
            elapsed = time.monotonic() - start
            await asyncio.sleep(0.4)  # let the acquisition end before the loop closes
            return elapsed

        assert asyncio.run(quick()) < 0.1  # switched off: the put returns at once, as before
    finally:
        del os.environ["IOS_SIM_XS3_PUT_COMPLETION"]


def test_the_scaler_starts_in_autocount_like_the_real_one():
    from sim.pvgroups.scaler_signals import ScalerIOC

    ioc = ScalerIOC(prefix="X{{Sclr:1}}")
    assert ScalerIOC._index(ioc.CONT.value, ("OneShot", "AutoCount")) == 1


if __name__ == "__main__":
    failed = 0
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                print(f"PASS  {name}")
            except Exception:
                failed += 1
                print(f"FAIL  {name}")
                traceback.print_exc()
    sys.exit(1 if failed else 0)
