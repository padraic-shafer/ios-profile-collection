"""
sim/check_drift.py
------------------
Detect divergence between the IOS profile's real ophyd devices and the
simulated caproto IOC.

Three sources are compared:

  A  Real profile devices (ground truth)
     The device-defining startup files are executed in an isolated namespace
     without connecting to EPICS or any external service.  Every module-scope
     ophyd Device / Signal object is then walked recursively to collect the
     exact set of PV names the profile will request at runtime.

  B  Sim IOC served PVs
     build_ioc_groups() + assemble_pvgroup() from sim/run_iocs.py gives the
     full set of PV names caproto will serve.  No server is started.

  I  Hand-written inventory (sim/pv_inventory.py)
     build_inventory() gives the PV set maintained by hand.  Compared
     against A to flag when it needs updating.

Checks performed
~~~~~~~~~~~~~~~~
  FAIL  PVs the profile needs but the sim IOC does NOT serve.
        These would cause connection timeouts in a real sim session.

  FAIL  Device files that fail to load (surfaced, not silently skipped).

  WARN  PVs the sim IOC serves but no profile device requests.
        Mostly expected (motor-record extras, temperature monitors) but
        worth knowing about when trimming dead PVs.

  WARN  PV names in sim/pv_inventory.py that diverge from the live walk.
        The inventory needs --write to resync.

Exit codes
~~~~~~~~~~
  0   No FAILs (WARNs may be present)
  1   At least one FAIL (or any WARN under --strict)

Usage
~~~~~
  python sim/check_drift.py                # human-readable report
  python sim/check_drift.py --json         # JSON output for CI
  python sim/check_drift.py --strict       # promote WARNs to FAILs
  python sim/check_drift.py --write        # regenerate pv_inventory.py
  python sim/check_drift.py --no-allowlist # disable expected-extra suppression

  pixi run sim-check-drift

--write mode
~~~~~~~~~~~~
  Regenerates the auto-generated section in sim/pv_inventory.py from the
  live device walk.  By default the script only *reports* drift and prints
  a recommendation block.  Run with --write explicitly to apply changes.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import sys
import textwrap
import types
from collections import defaultdict
from typing import Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO = pathlib.Path(__file__).resolve().parents[1]
_SIM_DIR = _REPO / "sim"
_STARTUP_DIR = _REPO / "startup"

# Device-defining startup files, in execution order.
# Selection criterion: defines or instantiates ophyd Device / Signal objects.
# Excluded: 00-startup.py (network calls), 47-IOS_gui.py (Qt), 5x/9x (scans).
DEVICE_FILES: List[pathlib.Path] = [
    _STARTUP_DIR / "01-classes.py",
    _STARTUP_DIR / "10-machine.py",
    _STARTUP_DIR / "10-optics.py",
    _STARTUP_DIR / "11-valves.py",
    _STARTUP_DIR / "20-detectors.py",
    _STARTUP_DIR / "21-specs_analyzer.py",
    _STARTUP_DIR / "22-xspress3.py",
    _STARTUP_DIR / "23-devices.py",
]

# PV-suffix allowlist for "extra in sim but not needed by profile".
# These are intentional expansions (broader motor record, temperature
# monitors, etc.) rather than bugs.  Suppress from WARN output.
EXTRA_ALLOWLIST_SUFFIXES: Tuple[str, ...] = (
    # Motor record fields beyond what EpicsMotor requests (sim serves a superset)
    ".ATHM", ".BACC", ".CNEN", ".DESC", ".DHLM", ".DLLM",
    ".DIFF", ".DVAL", ".EGU", ".ERES", ".HVEL",
    ".JOGF", ".JOGR", ".LOLO", ".HIHI", ".LOW", ".HIGH",
    ".MIP", ".MISS", ".MRES", ".MSTA",
    ".PREC", ".RCNT", ".RDBD", ".RRES", ".RRBV", ".RTRY", ".RVAL",
    ".SBAS", ".SPDB", ".SPMG", ".STUP", ".TDIR",
    ".TWF", ".TWR", ".TWV", ".UEIP", ".UREV", ".URIP", ".VMAX",
)

EXTRA_ALLOWLIST_PREFIXES: Tuple[str, ...] = (
    # Temperature monitors: served for completeness, not walked via Device objects
    "XF:23ID1-OP{TCtrl:",
    "XF:23IDA-UT{DI}",
    "XF:23ID2-OP{Mon-",
    # SPECS HDF5 plugin: commented-out in 21-specs_analyzer.py (hdf1 component
    # is disabled in the profile) but the sim serves it for future use.
    "XF:23ID2-ES{SPECS}HDF1:",
    # SPECS cam1: the sim serves the full CamBase surface; the ophyd walk via
    # SpecsDetectorCam only resolves a subset (custom fields + no-auto-monitor
    # base fields); extras here are intentional coverage for future AD use.
    "XF:23ID2-ES{SPECS}cam1:",
    # SPECS Stats5 plugin: served broadly; profile only uses Total_RBV and
    # EnableCallbacks via ADComponent — the rest are intentional extras.
    "XF:23ID2-ES{SPECS}Stats5:",
    # Xspress3 HDF1 plugin extras (sim serves more than ophyd directly walks)
    "XF:23ID2-ES{Xsp:1}:HDF1:",
)


# ---------------------------------------------------------------------------
# Source A: load real profile devices offline
# ---------------------------------------------------------------------------

def _apply_offline_patches() -> None:
    """Patch ophyd so device files can be exec'd without a live IOC.

    Three patches are applied:
      1. Very short CA timeout so any stray connection attempt fails fast.
      2. EpicsSignalBase.connected always returns True so attribute access
         on un-connected signals (e.g. .kind = "hinted") doesn't block.
      3. EpicsSignal.get() returns a benign default on any CA error so the
         Xspress3 import-time roi_name.get() loop returns immediately.
      4. EpicsSignalBase.wait_for_connection() is a no-op that returns False.

    All patches target the class — they apply for the lifetime of the
    process and are intentionally NOT restored (this script is a one-shot
    tool, not a library).
    """
    try:
        from ophyd.signal import EpicsSignalBase
    except ImportError:
        from ophyd import EpicsSignal as EpicsSignalBase

    EpicsSignalBase.set_defaults(timeout=0.001, connection_timeout=0.001)

    _orig_wfc = EpicsSignalBase.wait_for_connection
    def _safe_wfc(self, *a, **kw):
        try:
            return _orig_wfc(self, *a, **kw)
        except Exception:
            return False
    EpicsSignalBase.wait_for_connection = _safe_wfc

    # .connected as a property — always report True so kind/read_attrs
    # attribute access on MCA ROI / AD signals doesn't block.
    EpicsSignalBase.connected = property(lambda self: True)

    import ophyd
    _orig_get = ophyd.EpicsSignal.get
    def _safe_get(self, *a, **kw):
        try:
            return _orig_get(self, *a, **kw)
        except Exception:
            return ""
    ophyd.EpicsSignal.get = _safe_get


def _make_stub_namespace() -> dict:
    """Return a namespace with stubs for names used inside function bodies.

    These names appear in the device files only inside function definitions
    (plan stubs, callbacks) or as deferred references.  The stubs are
    stand-ins so the exec doesn't raise NameError at module scope.
    """
    import numpy as np

    class _NsProxy:
        """Absorbs any attribute access / call without error."""
        def __getattr__(self, name):
            return _NsProxy()
        def __call__(self, *a, **kw):
            return _NsProxy()
        def __iter__(self):
            return iter([])
        def __repr__(self):
            return "<stub>"

    stub = _NsProxy()
    return {
        # bluesky plan stubs (only inside generator functions)
        "bps": stub, "bpp": stub, "bp": stub,
        "mv": stub, "sleep": stub,
        # run engine / best-effort callback
        "RE": stub, "bec": stub, "sd": stub,
        # numpy (imported explicitly in some files, but numpy is available)
        "np": np,
        # pyepics (caget/caput only inside functions)
        "caget": stub, "caput": stub,
        # bluesky suspenders
        "SuspendBoolHigh": stub,
        # nslsii (not needed for device definitions)
        "nslsii": stub,
    }


def _walk_pvs(obj, seen: set | None = None) -> Set[str]:
    """Recursively collect pvnames from an ophyd Device or Signal."""
    if seen is None:
        seen = set()
    pvs: Set[str] = set()
    obj_id = id(obj)
    if obj_id in seen:
        return pvs
    seen.add(obj_id)

    if hasattr(obj, "pvname"):
        pvs.add(obj.pvname)
    elif hasattr(obj, "component_names"):
        for attr in obj.component_names:
            try:
                child = getattr(obj, attr)
            except Exception:
                continue
            pvs |= _walk_pvs(child, seen)
    return pvs


def load_source_a(
    device_files: List[pathlib.Path] | None = None,
) -> Tuple[Set[str], List[str], Dict[str, Set[str]]]:
    """Load real profile devices and return their PV set.

    Returns
    -------
    pvs : set[str]
        All PV names requested by profile devices.
    load_warnings : list[str]
        Human-readable warnings for files that failed to load.
    by_device : dict[str, set[str]]
        PV names grouped by the device variable name (for diagnostics).
    """
    _apply_offline_patches()

    # Apply service stubs (amostra, pyOlog) so their import doesn't block.
    try:
        sys.path.insert(0, str(_REPO))
        from sim.externals.stubs import _stub_amostra, _stub_olog
        _stub_amostra()
        _stub_olog()
    except Exception:
        pass

    ns = _make_stub_namespace()
    load_warnings: List[str] = []

    files = device_files if device_files is not None else DEVICE_FILES

    # Suppress stdout during exec so device-file print() calls (e.g. the
    # Xspress3 "No PV set for..." messages from the offline roi_name.get())
    # don't pollute the drift report output.
    import io
    _devnull = io.StringIO()

    for fpath in files:
        if not fpath.exists():
            load_warnings.append(f"Device file not found: {fpath}")
            continue
        try:
            src = fpath.read_text()
            _real_stdout, sys.stdout = sys.stdout, _devnull
            try:
                exec(compile(src, str(fpath), "exec"), ns)
            finally:
                sys.stdout = _real_stdout
        except Exception as exc:
            sys.stdout = _real_stdout  # ensure restore on error too
            load_warnings.append(
                f"Failed to load {fpath.name}: {type(exc).__name__}: {exc}"
            )

    # Collect ophyd objects from the namespace
    try:
        from ophyd import Device, Signal
        ophyd_types = (Device, Signal)
    except ImportError:
        from ophyd import Device
        ophyd_types = (Device,)

    all_pvs: Set[str] = set()
    by_device: Dict[str, Set[str]] = {}
    seen_ids: set = set()

    for name, obj in ns.items():
        if name.startswith("_"):
            continue
        if isinstance(obj, ophyd_types):
            device_pvs = _walk_pvs(obj, seen_ids)
            if device_pvs:
                by_device[name] = device_pvs
                all_pvs |= device_pvs

    return all_pvs, load_warnings, by_device


# ---------------------------------------------------------------------------
# Source B: sim IOC served PVs
# ---------------------------------------------------------------------------

def load_source_b() -> Set[str]:
    """Return the set of PV names the sim IOC serves (no server started)."""
    sys.path.insert(0, str(_REPO))
    from sim.run_iocs import assemble_pvgroup, build_ioc_groups

    groups = build_ioc_groups()
    ioc = assemble_pvgroup(groups)(prefix="")
    return set(ioc.pvdb.keys())


# ---------------------------------------------------------------------------
# Source I: hand-written inventory
# ---------------------------------------------------------------------------

def load_source_i() -> Set[str]:
    """Return the PV set from the hand-written pv_inventory.py."""
    sys.path.insert(0, str(_REPO))
    from sim.pv_inventory import build_inventory

    pvs: Set[str] = set()
    for pvlist in build_inventory().values():
        for pvname, _ in pvlist:
            pvs.add(pvname)
    return pvs


# ---------------------------------------------------------------------------
# Filtering helpers
# ---------------------------------------------------------------------------

def _is_allowlisted_extra(pvname: str) -> bool:
    """Return True if an extra-in-sim PV is expected/intentional."""
    for suffix in EXTRA_ALLOWLIST_SUFFIXES:
        if pvname.endswith(suffix):
            return True
    for prefix in EXTRA_ALLOWLIST_PREFIXES:
        if pvname.startswith(prefix):
            return True
    return False


def _group_missing_by_device(
    missing: Set[str], by_device: Dict[str, Set[str]]
) -> Dict[str, Set[str]]:
    """Map missing PVs back to the device variable that needs them."""
    grouped: Dict[str, Set[str]] = defaultdict(set)
    for dev_name, dev_pvs in by_device.items():
        overlap = missing & dev_pvs
        if overlap:
            grouped[dev_name] |= overlap
    # Any PV not attributed to a named device goes under "<unknown>"
    attributed = set().union(*grouped.values()) if grouped else set()
    unattributed = missing - attributed
    if unattributed:
        grouped["<unknown>"] = unattributed
    return dict(grouped)


# ---------------------------------------------------------------------------
# --write: regenerate pv_inventory.py auto-generated block
# ---------------------------------------------------------------------------

_AUTOGEN_MARKER_START = "# <<< AUTO-GENERATED by check_drift.py --write — do not edit below >>>"
_AUTOGEN_MARKER_END   = "# <<< END AUTO-GENERATED >>>"

_PV_INVENTORY_HEADER = '''\
"""
sim/pv_inventory.py
-------------------
PV inventory for the IOS profile collection.

