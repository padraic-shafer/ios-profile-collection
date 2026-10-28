"""
sim/pv_inventory.py
-------------------
Walk every ophyd Device defined in the IOS profile collection and collect the
exact set of EPICS PV names that ophyd will request at runtime.  No real EPICS
connections are made — the walk is purely structural.

This module also provides ``get_pv_types()``, which is the function referenced
by the ``pvs`` pixi task::

    pixi run pvs
    # expands to: ipython --profile-dir=. -c 'get_pv_types(); exit()'

Usage (standalone, without the full profile loaded)::

    python sim/pv_inventory.py

Usage from inside an IPython profile session::

    get_pv_types()          # prints a table
    inv = build_inventory() # returns the full dict
"""

from __future__ import annotations

import sys
import os
import types
import importlib.util
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ophyd fields that every EpicsMotor subscribes to.  This list is derived from
# ophyd.epics_motor.EpicsMotor's component definitions and covers every PV
# suffix the motor record device requests.
MOTOR_RECORD_SUFFIXES: Tuple[str, ...] = (
    ".VAL",
    ".RBV",
    ".DMOV",
    ".MOVN",
    ".STOP",
    ".SET",
    ".EGU",
    ".DESC",
    ".VELO",
    ".VMAX",
    ".ACCL",
    ".MRES",
    ".RRBV",
    ".RVAL",
    ".STUP",
    ".SPMG",
    ".HLM",
    ".LLM",
    ".HLS",
    ".LLS",
    ".RDBD",
    ".TWF",
    ".TWR",
    ".TWV",
    ".HOMF",
    ".HOMR",
    ".CNEN",
    ".DIR",
    ".OFF",
    ".DHLM",
    ".DLLM",
    ".DVAL",
    ".TDIR",
    ".MIP",
    ".MSTA",
    ".ATHM",
    ".JOGF",
    ".JOGR",
    ".HVEL",
    ".SBAS",
    ".BACC",
    ".ERES",
    ".RRES",
    ".RCNT",
    ".RTRY",
    ".MISS",
    ".UREV",
    ".LOLO",
    ".HIHI",
    ".LOW",
    ".HIGH",
    ".UEIP",
    ".URIP",
    ".SPDB",
    ".PREC",
)

# SynApps scaler-record fields for a single channel index.
def _scaler_channel_suffixes(n: int) -> List[str]:
    return [f".S{n}", f".NM{n}", f".PR{n}", f".G{n}"]

SCALER_TOP_SUFFIXES: Tuple[str, ...] = (
    ".CNT",
    ".CONT",
    ".DLY",
    ".DLY1",
    ".T",
    ".FREQ",
    ".TP",
    ".TP1",
    ".RATE",
    ".RAT1",
    ".EGU",
    "_calc5.VAL",  # norm_ch4 signal
)


# ---------------------------------------------------------------------------
# Core walk: collect (pvname, type_hint) from a Device without connecting
# ---------------------------------------------------------------------------

def _walk_device(device) -> List[Tuple[str, str]]:
    """Recursively walk an ophyd Device and yield (pvname, kind) pairs.

    Works on already-instantiated devices; does NOT connect to EPICS.
    ``kind`` is a rough category string for display purposes.
    """
    results: List[Tuple[str, str]] = []
    # ophyd stores the component instances under the same attr names
    for attr in device.component_names:
        try:
            child = getattr(device, attr)
        except Exception:
            continue
        cls_name = type(child).__name__
        if hasattr(child, "pvname"):
            # It's a signal — has a single PV name
            results.append((child.pvname, cls_name))
        elif hasattr(child, "component_names"):
            # It's a sub-Device — recurse
            results.extend(_walk_device(child))
    return results


def _motor_pvs(prefix: str) -> List[Tuple[str, str]]:
    """Return the full motor-record PV list for an EpicsMotor at *prefix*."""
    return [(prefix + suf, "MotorField") for suf in MOTOR_RECORD_SUFFIXES]


def _scaler_pvs(prefix: str, n_channels: int = 32) -> List[Tuple[str, str]]:
    """Return all scaler-record PV names for a DodgyEpicsScaler at *prefix*."""
    pvs: List[Tuple[str, str]] = []
    for suf in SCALER_TOP_SUFFIXES:
        pvs.append((prefix + suf, "ScalerField"))
    for ch in range(1, n_channels + 1):
        for suf in _scaler_channel_suffixes(ch):
            pvs.append((prefix + suf, "ScalerChannel"))
    return pvs


# ---------------------------------------------------------------------------
# Inventory builder — constructs devices from their prefix strings
# ---------------------------------------------------------------------------

