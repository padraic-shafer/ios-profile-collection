"""
sim/run_iocs.py
---------------
Start all simulated caproto IOCs for the IOS profile collection.

Every EPICS PV name is identical to the real beamline IOC.  Only the
CA addressing differs: this server binds to 127.0.0.1 on a fixed port
and expects clients to set::

    EPICS_CA_ADDR_LIST=127.0.0.1
    EPICS_CA_AUTO_ADDR_LIST=NO

Usage::

    python sim/run_iocs.py            # foreground, logs to stdout
    python sim/run_iocs.py --list-pvs # print all served PV names and exit

The script can also be invoked via the pixi task::

    pixi run sim-iocs

Environment variables (all optional):

    IOS_SIM_CA_PORT   CA server port (default: 5064, the EPICS standard)
    IOS_SIM_LOG_LEVEL log level name (default: WARNING)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from caproto.server import run, PVGroup, pvproperty, SubGroup

from sim.pvgroups.motors import MotorFields, MOTOR_PREFIX_MAP
from sim.pvgroups.scaler_signals import (
    ScalerIOC,
    StandaloneSignalsIOC,
    ShutterIOC,
    SHUTTER_PREFIX_MAP,
)
from sim.pvgroups.positioners import (
    EPU1IOC,
    EPU2IOC,
    EPUStopIOC,
    M1A_IOC,
    M1B1_IOC,
    M1B2_IOC,
    M3B_IOC,
    MirrorStandaloneIOC,
    FeedbackLoopIOC,
    PGMEnergyIOC,
    VortexIOC,
)
from sim.pvgroups.detectors import (
    SpecsIOC,
    Xspress3IOC,
    XS3_ROI_NAMES,
)

log = logging.getLogger("ios.sim")


# ---------------------------------------------------------------------------
# Build the combined PVGroup list
# ---------------------------------------------------------------------------

def build_ioc_groups() -> list[tuple[type, str]]:
    """Return a list of (PVGroup subclass, prefix) pairs for every IOC."""

    groups: list[tuple[type, str]] = []

    # -- Motors ------------------------------------------------------------
    for name, prefix in MOTOR_PREFIX_MAP.items():
        groups.append((MotorFields, prefix))

    # -- Scaler -----------------------------------------------------------
    groups.append((ScalerIOC, "XF:23ID2-ES{{Sclr:1}}"))

    # -- Standalone signals (one flat group, prefix="" so PV names are full)
    groups.append((StandaloneSignalsIOC, ""))

    # -- Shutters ---------------------------------------------------------
    for name, prefix in SHUTTER_PREFIX_MAP.items():
        groups.append((ShutterIOC, prefix))

    # -- EPU --------------------------------------------------------------
    # EPU1IOC/EPU2IOC use absolute PV names (prefix split mid-brace), so prefix="".
    groups.append((EPU1IOC, ""))
    groups.append((EPU2IOC, ""))
    groups.append((EPUStopIOC, ""))   # absolute-PV stop signals, no prefix

    # -- Mirrors (split-brace prefixes — use absolute-PV IOC classes) ------
    groups.append((M1A_IOC,  ""))
    groups.append((M1B1_IOC, ""))
    groups.append((M1B2_IOC, ""))
    groups.append((M3B_IOC,  ""))
    groups.append((MirrorStandaloneIOC, ""))

    # -- Mirror feedback --------------------------------------------------
    groups.append((FeedbackLoopIOC, "XF:23ID2-OP{{FBck}}"))

    # -- PGM (absolute PV names, prefix="") --------------------------------
    groups.append((PGMEnergyIOC, ""))

    # -- Vortex MCA -------------------------------------------------------
    groups.append((VortexIOC, "XF:23ID2-ES{{Vortex}}"))

    # -- SPECS analyzer (flat group, absolute PV names — prefix must be "") --
    groups.append((SpecsIOC, ""))

    # -- Xspress3 (flat group, absolute PV names — prefix must be "") ------
    groups.append((Xspress3IOC, ""))

    return groups


# ---------------------------------------------------------------------------
# Merge all groups into a single top-level PVGroup for caproto
# ---------------------------------------------------------------------------

def assemble_pvgroup(groups: list[tuple[type, str]]) -> type:
    """
    Dynamically assemble all (PVGroup subclass, prefix) pairs into a single
    top-level PVGroup subclass that caproto's ``run()`` can host.

    Each entry becomes a SubGroup descriptor at the class level.  The top-level
    group is instantiated with prefix="" so each sub-group's prefix is its
    full absolute PV prefix.
    """
    attrs: dict = {}
    for i, (cls, prefix) in enumerate(groups):
        # Note: caproto skips attributes starting with '_', so use 'ioc_N'.
        attr_name = f"ioc_{i}"
        attrs[attr_name] = SubGroup(cls, prefix=prefix)

    TopLevel = type("IOSSimIOC", (PVGroup,), attrs)
    return TopLevel


async def run_with_startup(ioc_instance):
    """Run _startup() hooks on any sub-group that defines one."""
    for attr_name in vars(type(ioc_instance)):
        if not attr_name.startswith("ioc_"):
            continue
        child = getattr(ioc_instance, attr_name)
        if hasattr(child, "_startup") and asyncio.iscoroutinefunction(child._startup):
            await child._startup()
        # One level deeper (e.g. Xspress3IOC contains sub-PVGroups)
        for sub_attr in vars(type(child)):
            if sub_attr.startswith("_"):
                continue
            sub = getattr(child, sub_attr, None)
            if sub is None:
                continue
            if hasattr(sub, "_startup") and asyncio.iscoroutinefunction(sub._startup):
                await sub._startup()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="IOS sim IOCs (caproto)")
    p.add_argument(
        "--list-pvs",
        action="store_true",
        help="Print all served PV names and exit without starting the server.",
    )
    p.add_argument(
        "--log-level",
        default=os.environ.get("IOS_SIM_LOG_LEVEL", "WARNING"),
        help="Logging level (default: WARNING)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    ca_port = int(os.environ.get("IOS_SIM_CA_PORT", "5064"))
    interfaces = ["127.0.0.1"]

    groups = build_ioc_groups()

    if args.list_pvs:
        # Instantiate briefly to collect PV names, then exit
        TopLevel = assemble_pvgroup(groups)
        ioc = TopLevel(prefix="")
        pvdb = ioc.pvdb
        for pvname in sorted(pvdb.keys()):
            print(pvname)
        print(f"\n{len(pvdb)} PVs served", file=sys.stderr)
        return

    TopLevel = assemble_pvgroup(groups)

    log.warning(
        "Starting IOS sim IOC on 127.0.0.1:%d  (%d device groups)",
        ca_port,
        len(groups),
    )
    log.warning(
        "Set EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO "
        "before starting the profile."
    )

    ioc = TopLevel(prefix="")

    async def _startup(async_lib):
        """Seed PVs that need pre-populated values (Xspress3 roi_name, etc.)."""
        await run_with_startup(ioc)

    run(
        ioc.pvdb,
        startup_hook=_startup,
        interfaces=interfaces,
        log_pv_names=False,
    )


if __name__ == "__main__":
    main()
