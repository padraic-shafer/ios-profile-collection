"""Offline checks of the mock Queueserver's pieces (sim/qs/) and the simulated Xspress3 file.

No IOC, Queueserver or network is needed. The ``qs-sim`` environment has no pytest, so the file also runs as
a script,

    pixi run -e qs-sim python acceptance_tests/test_sim_qs.py

and pytest collects the same functions where it is installed. The end-to-end check against a running mock is
sim/qs/smoke.py.
"""

import os
import pathlib
import sys
import tempfile
import traceback

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.qs import guard, make_startup_dir  # noqa: E402


def raises(exc, func, *args):
    try:
        func(*args)
    except exc as error:
        return error
    raise AssertionError(f"{func.__name__} did not raise {exc.__name__}")


def test_the_ca_port_must_be_set_and_not_the_default():
    assert guard.ca_port_from_environment({"IOS_SIM_CA_PORT": "5864"}) == 5864
    raises(guard.SimGuardError, guard.ca_port_from_environment, {})
    raises(guard.SimGuardError, guard.ca_port_from_environment, {"IOS_SIM_CA_PORT": "abc"})
    assert "default" in str(raises(guard.SimGuardError, guard.ca_port_from_environment, {"IOS_SIM_CA_PORT": "5064"}))
    raises(guard.SimGuardError, guard.ca_port_from_environment, {"IOS_SIM_CA_PORT": "80"})


def test_the_environment_reaches_only_the_loopback_address():
    env = guard.loopback_environment(5864)
    assert env["EPICS_CA_ADDR_LIST"] == "127.0.0.1" and env["EPICS_CA_AUTO_ADDR_LIST"] == "NO"
    assert env["EPICS_PVA_ADDR_LIST"] == "127.0.0.1" and env["EPICS_PVA_AUTO_ADDR_LIST"] == "NO"
    assert env["EPICS_CA_SERVER_PORT"] == "5864" and env["EPICS_CA_REPEATER_PORT"] == "5865"
    assert env["EPICS_CA_NAME_SERVERS"] == "" and env["EPICS_PVA_NAME_SERVERS"] == ""


def test_a_string_pv_arrives_as_text_whatever_its_form():
    assert guard._as_text([b"ios-sim"]) == "ios-sim"
    assert guard._as_text(["ios-sim"]) == "ios-sim"
    assert guard._as_text(list(b"ios-sim") + [0, 0]) == "ios-sim"


def test_the_guard_refuses_when_the_simulated_ioc_does_not_answer():
    saved = {k: os.environ.get(k) for k in ("EPICS_CA_ADDR_LIST", "EPICS_CA_AUTO_ADDR_LIST", "EPICS_CA_SERVER_PORT")}
    os.environ.update(EPICS_CA_ADDR_LIST="127.0.0.1", EPICS_CA_AUTO_ADDR_LIST="NO", EPICS_CA_SERVER_PORT="59999")
    try:
        error = raises(guard.SimGuardError, guard.check_sentinel, 1.0)
        assert "IOS-SIM:Sentinel" in str(error)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_the_startup_directory_has_the_guard_first_and_the_sim_files_last():
    with tempfile.TemporaryDirectory() as tmp:
        names = make_startup_dir.make_startup_dir(pathlib.Path(tmp))
        assert names[0] == "00-00-sim-guard.py" and names[-3:] == ["zz-sim-paths.py", "zz-tiled-writer.py", "zz-xs3-trigger.py"]
        assert "47-IOS_gui.py" not in names and "00-startup.py" in names and "99-xas-edge-plans.py" in names
        assert (pathlib.Path(tmp) / "00-startup.py").is_symlink()
        assert (pathlib.Path(tmp) / "user_group_permissions.yaml").is_file()
        # the profile itself is linked, not copied
        assert (pathlib.Path(tmp) / "99-xas-edge-plans.py").resolve() == ROOT / "startup" / "99-xas-edge-plans.py"


def test_the_permissions_allow_exactly_the_plans_of_the_model_and_two_diagnostics():
    import yaml

    groups = yaml.safe_load((ROOT / "sim" / "qs" / "user_group_permissions.yaml").read_text())["user_groups"]
    assert set(groups["primary"]["allowed_plans"]) == {
        "xas_edge_ascan", "xas_pd_ascan", "XAS_scan", "PD_scan", "find_sample", "count", "mv",
    }
    assert all(not name.startswith(":") for name in groups["primary"]["allowed_plans"])


def test_the_shared_xspress3_file_is_small_and_readable_as_the_handler_reads_it():
    import h5py
    import numpy as np

    from sim.pvgroups import xspress3

    with tempfile.TemporaryDirectory() as tmp:
        path = xspress3.ensure_shared_file(pathlib.Path(tmp), frames=1024)
        assert path.stat().st_size < 2_000_000
        with h5py.File(path, "r") as handle:
            data = handle[xspress3.DATASET]
            assert data.shape == (1024, 1, xspress3.N_BINS)
            assert np.array_equal(data[0, 0, :], data[1023, 0, :])  # one spectrum in every frame
            assert data[0, 0, 440:460].sum() > data[0, 0, 0:20].sum()  # with its line at bin 450
        assert xspress3.ensure_shared_file(pathlib.Path(tmp), frames=1024) == path  # not written again


def test_the_xspress3_serves_the_names_of_the_profiles_class_and_only_below_the_data_directory():
    from sim.pvgroups import xspress3

    names = {p.name for p in xspress3.needed_pvs()}
    for pv in ("det1:Acquire_RBV", "MCA1ROI:1:Name", "MCA1ROI:4:MinX", "HDF1:FilePath_RBV", "HDF1:Capture_RBV"):
        assert xspress3.PREFIX + pv in names, pv
    with tempfile.TemporaryDirectory() as tmp:
        directory = pathlib.Path(tmp).resolve()
        assert xspress3._inside(directory, directory / "2026" / "11" / "x.h5")
        assert not xspress3._inside(directory, pathlib.Path("/nsls2/data/ios/legacy/xspress3_data/2026"))
        assert not xspress3._inside(directory, directory / ".." / "elsewhere")