def build_inventory() -> Dict[str, List[Tuple[str, str]]]:
    """Return a dict mapping device name -> list of (pvname, kind) pairs.

    This function constructs lightweight ophyd stubs (or real instances) for
    every device defined in the IOS profile collection and collects the PV set
    without connecting to EPICS.  Import-time blocking calls that would require
    real services (redis, kafka, olog, amostra, xspress3 roi_name.get …) are
    suppressed here.

    The returned mapping is the *single source of truth* used by both:
    - ``get_pv_types()``  (the pixi ``pvs`` task)
    - ``sim/pvgroups/*.py``  (caproto IOC PVGroup definitions)
    """
    import ophyd
    from ophyd import (
        EpicsMotor,
        EpicsSignal,
        EpicsSignalRO,
        Device,
        Component as Cpt,
    )

    inventory: Dict[str, List[Tuple[str, str]]] = {}

    # -- Motors (EpicsMotor) ------------------------------------------------
    # Each EpicsMotor prefix maps to the full motor-record field surface.
    motor_instances = {
        # 10-optics.py (slits, diagnostics, manipulators, KB, BDC, DM)
        "slt2":         "XF:23ID2-OP{Slt:2-Ax:Y}Mtr",
        "diag1_y":      "XF:23ID2-BI{Diag:1-Ax:Y}Mtr",
        "diag3_y":      "XF:23ID2-BI{Diag:3-Ax:Y}Mtr",
        "diag4_y":      "XF:23ID2-BI{Diag:4-Ax:Y}Mtr",
        "au_mesh":      "XF:23ID2-BI{AuMesh:1-Ax:Y}Mtr",
        "ioxas_x":      "XF:23ID2-BI{IOXAS:1-Ax:X}Mtr",
        "vortex_x":     "XF:23ID2-BI{Vortex:1-Ax:X}Mtr",
        "appes_y":      "XF:23ID2-ES{APPES:1-Ax:Y}Mtr",
        "appes_x":      "XF:23ID2-ES{APPES:1-Ax:X}Mtr",
        "appes_z":      "XF:23ID2-ES{APPES:1-Ax:Z}Mtr",
        "appes_t":      "XF:23ID2-ES{APPES:1-Ax:R}Mtr",
        "dm1_x":        "XF:23ID2-OP{DM1-Ax:X}Mtr",
        "dm1_roll":     "XF:23ID2-OP{DM1-Ax:Roll}Mtr",
        "dm1_diag":     "XF:23ID2-OP{DM1:FS-Ax:Y}Mtr",
        "dm1_slt":      "XF:23ID2-OP{DM1:HSlt-Ax:X}Mtr",
        "dm2_us_diag":  "XF:23ID2-OP{DM2:FS-Ax:Y}Mtr",
        "dm2_ds_diag":  "XF:23ID2-OP{DM2:FSPhDiod-Ax:Y}Mtr",
        "dm2_ygap":     "XF:23ID2-OP{DM2:Slt-Ax:YGap}Mtr",
        "dm2_yctr":     "XF:23ID2-OP{DM2:Slt-Ax:YCtr}Mtr",
        "dm2_xgap":     "XF:23ID2-OP{DM2:Slt-Ax:XGap}Mtr",
        "dm2_xctr":     "XF:23ID2-OP{DM2:Slt-Ax:XCtr}Mtr",
        "kb_roll":      "XF:23ID2-OP{KB:base-Ax:Theta}Mtr",
        "kb_yi":        "XF:23ID2-OP{KB:base-Ax:InB}Mtr",
        "kb_yo":        "XF:23ID2-OP{KB:base-Ax:OutB}Mtr",
        "kb_x":         "XF:23ID2-OP{KB:base-Ax:X}Mtr",
        "kb_z":         "XF:23ID2-OP{KB:base-Ax:Z}Mtr",
        "kbph_y":       "XF:23ID2-OP{KB:Pnh-Ax:Y}Mtr",
        "kbph_x":       "XF:23ID2-OP{KB:Pnh-Ax:X}Mtr",
        "kbdiag_y":     "XF:23ID2-OP{KB:Diag-Ax:Z}Mtr",
        "kbdiag_rot":   "XF:23ID2-OP{KB:Diag-Ax:Rot}Mtr",
        "hkb_pitch":    "XF:23ID2-OP{KB:MirH-Ax:Pitch}Mtr",
        "hkb_roll":     "XF:23ID2-OP{KB:MirH-Ax:Roll}Mtr",
        "vkb_pitch":    "XF:23ID2-OP{KB:MirV-Ax:Pitch}Mtr",
        "bdc_x":        "XF:23ID2-OP{IRm-Ax:X}Mtr",
        "bdc_z":        "XF:23ID2-OP{IRm-Ax:Z}Mtr",
        "bdc_y":        "XF:23ID2-OP{IRm-Ax:Y}Mtr",
        # 10-optics.py — SlitsGapCenter (slt1): four motors
        "slt1_xg":      "XF:23ID2-OP{Slt:1-Ax:XGap}Mtr",
        "slt1_xc":      "XF:23ID2-OP{Slt:1-Ax:XCtr}Mtr",
        "slt1_yg":      "XF:23ID2-OP{Slt:1-Ax:YGap}Mtr",
        "slt1_yc":      "XF:23ID2-OP{Slt:1-Ax:YCtr}Mtr",
        # 10-optics.py — PGM motors
        "pgm_pit":      "XF:23ID2-OP{Mono-Ax:MirP}Mtr",
        "pgm_x":        "XF:23ID2-OP{Mono-Ax:MirX}Mtr",
        "pgm_grt_pit":  "XF:23ID2-OP{Mono-Ax:GrtP}Mtr",
        "pgm_grt_x":    "XF:23ID2-OP{Mono-Ax:GrtX}Mtr",
        # 10-optics.py — M3A (MotorMirror)
        "m3a_x":        "XF:23ID2-OP{Mir:3A-Ax:XAvg}Mtr",
        "m3a_pit":      "XF:23ID2-OP{Mir:3A-Ax:P}Mtr",
        "m3a_bdr":      "XF:23ID2-OP{Mir:3A-Ax:Bdr}Mtr",
    }
    for name, prefix in motor_instances.items():
        inventory[f"motor:{name}"] = _motor_pvs(prefix)

    # -- Scaler (DodgyEpicsScaler) ------------------------------------------
    inventory["sclr"] = _scaler_pvs("XF:23ID2-ES{Sclr:1}")

    # -- Standalone EpicsSignal / EpicsSignalRO PVs -------------------------
    # Collected verbatim from 10-machine.py, 10-optics.py, 11-valves.py,
    # 20-detectors.py, 23-devices.py, 99-settings.py, 97-misc.py.
    standalone_pvs: List[Tuple[str, str]] = [
        # 10-optics.py standalone signals
        ("XF:23ID2-OP{Mir:3B-Ax:Pit}Mtr_POS_SP",          "EpicsSignal"),
        ("XF:23ID2-BI{ExitSlt-Cam:1}Stats1:CentroidX_RBV", "EpicsSignalRO"),
        ("XF:23IDA-OP:2{Mir:1A-Ax:FPit}Mtr_POS_SP",        "EpicsSignal"),
        ("XF:23IDA-OP:2{Mir:1A-Ax:FPit}Mtr_MON",           "EpicsSignal"),
        ("XF:23ID2-OP{FBck}PID-SP",                         "EpicsSignal"),
        ("XF:23IDA-OP:2{Mir:1A-Ax:Pit}Mtr_POS_SP",         "EpicsSignal"),
        ("XF:23IDA-OP:2{Mir:1A-Ax:Pit}Mtr_MON",            "EpicsSignal"),
        ("XF:23IDA-OP:2{Mir:1A}MOVE_CMD.PROC",              "EpicsSignal"),
        ("XF:23IDA-OP:2{Mir:1A-Ax:Pit}Mtr_TWN_CMD.PROC",   "EpicsSignal"),
        ("XF:23IDA-OP:2{Mir:1A-Ax:Pit}Mtr_TWP_CMD.PROC",   "EpicsSignal"),
        ("XF:23IDA-OP:2{Mir:1A-Ax:Pit}Mtr_TWV_SP",         "EpicsSignal"),
        # 11-valves.py standalone signals
        ("XF:23ID2-VA{Diag:03-GV:1}Cmd:Opn-Cmd",           "EpicsSignal"),
        ("XF:23ID2-VA{Mir:3-GV:1}Cmd:Opn-Cmd",             "EpicsSignal"),
        ("XF:23ID2-VA{Slt:3-GV:1}Cmd:Opn-Cmd",             "EpicsSignal"),
        ("XF:23ID2-VA{Slt:1-GV:1}Cmd:Opn-Cmd",             "EpicsSignal"),
        ("XF:23ID2-VA{Pmp:Inl:01-GV:1}Cmd:Opn-Cmd",        "EpicsSignal"),
        ("XF:23ID2-VA{Pmp:Inl:02-GV:1}Cmd:Opn-Cmd",        "EpicsSignal"),
        ("XF:23ID2-VA{Mon-GV:1}Cmd:Opn-Cmd",               "EpicsSignal"),
        ("XF:23ID2-VA{Diag:01-GV:1}Cmd:Opn-Cmd",           "EpicsSignal"),
        ("XF:23ID2-VA{Diag:03-GV:1}Cmd:Cls-Cmd",           "EpicsSignal"),
        ("XF:23ID2-VA{Mir:3-GV:1}Cmd:Cls-Cmd",             "EpicsSignal"),
        ("XF:23ID2-VA{Diag:03-GV:1}Cmd:Opn-Cmd",           "EpicsSignal"),  # dup
        ("XF:23ID2-VA{Mir:3-GV:1}Cmd:Opn-Cmd",             "EpicsSignal"),  # dup
        ("XF:23ID2-VA{IOXAS-GV:4}Cmd:Opn-Cmd",             "EpicsSignal"),
        ("XF:23ID2-VA{IOXAS-GV:4}Cmd:Cls-Cmd",             "EpicsSignal"),
        ("XF:23ID2-VA{IOXAS-GV:5}Cmd:Opn-Cmd",             "EpicsSignal"),
        ("XF:23ID2-VA{IOXAS-GV:5}Cmd:Cls-Cmd",             "EpicsSignal"),
        ("XF:23ID2-OP{FBck}Sts:FB-Sel",                    "EpicsSignal"),
        # 20-detectors.py standalone signals
        ("XF:23ID-SR{}I-I",                                 "EpicsSignal"),
        ("XF:23ID2-ES{Sclr:1}_calc5.VAL",                  "EpicsSignal"),
        ("XF:23ID2-ES{Sclr:1}.TP",                         "EpicsSignal"),
        ("XF:23ID2-ES{CurrAmp:3}Gain:Val-SP",               "EpicsSignal"),
        ("XF:23ID2-ES{CurrAmp:3}Gain:Decade-SP",            "EpicsSignal"),
        ("XF:23ID2-ES{CurrAmp:2}Gain:Val-SP",               "EpicsSignal"),
        ("XF:23ID2-ES{CurrAmp:2}Gain:Decade-SP",            "EpicsSignal"),
        ("XF:23ID2-ES{CurrAmp:1}Gain:Val-SP",               "EpicsSignal"),
        ("XF:23ID2-ES{CurrAmp:1}Gain:Decade-SP",            "EpicsSignal"),
        ("XF:23ID-ID{EPU:1}Val:Table-Sel",                  "EpicsSignal"),
        ("XF:23ID-ID{EPU:1-FLT}Val:InpOff1-SP",             "EpicsSignal"),
        ("XF:23ID2-OP{FBck}Sts:FB-Sel",                    "EpicsSignal"),  # dup
        # 23-devices.py
        ("XF:23ID2-ES{SPECS-PS1}Mode:Opr-Sel",              "EpicsSignal"),
        ("XF:23ID2-ES{SPECS-PS1}Cmd:Degas-Cmd",             "EpicsSignal"),
        # 99-settings.py suspenders
        ("XF:23ID-PPS{Sh:FE}Pos-Sts",                      "EpicsSignalRO"),
        ("XF:23ID2-PPS{PSh}Pos-Sts",                       "EpicsSignalRO"),
        # 97-misc.py standalone
        ("XF:23IDA-UT{DI}P:Supply-I",                      "EpicsSignalRO"),
        ("XF:23IDA-UT{DI}P:Return-I",                      "EpicsSignalRO"),
        ("XF:23ID1-OP{TCtrl:1-Chan:A}T-I",                 "EpicsSignalRO"),
        ("XF:23ID1-OP{TCtrl:1-Chan:C}T-I",                 "EpicsSignalRO"),
        ("XF:23ID1-OP{TCtrl:1-Chan:B}T-I",                 "EpicsSignalRO"),
        ("XF:23ID1-OP{TCtrl:1-Chan:D}T-I",                 "EpicsSignalRO"),
        ("XF:23ID1-OP{TCtrl:1-Chan:D5}T-I",                "EpicsSignalRO"),
        ("XF:23ID2-OP{Mon-Mir}T-I",                        "EpicsSignalRO"),
        ("XF:23ID2-OP{Mon-Grt:1}T-I",                      "EpicsSignalRO"),
        ("XF:23ID2-OP{Mon-Grt:2}T-I",                      "EpicsSignalRO"),
        ("XF:23ID2-BI{ExitSlt-Cam:1}Stats1:CentroidX_RBV", "EpicsSignalRO"),  # dup
        # 97-misc.py yag_centroid (module-scope reassignment)
        ("XF:23ID2-BI{ExitSlt-Cam:1}Stats1:CentroidX_RBV", "EpicsSignalRO"),
    ]
    inventory["standalone_signals"] = standalone_pvs

    # -- Valve device (valve_appes) -----------------------------------------
    valve_appes_prefix = "XF:23ID2-VA{APPES-GV:3}"
    inventory["valve_appes"] = [
        (valve_appes_prefix + "Cmd:Opn-Cmd", "EpicsSignal"),
        (valve_appes_prefix + "Cmd:Cls-Cmd", "EpicsSignal"),
        (valve_appes_prefix + "Pos-Sts",     "EpicsSignal"),
    ]

    # -- TwoButtonShutter devices -------------------------------------------
    # fe_shutter, ds_shutter, us_shutter
    shutter_defs = {
        "fe_shutter": "XF:23ID-PPS{Sh:FE}",
        "ds_shutter": "XF:23ID2-PPS{PSh}",
        "us_shutter": "XF:23ID2-PPS:2{PSh}",
    }
    for sname, sprefix in shutter_defs.items():
        inventory[sname] = [
            (sprefix + "Cmd:Opn-Cmd",    "EpicsSignal(enum)"),
            (sprefix + "Cmd:Cls-Cmd",    "EpicsSignal(enum)"),
            (sprefix + "Pos-Sts",        "EpicsSignalRO(enum)"),
            (sprefix + "Sts:FailCls-Sts","EpicsSignalRO(enum)"),
            (sprefix + "Sts:FailOpn-Sts","EpicsSignalRO(enum)"),
        ]

    # -- EPU1 / EPU2 (10-machine.py) ----------------------------------------
    # EPU1: gap, phase, flt (Interpolator), rlt (Interpolator), table
    epu1_prefix = "XF:23ID-ID{EPU:1"
    inventory["epu1"] = [
        # GapMotor1
        (epu1_prefix + "-Ax:Gap}Pos-I",              "EpicsSignalRO"),
        (epu1_prefix + "-Ax:Gap}Pos-SP",             "EpicsSignal"),
        ("SR:C23-ID:G1A{EPU:1-Ax:Gap}-Mtr.STOP",     "EpicsSignal"),
        # PhaseMotor1
        (epu1_prefix + "-Ax:Phase}Pos-I",            "EpicsSignalRO"),
        (epu1_prefix + "-Ax:Phase}Pos-SP",           "EpicsSignal"),
        ("SR:C23-ID:G1A{EPU:1-Ax:Phase}-Mtr.STOP",   "EpicsSignal"),
        # Interpolator flt
        (epu1_prefix + "-FLT}Val:Inp1-SP",           "EpicsSignal"),
        (epu1_prefix + "-FLT}Val:InpOff1-SP",        "EpicsSignal"),
        (epu1_prefix + "-FLT}Enbl:Inp1-Sel",         "EpicsSignal"),
        (epu1_prefix + "-FLT}Val:Inp1-SP.DOL$",      "EpicsSignal"),
        (epu1_prefix + "-FLT}Val:Out1-I",            "EpicsSignalRO"),
        (epu1_prefix + "-FLT}Enbl:Out1-Sel",         "EpicsSignalRO"),
        (epu1_prefix + "-FLT}Calc1.OUT$",            "EpicsSignal"),
        (epu1_prefix + "-FLT}Val:DBand1-SP",         "EpicsSignal"),
        (epu1_prefix + "-FLT}Val:OutDrv1-I",         "EpicsSignalRO"),
        (epu1_prefix + "-FLT}Sts:Interp1-Sts",       "EpicsSignalRO"),
        # Interpolator rlt
        (epu1_prefix + "-RLT}Val:Inp1-SP",           "EpicsSignal"),
        (epu1_prefix + "-RLT}Val:InpOff1-SP",        "EpicsSignal"),
        (epu1_prefix + "-RLT}Enbl:Inp1-Sel",         "EpicsSignal"),
        (epu1_prefix + "-RLT}Val:Inp1-SP.DOL$",      "EpicsSignal"),
        (epu1_prefix + "-RLT}Val:Out1-I",            "EpicsSignalRO"),
        (epu1_prefix + "-RLT}Enbl:Out1-Sel",         "EpicsSignalRO"),
        (epu1_prefix + "-RLT}Calc1.OUT$",            "EpicsSignal"),
        (epu1_prefix + "-RLT}Val:DBand1-SP",         "EpicsSignal"),
        (epu1_prefix + "-RLT}Val:OutDrv1-I",         "EpicsSignalRO"),
        (epu1_prefix + "-RLT}Sts:Interp1-Sts",       "EpicsSignalRO"),
        # Table
        (epu1_prefix + "}Val:Table-Sel",             "EpicsSignal"),
    ]
    epu2_prefix = "XF:23ID-ID{EPU:2"
    inventory["epu2"] = [
        (epu2_prefix + "-Ax:Gap}Pos-I",              "EpicsSignalRO"),
        (epu2_prefix + "-Ax:Gap}Pos-SP",             "EpicsSignal"),
        ("SR:C23-ID:G1A{EPU:2-Ax:Gap}-Mtr.STOP",     "EpicsSignal"),
        (epu2_prefix + "-Ax:Phase}Pos-I",            "EpicsSignalRO"),
        (epu2_prefix + "-Ax:Phase}Pos-SP",           "EpicsSignal"),
        ("SR:C23-ID:G1A{EPU:2-Ax:Phase}-Mtr.STOP",   "EpicsSignal"),
    ]

    # -- Mirror devices (10-optics.py) --------------------------------------
    # MirrorAxis uses Mtr_MON / Mtr_POS_SP per axis,
    # plus parent-level MOVE_CMD.PROC / STOP_CMD.PROC / BUSY_STS.
    def _mirror_pvs(prefix: str, axes=("Z", "Y", "X", "Pit", "Yaw", "Rol")) -> List[Tuple[str, str]]:
        pvs = []
        for ax in axes:
            p = f"{prefix}-Ax:{ax}}}"
            pvs += [
                (f"{p}Mtr_MON",              "EpicsSignalRO"),
                (f"{p}Mtr_POS_SP",           "EpicsSignal"),
            ]
        pvs += [
            (f"{prefix}}}MOVE_CMD.PROC",     "EpicsSignal"),
            (f"{prefix}}}STOP_CMD.PROC",     "EpicsSignal"),
            (f"{prefix}}}BUSY_STS",          "EpicsSignalRO"),
        ]
        return pvs

    inventory["m1a"]  = _mirror_pvs("XF:23IDA-OP:1{Mir:1")
    inventory["m1b1"] = _mirror_pvs("XF:23IDA-OP:2{Mir:1A") + [
        # FeedbackLoop on m1b1
        ("XF:23ID2-OP{FBck}Sts:FB-Sel",   "EpicsSignal"),
        ("XF:23ID2-OP{FBck}PID-SP",        "EpicsSignal"),
        ("XF:23ID2-OP{FBck}PID.VAL",       "EpicsSignalRO"),
        ("XF:23ID2-OP{FBck}PID.CVAL",      "EpicsSignalRO"),
        ("XF:23ID2-OP{FBck}PID.OVAL",      "EpicsSignalRO"),
        ("XF:23ID2-OP{FBck}PID.Err",       "EpicsSignalRO"),
        ("XF:23ID2-OP{FBck}PID.DRVH",      "EpicsSignal"),
        ("XF:23ID2-OP{FBck}PID.DRVL",      "EpicsSignal"),
        ("XF:23ID2-OP{FBck}PID.DT",        "EpicsSignalRO"),
        ("XF:23ID2-OP{FBck}PID.MDT",       "EpicsSignal"),
        ("XF:23ID2-OP{FBck}PID.SCAN",      "EpicsSignal"),
        ("XF:23ID2-OP{FBck}Val:Sbl-SP",    "EpicsSignal"),
    ]
    inventory["m1b2"] = _mirror_pvs("XF:23IDA-OP:2{Mir:1B")
    inventory["m3b"]  = _mirror_pvs("XF:23ID2-OP{Mir:3B")

    # -- PGM (10-optics.py) ------------------------------------------------
    pgm_prefix = "XF:23ID2-OP{Mono"
    inventory["pgm"] = [
        (pgm_prefix + "}Enrgy-I",            "EpicsSignalRO"),
        (pgm_prefix + "}Enrgy-SP",           "EpicsSignal"),
        (pgm_prefix + "}Cmd:Stop-Cmd",       "EpicsSignal"),
        # MonoFly
        (pgm_prefix + "}Enrgy:Start-SP",     "EpicsSignal"),
        (pgm_prefix + "}Enrgy:Stop-SP",      "EpicsSignal"),
        (pgm_prefix + "}Enrgy:FlyVelo-SP",   "EpicsSignal"),
        (pgm_prefix + "}Cmd:FlyStart-Cmd.PROC", "EpicsSignal"),
        (pgm_prefix + "}Cmd:Stop-Cmd.PROC",  "EpicsSignal"),
        (pgm_prefix + "}Sts:Scan-Sts",       "EpicsSignalRO"),
        (pgm_prefix + "}Sts:Move-Sts",       "EpicsSignalRO"),
        # PGM axis motors (EpicsMotor embedded in PGM Device)
    ] + _motor_pvs(pgm_prefix + "-Ax:MirP}Mtr") \
      + _motor_pvs(pgm_prefix + "-Ax:MirX}Mtr") \
      + _motor_pvs(pgm_prefix + "-Ax:GrtP}Mtr") \
      + _motor_pvs(pgm_prefix + "-Ax:GrtX}Mtr")

    # -- Vortex MCA (01-classes.py / 20-detectors.py) ----------------------
    # EpicsMCA (mca1) + EpicsDXP (dxp1:) at XF:23ID2-ES{Vortex}
    vortex_prefix = "XF:23ID2-ES{Vortex}"
    # EpicsMCA fields (from ophyd source, mca1 suffix)
    mca_prefix = vortex_prefix + "mca1"
    dxp_prefix = vortex_prefix + "dxp1:"
    inventory["vortex"] = [
        # EpicsMCA core fields
        (mca_prefix,                                "EpicsMCA.spectrum(waveform)"),
        (mca_prefix + ".ERAS",                     "EpicsMCA.erase"),
        (mca_prefix + ".STRT",                     "EpicsMCA.start"),
        (mca_prefix + ".ERST",                     "EpicsMCA.erase_start"),
        (mca_prefix + ".ACQG",                     "EpicsMCA.acquiring"),
        (mca_prefix + ".PRTM",                     "EpicsMCA.preset_real_time"),
        (mca_prefix + ".PLTM",                     "EpicsMCA.preset_live_time"),
        (mca_prefix + ".ERTM",                     "EpicsMCA.elapsed_real_time"),
        (mca_prefix + ".ELTM",                     "EpicsMCA.elapsed_live_time"),
        (mca_prefix + ".DTIM",                     "EpicsMCA.dead_time"),
        (mca_prefix + ".IDTIM",                    "EpicsMCA.idle_time"),
        (mca_prefix + ".NUSE",                     "EpicsMCA.nuse"),
        # ROIs (roi0..roi31 — but profile uses roi0..roi4)
        *[(f"{mca_prefix}.R{i}",  f"EpicsMCA.roi{i}.count")  for i in range(5)],
        *[(f"{mca_prefix}.R{i}LO", f"EpicsMCA.roi{i}.lo_chan") for i in range(5)],
        *[(f"{mca_prefix}.R{i}HI", f"EpicsMCA.roi{i}.hi_chan") for i in range(5)],
        *[(f"{mca_prefix}.R{i}NM", f"EpicsMCA.roi{i}.name")   for i in range(5)],
        *[(f"{mca_prefix}.R{i}BG", f"EpicsMCA.roi{i}.net_count") for i in range(5)],
        # EpicsDXP fields (subset used by ophyd EpicsDXP)
        (dxp_prefix + "PeakingTime",               "EpicsDXP.peaking_time"),
        (dxp_prefix + "EnergyThreshold",           "EpicsDXP.energy_threshold"),
        (dxp_prefix + "TriggerThreshold",          "EpicsDXP.trigger_threshold"),
        (dxp_prefix + "BaselineThreshold",         "EpicsDXP.baseline_threshold"),
        (dxp_prefix + "MaxWidth",                  "EpicsDXP.max_width"),
    ]

    # -- SPECS Analyzer (21-specs_analyzer.py) -----------------------------
    specs_prefix = "XF:23ID2-ES{SPECS}"
    cam_prefix = specs_prefix + "cam1:"
    inventory["specs"] = [
        # CamBase standard fields
        (cam_prefix + "Acquire",                   "EpicsSignal"),
        (cam_prefix + "AcquireBusy",               "EpicsSignalRO"),
        (cam_prefix + "AcquireTime",               "EpicsSignal"),
        (cam_prefix + "AcquireTime_RBV",           "EpicsSignalRO"),
        (cam_prefix + "AcquirePeriod",             "EpicsSignal"),
        (cam_prefix + "AcquirePeriod_RBV",         "EpicsSignalRO"),
        (cam_prefix + "NumImages",                 "EpicsSignal"),
        (cam_prefix + "NumImages_RBV",             "EpicsSignalRO"),
        (cam_prefix + "NumImagesCounter_RBV",      "EpicsSignalRO"),
        (cam_prefix + "NumExposures",              "EpicsSignal"),
        (cam_prefix + "NumExposures_RBV",          "EpicsSignalRO"),
        (cam_prefix + "ImageMode",                 "EpicsSignal"),
        (cam_prefix + "ImageMode_RBV",             "EpicsSignalRO"),
        (cam_prefix + "TriggerMode",               "EpicsSignal"),
        (cam_prefix + "TriggerMode_RBV",           "EpicsSignalRO"),
        (cam_prefix + "DetectorState_RBV",         "EpicsSignalRO"),
        (cam_prefix + "ArrayRate_RBV",             "EpicsSignalRO"),
        (cam_prefix + "DataType",                  "EpicsSignal"),
        (cam_prefix + "DataType_RBV",              "EpicsSignalRO"),
        (cam_prefix + "ColorMode",                 "EpicsSignal"),
        (cam_prefix + "ColorMode_RBV",             "EpicsSignalRO"),
        (cam_prefix + "ArraySizeX_RBV",            "EpicsSignalRO"),
        (cam_prefix + "ArraySizeY_RBV",            "EpicsSignalRO"),
        (cam_prefix + "ArraySize_RBV",             "EpicsSignalRO"),
        (cam_prefix + "StatusMessage_RBV",         "EpicsSignalRO"),
        (cam_prefix + "StringToServer_RBV",        "EpicsSignalRO"),
        (cam_prefix + "StringFromServer_RBV",      "EpicsSignalRO"),
        (cam_prefix + "ShutterMode",               "EpicsSignal"),
        (cam_prefix + "ShutterMode_RBV",           "EpicsSignalRO"),
        (cam_prefix + "ShutterControl",            "EpicsSignal"),
        (cam_prefix + "ShutterControl_RBV",        "EpicsSignalRO"),
        (cam_prefix + "ShutterStatus_RBV",         "EpicsSignalRO"),
        (cam_prefix + "ShutterOpenDelay",          "EpicsSignal"),
        (cam_prefix + "ShutterOpenDelay_RBV",      "EpicsSignalRO"),
        (cam_prefix + "ShutterCloseDelay",         "EpicsSignal"),
        (cam_prefix + "ShutterCloseDelay_RBV",     "EpicsSignalRO"),
        (cam_prefix + "Temperature",               "EpicsSignal"),
        (cam_prefix + "Temperature_RBV",           "EpicsSignalRO"),
        (cam_prefix + "TemperatureActual",         "EpicsSignalRO"),
        # SpecsDetectorCam custom fields
        (cam_prefix + "CONNECTED_RBV",             "EpicsSignalRO"),
        (cam_prefix + "CONNECT",                   "EpicsSignal"),
        (cam_prefix + "StatusMessage_RBV",         "EpicsSignalRO"),
        (cam_prefix + "SERVER_NAME_RBV",           "EpicsSignalRO"),
        (cam_prefix + "PROTOCOL_VERSION_RBV",      "EpicsSignalRO"),
        (cam_prefix + "PASS_ENERGY",               "EpicsSignal"),
        (cam_prefix + "PASS_ENERGY_RBV",           "EpicsSignalRO"),
        (cam_prefix + "LOW_ENERGY",                "EpicsSignal"),
        (cam_prefix + "LOW_ENERGY_RBV",            "EpicsSignalRO"),
        (cam_prefix + "HIGH_ENERGY",               "EpicsSignal"),
        (cam_prefix + "HIGH_ENERGY_RBV",           "EpicsSignalRO"),
        (cam_prefix + "ENERGY_WIDTH_RBV",          "EpicsSignalRO"),
        (cam_prefix + "KINETIC_ENERGY",            "EpicsSignal"),
        (cam_prefix + "KINETIC_ENERGY_RBV",        "EpicsSignalRO"),
        (cam_prefix + "RETARDING_RATIO",           "EpicsSignal"),
        (cam_prefix + "RETARDING_RATIO_RBV",       "EpicsSignalRO"),
        (cam_prefix + "STEP_SIZE",                 "EpicsSignal"),
        (cam_prefix + "STEP_SIZE_RBV",             "EpicsSignalRO"),
        (cam_prefix + "VALUES",                    "EpicsSignal"),
        (cam_prefix + "VALUES_RBV",                "EpicsSignalRO"),
        (cam_prefix + "SAMPLES",                   "EpicsSignal"),
        (cam_prefix + "SAMPLES_RBV",               "EpicsSignalRO"),
        (cam_prefix + "LENS_MODE",                 "EpicsSignal"),
        (cam_prefix + "LENS_MODE_RBV",             "EpicsSignalRO"),
        (cam_prefix + "SCAN_RANGE",                "EpicsSignal"),
        (cam_prefix + "SCAN_RANGE_RBV",            "EpicsSignalRO"),
        (cam_prefix + "ACQ_MODE",                  "EpicsSignal"),
        (cam_prefix + "ACQ_MODE_RBV",              "EpicsSignalRO"),
        (cam_prefix + "DEFINE_SPECTRUM",           "EpicsSignal"),
        (cam_prefix + "DEFINE_SPECTRUM_RBV",       "EpicsSignalRO"),
        (cam_prefix + "VALIDATE_SPECTRUM",         "EpicsSignal"),
        (cam_prefix + "VALIDATE_SPECTRUM_RBV",     "EpicsSignalRO"),
        (cam_prefix + "SAFE_STATE",                "EpicsSignal"),
        (cam_prefix + "SAFE_STATE_RBV",            "EpicsSignalRO"),
        (cam_prefix + "PAUSE_RBV",                 "EpicsSignal"),
        (cam_prefix + "PAUSE_RBV_RBV",             "EpicsSignalRO"),
        (cam_prefix + "CURRENT_POINT_RBV",         "EpicsSignalRO"),
        (cam_prefix + "CURRENT_CHANNEL_RBV",       "EpicsSignalRO"),
        (cam_prefix + "REGION_TIME_LEFT_RBV",      "EpicsSignalRO"),
        (cam_prefix + "REGION_PROGRESS_RBV",       "EpicsSignalRO"),
        (cam_prefix + "TOTAL_TIME_LEFT_RBV",       "EpicsSignalRO"),
        (cam_prefix + "PROGRESS_RBV",              "EpicsSignalRO"),
        (cam_prefix + "TOTAL_POINTS_ITERTION_RBV", "EpicsSignalRO"),
        (cam_prefix + "TOTAL_POINTS_RBV",          "EpicsSignalRO"),
        # Stats5 plugin (count + count_enable)
        (specs_prefix + "Stats5:Total_RBV",        "EpicsSignalRO"),
        (specs_prefix + "Stats5:EnableCallbacks",  "EpicsSignal"),
        # Stats5 full plugin PVs (needed for plugin to connect)
        (specs_prefix + "Stats5:PortName_RBV",     "EpicsSignalRO"),
        (specs_prefix + "Stats5:NDArrayPort",      "EpicsSignal"),
        (specs_prefix + "Stats5:NDArrayPort_RBV",  "EpicsSignalRO"),
        (specs_prefix + "Stats5:BlockingCallbacks","EpicsSignal"),
        (specs_prefix + "Stats5:MinX_RBV",         "EpicsSignalRO"),
        (specs_prefix + "Stats5:MinY_RBV",         "EpicsSignalRO"),
        (specs_prefix + "Stats5:MaxX_RBV",         "EpicsSignalRO"),
        (specs_prefix + "Stats5:MaxY_RBV",         "EpicsSignalRO"),
        (specs_prefix + "Stats5:MeanValue_RBV",    "EpicsSignalRO"),
        (specs_prefix + "Stats5:Sigma_RBV",        "EpicsSignalRO"),
        (specs_prefix + "Stats5:Net_RBV",          "EpicsSignalRO"),
        (specs_prefix + "Stats5:MinValue_RBV",     "EpicsSignalRO"),
        (specs_prefix + "Stats5:MaxValue_RBV",     "EpicsSignalRO"),
    ]

    # -- Xspress3 (22-xspress3.py) -----------------------------------------
    # build_xspress3_class with channel_numbers=(1,), mcaroi_numbers=(1,2,3,4)
    xs3_prefix = "XF:23ID2-ES{Xsp:1}:"
    inventory["xs3"] = _xspress3_pvs(xs3_prefix, channels=(1,), mcarois=(1, 2, 3, 4))

    return inventory


