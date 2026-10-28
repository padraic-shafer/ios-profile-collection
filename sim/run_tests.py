"""
sim/run_tests.py
-----------------
Acceptance test runner for the IOS sim stack.

Exercises the sim IOC with the same operations the real beamline profile
performs, verifying that:

  1. All device families connect (scaler, motors, shutters, EPU, PGM, mirrors,
     Vortex MCA, SPECS, Xspress3).
  2. The existing acceptance test passes: ``count([sclr], num=5)``.
  3. A short motor scan completes: ``scan([sclr], appes_x, 0, 1, 3)``.

Usage (requires the sim IOC to already be running)::

    EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO \\
        python sim/run_tests.py

Or via pixi::

    pixi run sim-test   # starts IOC + runs tests automatically

Exit code: 0 on all-pass, 1 on any failure.
"""

from __future__ import annotations

import os
import sys
import time
import logging

# Repo root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set EPICS addressing before any ophyd import
os.environ.setdefault("EPICS_CA_ADDR_LIST",      "127.0.0.1")
os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST",  "NO")

# Apply service stubs so the test environment mirrors the profile session
from sim.externals.stubs import apply_all
apply_all()

# Set ophyd defaults before any device is instantiated
try:
    from ophyd.signal import EpicsSignalBase as _ESB
except ImportError:
    from ophyd import EpicsSignal as _ESB
_ESB.set_defaults(timeout=10, connection_timeout=10)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("ios.sim.tests")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

passed: list[str] = []
failed: list[str] = []

def ok(name: str) -> None:
    passed.append(name)
    print(f"  PASS  {name}")

def fail(name: str, reason: str = "") -> None:
    failed.append(name)
    print(f"  FAIL  {name}{': ' + reason if reason else ''}")

def expect_near(name: str, got, want, tol=0.1) -> bool:
    try:
        if abs(float(got) - float(want)) <= tol:
            ok(name)
            return True
        else:
            fail(name, f"got {got}, expected ~{want}")
            return False
    except Exception as exc:
        fail(name, str(exc))
        return False

# ---------------------------------------------------------------------------
# Test 1: low-level CA connectivity (caproto sync client)
# ---------------------------------------------------------------------------

def test_ca_connectivity() -> None:
    print("\n── CA connectivity ─────────────────────────────────────────")
    from caproto.sync.client import read

    checks = [
        ("scaler.TP",        "XF:23ID2-ES{Sclr:1}.TP",               "float",  1.0),
        ("scaler.S2",        "XF:23ID2-ES{Sclr:1}.S2",               "any",    None),
        ("slt2.DMOV",        "XF:23ID2-OP{Slt:2-Ax:Y}Mtr.DMOV",     "int",    1),
        ("fe_shutter.Pos",   "XF:23ID-PPS{Sh:FE}Pos-Sts",            "any",    None),
        ("ring_curr",        "XF:23ID-SR{}I-I",                       "float",  400.0),
        ("epu1.gap.Pos-I",   "XF:23ID-ID{EPU:1-Ax:Gap}Pos-I",        "any",    None),
        ("pgm.energy-I",     "XF:23ID2-OP{Mono}Enrgy-I",             "float",  400.0),
        ("m1a.pit.MON",      "XF:23IDA-OP:1{Mir:1-Ax:Pit}Mtr_MON",  "any",    None),
        ("vortex.ACQG",      "XF:23ID2-ES{Vortex}mca1.ACQG",        "any",    None),
        ("specs.acquire",    "XF:23ID2-ES{SPECS}cam1:Acquire",       "any",    None),
        ("xs3.roi1.name",    "XF:23ID2-ES{Xsp:1}:C1_MCA_ROI1_ROIName","any",  None),
    ]

    for name, pvname, kind, expected in checks:
        try:
            r = read(pvname, timeout=5)
            data = r.data
            if kind == "float" and expected is not None:
                val = float(data[0]) if data is not None and len(data) > 0 else None
                expect_near(name, val, expected, tol=1.0)
            elif kind == "int" and expected is not None:
                val = int(data[0]) if data is not None and len(data) > 0 else None
                if val == int(expected):
                    ok(name)
                else:
                    fail(name, f"got {val}, expected {expected}")
            else:
                # Any non-None response is a pass
                if data is not None:
                    ok(name)
                else:
                    fail(name, "no data returned")
        except Exception as exc:
            fail(name, str(exc))