The ``by_device`` section below is AUTO-GENERATED by::

    pixi run sim-check-drift -- --write

Run that command after any change to startup/*.py devices and review the
diff before committing.  The ``get_pv_types()`` function and the motor /
scaler field helpers above the auto-generated section are hand-maintained.
"""
'''

def _write_inventory(
    by_device: Dict[str, Set[str]],
    inv_path: pathlib.Path | None = None,
) -> None:
    """Rewrite the auto-generated block in sim/pv_inventory.py.

    Only the ``build_inventory()`` return value (device→PV mapping) is
    regenerated.  The module-level helpers (get_pv_types, all_pvnames,
    motor field lists, etc.) are preserved unchanged.
    """
    inv_path = inv_path or (_SIM_DIR / "pv_inventory.py")
    original = inv_path.read_text()

    # Build the new auto-generated block
    lines: List[str] = []
    lines.append(_AUTOGEN_MARKER_START)
    lines.append("")
    lines.append("def build_inventory() -> dict:")
    lines.append('    """Auto-generated PV inventory.  Regenerate with: pixi run sim-check-drift -- --write"""')
    lines.append("    inventory: dict = {}")
    lines.append("")
    for dev_name, pvset in sorted(by_device.items()):
        lines.append(f"    # {dev_name}")
        lines.append(f"    inventory[{dev_name!r}] = [")
        for pvname in sorted(pvset):
            lines.append(f"        ({pvname!r}, 'auto'),")
        lines.append("    ]")
        lines.append("")
    lines.append("    return inventory")
    lines.append("")
    lines.append(_AUTOGEN_MARKER_END)
    new_block = "\n".join(lines)

    # Replace the auto-generated block if it exists, otherwise append it
    if _AUTOGEN_MARKER_START in original:
        start = original.index(_AUTOGEN_MARKER_START)
        end   = original.index(_AUTOGEN_MARKER_END) + len(_AUTOGEN_MARKER_END)
        new_content = original[:start] + new_block + original[end:]
    else:
        new_content = original.rstrip("\n") + "\n\n\n" + new_block + "\n"

    inv_path.write_text(new_content)


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------

class DriftReport:
    def __init__(self) -> None:
        self.fails:  List[dict] = []   # {"check": str, "pv": str, "device": str}
        self.warns:  List[dict] = []
        self.load_warnings: List[str] = []
        self.counts: Dict[str, int] = {}

    def add_fail(self, check: str, pv: str, device: str = "") -> None:
        self.fails.append({"check": check, "pv": pv, "device": device})

    def add_warn(self, check: str, pv: str, device: str = "") -> None:
        self.warns.append({"check": check, "pv": pv, "device": device})

    @property
    def has_fails(self) -> bool:
        return bool(self.fails) or bool(self.load_warnings)


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_drift_check(
    use_allowlist: bool = True,
) -> Tuple[DriftReport, Dict[str, Set[str]], Set[str], Set[str]]:
    """Run all drift checks and return the report plus raw data."""
    report = DriftReport()

    # --- Source A ---
    pvs_a, load_warnings, by_device = load_source_a()
    report.load_warnings = load_warnings
    for w in load_warnings:
        report.add_fail("load_failed", w)  # load failures are FAILs

    # --- Source B ---
    pvs_b = load_source_b()

    # --- Source I ---
    pvs_i = load_source_i()

    # --- Check 1: profile needs PV that sim doesn't serve ---
    missing = pvs_a - pvs_b
    missing_by_device = _group_missing_by_device(missing, by_device)
    for dev_name, dev_missing in sorted(missing_by_device.items()):
        for pv in sorted(dev_missing):
            report.add_fail("missing_from_sim", pv, dev_name)

    # --- Check 2: sim serves PV no profile needs ---
    extra = pvs_b - pvs_a
    for pv in sorted(extra):
        if use_allowlist and _is_allowlisted_extra(pv):
            continue
        report.add_warn("extra_in_sim", pv)

    # --- Check 3: inventory diverges from live walk ---
    inv_missing = pvs_a - pvs_i   # in profile but not inventory
    inv_extra   = pvs_i - pvs_a   # in inventory but not profile
    for pv in sorted(inv_missing):
        report.add_warn("inventory_missing", pv)
    for pv in sorted(inv_extra):
        report.add_warn("inventory_extra", pv)

    report.counts = {
        "profile_pvs":      len(pvs_a),
        "sim_pvs":          len(pvs_b),
        "inventory_pvs":    len(pvs_i),
        "missing_from_sim": len(missing),
        "extra_in_sim":     len(extra),
        "extra_in_sim_non_allowlisted": sum(
            1 for pv in extra
            if not (use_allowlist and _is_allowlisted_extra(pv))
        ),
        "inventory_missing": len(inv_missing),
        "inventory_extra":   len(inv_extra),
    }

    return report, by_device, pvs_a, pvs_b


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _format_human(
    report: DriftReport,
    by_device: Dict[str, Set[str]],
    pvs_a: Set[str],
    pvs_b: Set[str],
    strict: bool = False,
    write_mode: bool = False,
    use_allowlist: bool = True,
) -> str:
    lines: List[str] = []
    W = 70

    lines.append("=" * W)
    lines.append("IOS Sim Drift Check")
    lines.append("=" * W)

    # --- Load warnings ---
    if report.load_warnings:
        lines.append("")
        lines.append("  FAIL  Device file load errors (profile changes may be unreachable):")
        for w in report.load_warnings:
            lines.append(f"    {w}")

    # --- Missing from sim (grouped by device) ---
    missing_items = [f for f in report.fails if f["check"] == "missing_from_sim"]
    if missing_items:
        by_dev: Dict[str, List[str]] = defaultdict(list)
        for item in missing_items:
            by_dev[item["device"]].append(item["pv"])
        lines.append("")
        lines.append(f"  FAIL  {len(missing_items)} PV(s) needed by the profile but NOT served by the sim IOC.")
        lines.append("        These would cause connection timeouts in a sim session.")
        lines.append("        Add a caproto PVGroup in sim/pvgroups/ for each affected device.")
        lines.append("")
        for dev_name, pvlist in sorted(by_dev.items()):
            lines.append(f"    Device: {dev_name}  ({len(pvlist)} PVs)")
            for pv in sorted(pvlist)[:10]:
                lines.append(f"      MISSING  {pv}")
            if len(pvlist) > 10:
                lines.append(f"      ... and {len(pvlist) - 10} more (run --json for full list)")
    else:
        lines.append("")
        lines.append("  PASS  All profile PVs are served by the sim IOC.")

    # --- Extra in sim ---
    extra_items = [w for w in report.warns if w["check"] == "extra_in_sim"]
    if extra_items:
        lines.append("")
        n_al = report.counts["extra_in_sim"] - report.counts["extra_in_sim_non_allowlisted"]
        lines.append(
            f"  WARN  {len(extra_items)} sim PV(s) not requested by any profile device "
            f"({'allowlisted' if not use_allowlist else f'{n_al} allowlisted, {len(extra_items)} remaining'})."
        )
        lines.append("        These may be dead PVs that can be removed, or intentional extras.")
        for item in extra_items[:5]:
            lines.append(f"    EXTRA  {item['pv']}")
        if len(extra_items) > 5:
            lines.append(f"    ... and {len(extra_items) - 5} more (run --json for full list)")

    # --- Inventory drift ---
    inv_missing = [w for w in report.warns if w["check"] == "inventory_missing"]
    inv_extra   = [w for w in report.warns if w["check"] == "inventory_extra"]
    if inv_missing or inv_extra:
        lines.append("")
        lines.append(
            f"  WARN  sim/pv_inventory.py diverges from the live device walk: "
            f"{len(inv_missing)} missing, {len(inv_extra)} extra."
        )
        if not write_mode:
            lines.append("")
            lines.append(
                textwrap.indent(textwrap.dedent("""\
                    Recommendation: regenerate the inventory from the live profile devices.

                        pixi run sim-check-drift -- --write

                    Then review the diff:

                        git diff sim/pv_inventory.py

                    Commit it together with your device changes so the inventory
                    stays in step with the profile.
                """), "    ")
        )

    # --- Summary ---
    c = report.counts
    lines.append("")
    lines.append("-" * W)
    lines.append(
        f"Profile PVs: {c['profile_pvs']}   "
        f"Sim PVs: {c['sim_pvs']}   "
        f"Inventory PVs: {c['inventory_pvs']}"
    )
    lines.append(
        f"Missing from sim: {c['missing_from_sim']}   "
        f"Extra in sim: {c['extra_in_sim']}   "
        f"Inventory drift: {c['inventory_missing']}+{c['inventory_extra']}"
    )

    fail_count = len([f for f in report.fails if f["check"] != "load_failed"])
    fail_count += len(report.load_warnings)
    warn_count  = len(report.warns)
    effective_fails = fail_count + (warn_count if strict else 0)

    lines.append("")
    if effective_fails == 0:
        lines.append("  Result: OK" + (" (strict)" if strict else ""))
    else:
        lines.append(
            f"  Result: FAIL  ({fail_count} fail(s), {warn_count} warn(s)"
            + (f", strict mode" if strict else "")
            + ")"
        )
    lines.append("=" * W)
    return "\n".join(lines)


def _format_json(
    report: DriftReport,
    strict: bool = False,
    use_allowlist: bool = True,
) -> str:
    fail_count = len(report.fails)
    warn_count  = len(report.warns)
    out = {
        "result": "fail" if (report.has_fails or (strict and warn_count)) else "ok",
        "strict": strict,
        "counts": report.counts,
        "load_warnings": report.load_warnings,
        "fails": report.fails,
        "warns": report.warns,
    }
    return json.dumps(out, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--json", action="store_true",
        help="Output JSON instead of human-readable text (for CI)"
    )
    p.add_argument(
        "--strict", action="store_true",
        help="Promote WARNs to FAILs (non-zero exit on any WARN)"
    )
    p.add_argument(
        "--write", action="store_true",
        help=(
            "Regenerate the auto-generated block in sim/pv_inventory.py "
            "from the live device walk.  Implies a report is printed first."
        )
    )
    p.add_argument(
        "--no-allowlist", action="store_true",
        help="Disable the expected-extra-in-sim allowlist (shows all extras)"
    )
    p.add_argument(
        "--inv-path", type=pathlib.Path, default=None,
        help="Path to pv_inventory.py (default: sim/pv_inventory.py)"
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    use_allowlist = not args.no_allowlist

    # Set EPICS env for the offline walk (no live IOC needed)
    os.environ.setdefault("EPICS_CA_ADDR_LIST",     "127.0.0.1")
    os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST", "NO")

    report, by_device, pvs_a, pvs_b = run_drift_check(use_allowlist=use_allowlist)

    # Output
    if args.json:
        print(_format_json(report, strict=args.strict, use_allowlist=use_allowlist))
    else:
        print(_format_human(
            report, by_device, pvs_a, pvs_b,
            strict=args.strict,
            write_mode=args.write,
            use_allowlist=use_allowlist,
        ))

    # --write: regenerate pv_inventory.py
    if args.write:
        inv_path = args.inv_path or (_SIM_DIR / "pv_inventory.py")
        _write_inventory(by_device, inv_path)
        print(f"\n  --write: regenerated {inv_path.relative_to(_REPO)}")
        print("  Review the diff before committing:")
        print(f"    git diff {inv_path.relative_to(_REPO)}")

    # Exit code
    fail_count = len(report.fails)
    warn_count  = len(report.warns)
    if args.strict:
        return 1 if (fail_count or warn_count) else 0
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