def _xspress3_pvs(
    prefix: str,
    channels: tuple = (1,),
    mcarois: tuple = (1, 2, 3, 4),
) -> List[Tuple[str, str]]:
    """Return the PV list for the Xspress3 detector as built by nslsii."""
    pvs: List[Tuple[str, str]] = []

    # Detector-level (Xspress3Detector / CamBase)
    det_cam = prefix + "det1:"
    for suffix, kind in [
        ("Acquire",          "EpicsSignal"),
        ("AcquireBusy",      "EpicsSignalRO"),
        ("AcquireTime",      "EpicsSignal"),
        ("AcquireTime_RBV",  "EpicsSignalRO"),
        ("NumImages",        "EpicsSignal"),
        ("NumImages_RBV",    "EpicsSignalRO"),
        ("TriggerMode",      "EpicsSignal"),
        ("TriggerMode_RBV",  "EpicsSignalRO"),
        ("DetectorState_RBV","EpicsSignalRO"),
        ("StatusMessage_RBV","EpicsSignalRO"),
        ("Erase",            "EpicsSignal"),
        ("ERASE",            "EpicsSignal"),
        ("UPDATE",           "EpicsSignal"),
        ("NumChannels",      "EpicsSignal"),
        ("NumChannels_RBV",  "EpicsSignalRO"),
        ("SCA_TimePerPoint", "EpicsSignal"),
        ("CTRL_MCA_ROI",     "EpicsSignal"),
        ("CTRL_DTC",         "EpicsSignal"),
        ("DataType",         "EpicsSignal"),
        ("DataType_RBV",     "EpicsSignalRO"),
        ("ArrayCounter",     "EpicsSignal"),
        ("ArrayCounter_RBV", "EpicsSignalRO"),
        ("ArrayRate_RBV",    "EpicsSignalRO"),
    ]:
        pvs.append((det_cam + suffix, kind))

    # Per-channel PVs
    for ch in channels:
        ch_prefix = prefix + f"C{ch}_"
        for suffix, kind in [
            ("SCA:ArrayData",          "EpicsSignalRO(waveform)"),
            ("MCA:ArrayData",          "EpicsSignalRO(waveform)"),
            ("ROI:ArrayData",          "EpicsSignalRO(waveform)"),
            ("DTC_FLAGS",              "EpicsSignal"),
            ("DTC_AEG",                "EpicsSignal"),
            ("DTC_AEO",                "EpicsSignal"),
            ("DTC_IWG",                "EpicsSignal"),
            ("DTC_IWO",                "EpicsSignal"),
            ("DTC_OWG",                "EpicsSignal"),
            ("DTC_OWO",                "EpicsSignal"),
            ("GNSCA",                  "EpicsSignalRO"),
        ]:
            pvs.append((ch_prefix + suffix, kind))
        # Per mcaroi
        for roi in mcarois:
            roi_prefix = prefix + f"C{ch}_MCA_ROI{roi}_"
            pvs += [
                (roi_prefix + "CallbacksOK_RBV",  "EpicsSignalRO"),
                (roi_prefix + "MinX",              "EpicsSignal"),
                (roi_prefix + "MinX_RBV",          "EpicsSignalRO"),
                (roi_prefix + "SizeX",             "EpicsSignal"),
                (roi_prefix + "SizeX_RBV",         "EpicsSignalRO"),
                (roi_prefix + "Total_RBV",         "EpicsSignalRO"),
                (roi_prefix + "Net_RBV",           "EpicsSignalRO"),
                (roi_prefix + "ROIName",           "EpicsSignal"),    # roi_name (.get() at import)
                (roi_prefix + "ROIName_RBV",       "EpicsSignalRO"),
            ]

    # HDF5 plugin
    hdf_prefix = prefix + "HDF1:"
    for suffix, kind in [
        ("EnableCallbacks",          "EpicsSignal"),
        ("EnableCallbacks_RBV",      "EpicsSignalRO"),
        ("PortName_RBV",             "EpicsSignalRO"),
        ("NDArrayPort",              "EpicsSignal"),
        ("NDArrayPort_RBV",          "EpicsSignalRO"),
        ("BlockingCallbacks",        "EpicsSignal"),
        ("FilePath",                 "EpicsSignal(char_waveform)"),
        ("FilePath_RBV",             "EpicsSignalRO(char_waveform)"),
        ("FilePathExists_RBV",       "EpicsSignalRO"),
        ("FileName",                 "EpicsSignal(char_waveform)"),
        ("FileName_RBV",             "EpicsSignalRO(char_waveform)"),
        ("FileNumber",               "EpicsSignal"),
        ("FileNumber_RBV",           "EpicsSignalRO"),
        ("FileTemplate",             "EpicsSignal(char_waveform)"),
        ("FileTemplate_RBV",         "EpicsSignalRO(char_waveform)"),
        ("FullFileName_RBV",         "EpicsSignalRO(char_waveform)"),
        ("AutoIncrement",            "EpicsSignal"),
        ("AutoIncrement_RBV",        "EpicsSignalRO"),
        ("AutoSave",                 "EpicsSignal"),
        ("AutoSave_RBV",             "EpicsSignalRO"),
        ("FileWriteMode",            "EpicsSignal"),
        ("FileWriteMode_RBV",        "EpicsSignalRO"),
        ("NumCapture",               "EpicsSignal"),
        ("NumCapture_RBV",           "EpicsSignalRO"),
        ("NumCaptured_RBV",          "EpicsSignalRO"),
        ("Capture",                  "EpicsSignal"),
        ("Capture_RBV",              "EpicsSignalRO"),
        ("WriteFile",                "EpicsSignal"),
        ("WriteFile_RBV",            "EpicsSignalRO"),
        ("ReadFile",                 "EpicsSignal"),
        ("ReadFile_RBV",             "EpicsSignalRO"),
        ("CreateDirectory",          "EpicsSignal"),
        ("CreateDirectory_RBV",      "EpicsSignalRO"),
        ("ArrayCounter",             "EpicsSignal"),
        ("ArrayCounter_RBV",         "EpicsSignalRO"),
        ("ArrayRate_RBV",            "EpicsSignalRO"),
        ("Compression",              "EpicsSignal"),
        ("Compression_RBV",          "EpicsSignalRO"),
        ("NumRowChunks",             "EpicsSignal"),
        ("NumRowChunks_RBV",         "EpicsSignalRO"),
        ("NumColChunks",             "EpicsSignal"),
        ("NumColChunks_RBV",         "EpicsSignalRO"),
        ("NumFramesChunks",          "EpicsSignal"),
        ("NumFramesChunks_RBV",      "EpicsSignalRO"),
        ("NDAttributeChunk",         "EpicsSignal"),
        ("NDAttributeChunk_RBV",     "EpicsSignalRO"),
        ("BoundaryAlign",            "EpicsSignal"),
        ("BoundaryAlign_RBV",        "EpicsSignalRO"),
        ("BoundaryThreshold",        "EpicsSignal"),
        ("BoundaryThreshold_RBV",    "EpicsSignalRO"),
        ("IOSpeed",                  "EpicsSignalRO"),
        ("StoreAttr",                "EpicsSignal"),
        ("StoreAttr_RBV",            "EpicsSignalRO"),
        ("StorePerform",             "EpicsSignal"),
        ("StorePerform_RBV",         "EpicsSignalRO"),
        ("WriteStatus",              "EpicsSignalRO"),
        ("WriteMessage",             "EpicsSignalRO(char_waveform)"),
        ("XMLFileName",              "EpicsSignal(char_waveform)"),
        ("XMLFileName_RBV",          "EpicsSignalRO(char_waveform)"),
        ("LazyOpen",                 "EpicsSignal"),
        ("LazyOpen_RBV",             "EpicsSignalRO"),
        ("TempSuffix",               "EpicsSignal(char_waveform)"),
        ("TempSuffix_RBV",           "EpicsSignalRO(char_waveform)"),
    ]:
        pvs.append((hdf_prefix + suffix, kind))

    return pvs