# ---------------------------------------------------------------------------
# Test 2: ophyd device connect
# ---------------------------------------------------------------------------

def test_ophyd_connect() -> None:
    print("\n── ophyd device connect ────────────────────────────────────")
    from ophyd import EpicsMotor, EpicsSignal

    devs = {
        "slt2":       EpicsMotor("XF:23ID2-OP{Slt:2-Ax:Y}Mtr",    name="slt2"),
        "appes_x":    EpicsMotor("XF:23ID2-ES{APPES:1-Ax:X}Mtr",  name="appes_x"),
        "ring_curr":  EpicsSignal("XF:23ID-SR{}I-I",                name="ring_curr"),
    }

    for name, dev in devs.items():
        try:
            status = dev.wait_for_connection(timeout=5)
            ok(f"ophyd.{name}")
        except Exception as exc:
            fail(f"ophyd.{name}", str(exc))

    return devs

# ---------------------------------------------------------------------------
# Test 3: existing acceptance test — count([sclr], num=5)
# ---------------------------------------------------------------------------

def test_count_sclr() -> None:
    print("\n── count([sclr], num=5)  [existing acceptance test] ────────")
    try:
        from ophyd import EpicsScaler as _Scaler

        sclr = _Scaler("XF:23ID2-ES{Sclr:1}", name="sclr")
        sclr.wait_for_connection(timeout=10)

        import bluesky
        from bluesky import RunEngine
        from bluesky.plans import count

        RE = RunEngine({})
        docs = []
        RE.subscribe(lambda name, doc: docs.append(name))

        RE(count([sclr], num=5))

        events = [d for d in docs if d == "event"]
        if len(events) == 5:
            ok("count([sclr], num=5) — 5 events")
        else:
            fail("count([sclr], num=5)", f"expected 5 events, got {len(events)}")
    except Exception as exc:
        fail("count([sclr], num=5)", str(exc))

# ---------------------------------------------------------------------------
# Test 4: motor scan smoke test — scan([sclr], appes_x, 0, 1, 3)
# ---------------------------------------------------------------------------

def test_motor_scan() -> None:
    print("\n── scan([sclr], appes_x, 0, 1, 3)  [smoke test] ───────────")
    try:
        from ophyd import EpicsMotor
        from ophyd import EpicsScaler as _Scaler

        sclr = _Scaler("XF:23ID2-ES{Sclr:1}", name="sclr")
        appes_x = EpicsMotor("XF:23ID2-ES{APPES:1-Ax:X}Mtr", name="appes_x")
        for dev in (sclr, appes_x):
            dev.wait_for_connection(timeout=10)

        from bluesky import RunEngine
        from bluesky.plans import scan

        RE = RunEngine({})
        docs = []
        RE.subscribe(lambda name, doc: docs.append(name))

        RE(scan([sclr], appes_x, 0, 1, 3))

        events = [d for d in docs if d == "event"]
        if len(events) == 3:
            ok("scan([sclr], appes_x, 0→1, 3pts) — 3 events")
        else:
            fail("scan([sclr], appes_x, 0→1, 3pts)",
                 f"expected 3 events, got {len(events)}")
    except Exception as exc:
        fail("scan motor", str(exc))

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("IOS Sim Acceptance Tests")
    print("=" * 60)

    test_ca_connectivity()
    test_ophyd_connect()
    test_count_sclr()
    test_motor_scan()

    print(f"\n{'=' * 60}")
    print(f"Results: {len(passed)} passed, {len(failed)} failed")
    if failed:
        print("Failed:")
        for f in failed:
            print(f"  - {f}")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