class _FakeCounter:
    """The image counter of a detector: a readback that can be read and subscribed to."""

    def __init__(self, value=5):
        self.value, self.subs = value, []

    def get(self):
        return self.value

    def subscribe(self, callback, run=True):
        self.subs.append(callback)
        if run:
            callback(value=self.value)

    def clear_sub(self, callback):
        if callback in self.subs:
            self.subs.remove(callback)

    def advance(self):
        self.value += 1
        for callback in list(self.subs):
            callback(value=self.value)


def _fake_detector():
    from types import SimpleNamespace

    from ophyd.status import Status

    detector = SimpleNamespace(cam=SimpleNamespace(array_counter=_FakeCounter()), _acquire_status=None)

    def trigger():
        detector._acquire_status = Status()
        return detector._acquire_status

    detector.trigger = trigger
    return detector


def test_a_trigger_finishes_on_the_image_counter_when_the_readback_edge_is_missed():
    from sim.qs.xs3_trigger import install

    detector = _fake_detector()
    install(detector, grace=0.05)
    status = detector.trigger()
    assert not status.done
    detector.cam.array_counter.advance()  # the acquisition ended; the 1 -> 0 of the readback never comes
    assert not status.done  # the readback has its grace first
    assert status.wait(timeout=2) is None and status.done and status.success
    assert detector._acquire_status is None  # nslsii's callback has nothing left to finish twice
    assert detector.cam.array_counter.subs == []


def test_a_trigger_that_the_readback_finishes_in_time_is_left_alone():
    import time

    from sim.qs.xs3_trigger import install

    detector = _fake_detector()
    install(detector, grace=0.05)
    status = detector.trigger()
    detector.cam.array_counter.advance()  # the counter moves just before the edge, as usual
    status.set_finished()  # nslsii's callback saw the edge
    time.sleep(0.2)  # the grace passes: nothing happens, nothing raises
    assert status.done and status.success
    assert detector.cam.array_counter.subs == []


def test_a_trigger_does_not_finish_before_the_counter_moves():
    import time

    from sim.qs.xs3_trigger import install

    detector = _fake_detector()
    install(detector, grace=0.05)
    status = detector.trigger()
    time.sleep(0.2)
    assert not status.done
    assert len(detector.cam.array_counter.subs) == 1


def test_the_trigger_writes_with_put_completion_and_finishes_from_it():
    from types import SimpleNamespace

    from ophyd.status import Status

    from sim.qs.xs3_trigger import install_put_completion

    calls = []

    class FakeAcquire:
        def put(self, value, **kwargs):
            calls.append((value, kwargs))

    detector = SimpleNamespace(cam=SimpleNamespace(acquire=FakeAcquire()), _acquire_status=Status())
    status = detector._acquire_status
    install_put_completion(detector)
    detector.cam.acquire.put(1, wait=False)  # what nslsii's trigger does
    value, kwargs = calls[-1]
    assert value == 1 and kwargs["use_complete"] is True and "wait" in kwargs
    assert not status.done
    kwargs["callback"]()  # the IOC's reply: the acquisition has ended, and the readback edge was not seen
    assert status.done and status.success and detector._acquire_status is None
    # another kind of write is passed on as it is
    detector.cam.acquire.put(0)
    assert calls[-1] == (0, {})
    # and a status that the edge finished first is left alone
    detector._acquire_status = Status()
    first = detector._acquire_status
    detector.cam.acquire.put(1, wait=False)
    first.set_finished()
    calls[-1][1]["callback"]()  # must not raise


def test_a_trigger_that_ended_before_it_returns_still_returns_its_status():
    from types import SimpleNamespace

    from ophyd.status import Status

    from sim.qs.xs3_trigger import install_put_completion

    calls = []

    class FakeAcquire:
        def put(self, value, **kwargs):
            calls.append(kwargs)
            if "callback" in kwargs:
                kwargs["callback"]()  # the acquisition is over before the write returns

    detector = SimpleNamespace(cam=SimpleNamespace(acquire=FakeAcquire()), _acquire_status=None)

    def new_acquire_status():
        return Status()

    detector.new_acquire_status = new_acquire_status

    def trigger():  # nslsii's, in short
        detector._acquire_status = detector.new_acquire_status()
        detector.cam.acquire.put(1, wait=False)
        return detector._acquire_status

    detector.trigger = trigger
    install_put_completion(detector)
    status = detector.trigger()
    assert status is not None and status.done and status.success
    assert detector._acquire_status is None
    install_put_completion(detector)  # a second install does not wrap again
    assert detector.trigger() is not None


def test_the_readback_edge_of_nslsiis_trigger_is_switched_off_when_put_completion_is_used():
    from types import SimpleNamespace

    from sim.qs.xs3_trigger import _ignore_the_edge, install_put_completion

    def make():
        detector = SimpleNamespace(cam=SimpleNamespace(acquire=SimpleNamespace(put=lambda *a, **k: None)))
        detector._acquire_changed = lambda value=None, old_value=None, **kw: calls.append((old_value, value))
        return detector

    calls = []
    detector = make()
    install_put_completion(detector)
    assert detector._acquire_changed is _ignore_the_edge
    detector._acquire_changed(value=0, old_value=1)
    assert calls == []  # the edge no longer finishes anything

    kept = make()
    original = kept._acquire_changed
    install_put_completion(kept, keep_edge=True)
    assert kept._acquire_changed is original


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