# ---------------------------------------------------------------------------
# get_pv_types() — referenced by pixi 'pvs' task
# ---------------------------------------------------------------------------

def get_pv_types() -> None:
    """Print a table of every EPICS PV the profile connects to, with its type.

    This is the function called by the pixi ``pvs`` task::

        pixi run pvs
        # ipython --profile-dir=. -c 'get_pv_types(); exit()'
    """
    inventory = build_inventory()

    total = 0
    # Count unique PV names (some appear in multiple devices)
    seen: set = set()
    lines = []
    for device_name, pvlist in sorted(inventory.items()):
        for pvname, kind in pvlist:
            unique = pvname not in seen
            seen.add(pvname)
            lines.append((device_name, pvname, kind, unique))
            total += 1

    # Print header
    w_dev  = max(len(r[0]) for r in lines) + 2
    w_pv   = max(len(r[1]) for r in lines) + 2
    w_kind = max(len(r[2]) for r in lines) + 2
    header = f"{'Device':<{w_dev}}{'PV Name':<{w_pv}}{'Type':<{w_kind}}Unique"
    print(header)
    print("-" * len(header))
    for device_name, pvname, kind, unique in lines:
        print(f"{device_name:<{w_dev}}{pvname:<{w_pv}}{kind:<{w_kind}}{'*' if unique else ''}")
    print()
    print(f"Total entries: {total}   Unique PV names: {len(seen)}")


# ---------------------------------------------------------------------------
# Flat PV list helpers for caproto IOC builders
# ---------------------------------------------------------------------------

def all_pvnames() -> List[str]:
    """Return a deduplicated, sorted list of every PV name in the inventory."""
    seen: set = set()
    out: List[str] = []
    for pvlist in build_inventory().values():
        for pvname, _ in pvlist:
            if pvname not in seen:
                seen.add(pvname)
                out.append(pvname)
    return sorted(out)


def pvnames_by_prefix(prefix: str) -> List[str]:
    """Return PV names that start with *prefix* (useful for slicing by IOC)."""
    return [pv for pv in all_pvnames() if pv.startswith(prefix)]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    get_pv_types()
