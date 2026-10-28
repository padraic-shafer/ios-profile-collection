"""
sim/externals/pre_exec.py
--------------------------
IPython pre-exec file for the IOS sim stack.

This file is injected via the IPython ``exec_files`` mechanism *before* the
numbered startup files (00-startup.py …) are executed.  It:

  1. Sets EPICS environment variables so ophyd connects to the local caproto
     IOC instead of the real beamline IOC.
  2. Applies all external-service stubs (amostra, pyOlog, redis override,
     kafka config, databroker local catalog).
  3. Pre-seeds the Xspress3 ``roi_name`` PVs via a synchronous CA put so
     the import-time ``mcaroi.roi_name.get()`` loop in 22-xspress3.py returns
     immediately with a non-empty value.

Usage
~~~~~
This file is referenced by the ``sim-start`` pixi task, which launches
IPython with::

    ipython --profile-dir=. -c "exec(open('sim/externals/pre_exec.py').read())"
    # or via InteractiveShellApp.exec_files in a sim ipython_config.py

It can also be used as a drop-in for the CI test harness.

Environment variables consumed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  IOS_SIM_CA_PORT     CA server port (default: 5064)
  IOS_SIM_KAFKA       Set to "1" to enable Kafka publishing (default: off)
  IOS_SIM_LOG_LEVEL   Log level for ios.sim logger (default: WARNING)
"""

from __future__ import annotations

import logging
import os
import pathlib
import sys
import time

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_level = os.environ.get("IOS_SIM_LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=getattr(logging, _level, logging.WARNING),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
_log = logging.getLogger("ios.sim")
_log.warning("=" * 60)
_log.warning("IOS SIM MODE — pre_exec.py running")
_log.warning("All EPICS devices connect to localhost caproto IOC")
_log.warning("=" * 60)

# ---------------------------------------------------------------------------
# 1. EPICS CA environment
# ---------------------------------------------------------------------------

_ca_port = os.environ.get("IOS_SIM_CA_PORT", "5064")

os.environ["EPICS_CA_ADDR_LIST"]         = "127.0.0.1"
os.environ["EPICS_CA_AUTO_ADDR_LIST"]    = "NO"
os.environ["EPICS_CAS_AUTO_BEACON_ADDR_LIST"] = "no"
os.environ["EPICS_CAS_BEACON_ADDR_LIST"] = "127.0.0.1"

_log.info("SIM: EPICS CA -> 127.0.0.1 (port %s)", _ca_port)

# ---------------------------------------------------------------------------
# 2. External-service stubs
# ---------------------------------------------------------------------------

# Ensure the repo root is on sys.path so 'sim' package is importable
_repo_root = pathlib.Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from sim.externals.stubs import apply_all
apply_all()

# ---------------------------------------------------------------------------
# 3. Pre-seed Xspress3 roi_name PVs via synchronous CA put
# ---------------------------------------------------------------------------
# 22-xspress3.py calls mcaroi.roi_name.get() at module scope (import time).
# The caproto _startup() hook seeds these asynchronously, but may not have
# run by the time ophyd's EpicsSignal.get() fires.  We do a synchronous put
# here so the PV has a non-empty value before the profile loads.
#
# This requires the sim IOC to already be running (pixi run sim-iocs).

def _seed_xs3_roi_names(timeout: float = 5.0) -> None:
    """Put non-empty strings onto Xspress3 roi_name PVs before profile load."""
    try:
        from caproto.sync.client import write as _ca_write
    except ImportError:
        _log.warning("SIM: caproto not importable; skipping Xspress3 ROI name seeding")
        return

    roi_names = {
        "XF:23ID2-ES{Xsp:1}:C1_MCA_ROI1_ROIName": "roi1",
        "XF:23ID2-ES{Xsp:1}:C1_MCA_ROI2_ROIName": "roi2",
        "XF:23ID2-ES{Xsp:1}:C1_MCA_ROI3_ROIName": "roi3",
        "XF:23ID2-ES{Xsp:1}:C1_MCA_ROI4_ROIName": "roi4",
    }

    for pvname, name in roi_names.items():
        try:
            _ca_write(pvname, name, timeout=timeout)
            _log.info("SIM: seeded %s = %r", pvname, name)
        except Exception as exc:
            _log.warning(
                "SIM: could not seed %s — is sim-iocs running? (%s)", pvname, exc
            )

_log.info("SIM: seeding Xspress3 roi_name PVs...")
_seed_xs3_roi_names()

# ---------------------------------------------------------------------------
# 4. Notify user
# ---------------------------------------------------------------------------

print(
    "\n"
    "╔══════════════════════════════════════════════════════════════╗\n"
    "║  IOS SIM MODE                                                ║\n"
    "║  EPICS devices → localhost caproto IOC                       ║\n"
    "║  Redis         → localhost:6379 (TLS disabled)               ║\n"
    "║  amostra/pyOlog→ stubbed (no-op)                             ║\n"
    "║  Run 'pixi run sim-up' to start redis/kafka/zmq containers   ║\n"
    "║  Run 'pixi run sim-iocs' to start the caproto IOC server     ║\n"
    "╚══════════════════════════════════════════════════════════════╝\n"
)
