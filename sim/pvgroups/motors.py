"""
sim/pvgroups/motors.py
----------------------
Caproto PVGroups that simulate EPICS motor records for every EpicsMotor
device instantiated in the IOS profile collection.

Each simulated motor:
  - Accepts a setpoint on ``.VAL``.
  - Immediately marks the move done (``DMOV=1``, ``MOVN=0``) so bluesky
    plan stubs that wait for motion do not hang.
  - Echoes the setpoint back on ``.RBV`` so readback is consistent.
  - Exposes all fields that ophyd's EpicsMotor component subscribes to.

PV names are identical to the real beamline IOC.  Only the CA addressing
is different — the sim IOC binds to 127.0.0.1 and clients set
``EPICS_CA_ADDR_LIST=127.0.0.1 EPICS_CA_AUTO_ADDR_LIST=NO``.
"""

from __future__ import annotations

import time
import asyncio

from caproto.server import PVGroup, pvproperty, run
from caproto import ChannelType


class MotorFields(PVGroup):
    """A minimal but complete motor-record surface for one EpicsMotor.

    The prefix passed to the constructor must be the full PV prefix
    *including* the trailing ``Mtr`` (e.g. ``XF:23ID2-OP{Slt:2-Ax:Y}Mtr``).
    Field suffixes (``.VAL``, ``.RBV`` …) are appended automatically.
    """

    # -- Position setpoint / readback --------------------------------------
    VAL  = pvproperty(name=".VAL",  value=0.0, dtype=float, doc="User setpoint")
    RBV  = pvproperty(name=".RBV",  value=0.0, dtype=float, read_only=True, doc="User readback")
    RRBV = pvproperty(name=".RRBV", value=0.0, dtype=float, read_only=True, doc="Raw readback")
    RVAL = pvproperty(name=".RVAL", value=0,   dtype=int,   read_only=True)
    DVAL = pvproperty(name=".DVAL", value=0.0, dtype=float)
    DIFF = pvproperty(name=".DIFF", value=0.0, dtype=float, read_only=True)

    # -- Motion status -----------------------------------------------------
    DMOV = pvproperty(name=".DMOV", value=1, dtype=int,  read_only=True, doc="Done moving")
    MOVN = pvproperty(name=".MOVN", value=0, dtype=int,  read_only=True, doc="Moving")
    MIP  = pvproperty(name=".MIP",  value=0, dtype=int,  read_only=True)
    MSTA = pvproperty(name=".MSTA", value=0, dtype=int,  read_only=True)
    TDIR = pvproperty(name=".TDIR", value=0, dtype=int,  read_only=True)
    MISS = pvproperty(name=".MISS", value=0, dtype=int,  read_only=True)
    RCNT = pvproperty(name=".RCNT", value=0, dtype=int,  read_only=True)

    # -- Limit switches ---------------------------------------------------
    HLS  = pvproperty(name=".HLS",  value=0, dtype=int, read_only=True)
    LLS  = pvproperty(name=".LLS",  value=0, dtype=int, read_only=True)
    HLM  = pvproperty(name=".HLM",  value=1e6, dtype=float)
    LLM  = pvproperty(name=".LLM",  value=-1e6, dtype=float)
    DHLM = pvproperty(name=".DHLM", value=1e6, dtype=float)
    DLLM = pvproperty(name=".DLLM", value=-1e6, dtype=float)
    LOLO = pvproperty(name=".LOLO", value=-1e6, dtype=float)
    HIHI = pvproperty(name=".HIHI", value=1e6,  dtype=float)
    LOW  = pvproperty(name=".LOW",  value=-1e6, dtype=float)
    HIGH = pvproperty(name=".HIGH", value=1e6,  dtype=float)

    # -- Control / command ------------------------------------------------
    STOP  = pvproperty(name=".STOP",  value=0, dtype=int)
    SET   = pvproperty(name=".SET",   value=0, dtype=int)
    FOFF  = pvproperty(name=".FOFF",  value=0, dtype=int, doc="Offset freeze switch")
    SPMG  = pvproperty(name=".SPMG",  value=3, dtype=int, doc="0=Stop,1=Pause,2=Move,3=Go")
    JOGF  = pvproperty(name=".JOGF",  value=0, dtype=int)
    JOGR  = pvproperty(name=".JOGR",  value=0, dtype=int)
    HOMF  = pvproperty(name=".HOMF",  value=0, dtype=int)
    HOMR  = pvproperty(name=".HOMR",  value=0, dtype=int)
    CNEN  = pvproperty(name=".CNEN",  value=0, dtype=int)
    STUP  = pvproperty(name=".STUP",  value=0, dtype=int)
    ATHM  = pvproperty(name=".ATHM",  value=0, dtype=int)
    TWF   = pvproperty(name=".TWF",   value=0, dtype=int)
    TWR   = pvproperty(name=".TWR",   value=0, dtype=int)
    TWV   = pvproperty(name=".TWV",   value=1.0, dtype=float)

    # -- Engineering / configuration --------------------------------------
    EGU   = pvproperty(name=".EGU",  value="mm", dtype=str,   max_length=16)
    DESC  = pvproperty(name=".DESC", value="Sim motor", dtype=str, max_length=40)
    PREC  = pvproperty(name=".PREC", value=4, dtype=int)
    VELO  = pvproperty(name=".VELO", value=1.0,  dtype=float)
    VMAX  = pvproperty(name=".VMAX", value=10.0, dtype=float)
    ACCL  = pvproperty(name=".ACCL", value=0.5,  dtype=float)
    MRES  = pvproperty(name=".MRES", value=0.001, dtype=float)
    ERES  = pvproperty(name=".ERES", value=0.001, dtype=float)
    RRES  = pvproperty(name=".RRES", value=0.001, dtype=float)
    UREV  = pvproperty(name=".UREV", value=1.0,  dtype=float)
    SBAS  = pvproperty(name=".SBAS", value=0.1,  dtype=float)
    BACC  = pvproperty(name=".BACC", value=0.5,  dtype=float)
    HVEL  = pvproperty(name=".HVEL", value=0.5,  dtype=float)
    RTRY  = pvproperty(name=".RTRY", value=0, dtype=int)
    RDBD  = pvproperty(name=".RDBD", value=0.001, dtype=float)
    SPDB  = pvproperty(name=".SPDB", value=0.001, dtype=float)
    DIR   = pvproperty(name=".DIR",  value=0, dtype=int)
    OFF   = pvproperty(name=".OFF",  value=0.0, dtype=float)
    UEIP  = pvproperty(name=".UEIP", value=0, dtype=int)
    URIP  = pvproperty(name=".URIP", value=0, dtype=int)

    # -- Jog / tweak -------------------------------------------------------
    # These are accessed by some mirror axis code via .PROC suffixes;
    # serving them as plain int PVs is sufficient for connection.

    @VAL.putter
    async def VAL(self, instance, value):
        """On setpoint write: pulse DMOV 1→0→1 so ophyd detects the move."""
        # Signal 'moving': DMOV=0, MOVN=1
        await self.DMOV.write(0)
        await self.MOVN.write(1)
        # Micro-sleep so the DMOV=0 monitor callback reaches ophyd before DMOV=1.
        # This is necessary because EpicsMotor._move_changed() only calls
        # _done_moving() when it sees a 1→0→1 DMOV transition (was_moving).
        await asyncio.sleep(0.05)
        # Update position and signal 'done'
        await self.RBV.write(value)
        await self.RRBV.write(value)
        await self.DMOV.write(1)
        await self.MOVN.write(0)
        return value


# ---------------------------------------------------------------------------
# One PVGroup per motor prefix
# ---------------------------------------------------------------------------
# The caproto server is told the *group prefix* and the group's pvproperty
# names become the suffixes.  So we instantiate one MotorFields per motor.
#
# All instantiation happens in run_iocs.py — this file only defines the class.


# ---------------------------------------------------------------------------
# Convenience: build the list of (prefix, name) pairs run_iocs needs
# ---------------------------------------------------------------------------

MOTOR_PREFIX_MAP: dict[str, str] = {
    # key = ophyd device name, value = full PV prefix (no trailing .)
    "slt2":        "XF:23ID2-OP{{Slt:2-Ax:Y}}Mtr",
    "diag1_y":     "XF:23ID2-BI{{Diag:1-Ax:Y}}Mtr",
    "diag3_y":     "XF:23ID2-BI{{Diag:3-Ax:Y}}Mtr",
    "diag4_y":     "XF:23ID2-BI{{Diag:4-Ax:Y}}Mtr",
    "au_mesh":     "XF:23ID2-BI{{AuMesh:1-Ax:Y}}Mtr",
    "ioxas_x":     "XF:23ID2-BI{{IOXAS:1-Ax:X}}Mtr",
    "vortex_x":    "XF:23ID2-BI{{Vortex:1-Ax:X}}Mtr",
    "appes_y":     "XF:23ID2-ES{{APPES:1-Ax:Y}}Mtr",
    "appes_x":     "XF:23ID2-ES{{APPES:1-Ax:X}}Mtr",
    "appes_z":     "XF:23ID2-ES{{APPES:1-Ax:Z}}Mtr",
    "appes_t":     "XF:23ID2-ES{{APPES:1-Ax:R}}Mtr",
    "dm1_x":       "XF:23ID2-OP{{DM1-Ax:X}}Mtr",
    "dm1_roll":    "XF:23ID2-OP{{DM1-Ax:Roll}}Mtr",
    "dm1_diag":    "XF:23ID2-OP{{DM1:FS-Ax:Y}}Mtr",
    "dm1_slt":     "XF:23ID2-OP{{DM1:HSlt-Ax:X}}Mtr",
    "dm2_us_diag": "XF:23ID2-OP{{DM2:FS-Ax:Y}}Mtr",
    "dm2_ds_diag": "XF:23ID2-OP{{DM2:FSPhDiod-Ax:Y}}Mtr",
    "dm2_ygap":    "XF:23ID2-OP{{DM2:Slt-Ax:YGap}}Mtr",
    "dm2_yctr":    "XF:23ID2-OP{{DM2:Slt-Ax:YCtr}}Mtr",
    "dm2_xgap":    "XF:23ID2-OP{{DM2:Slt-Ax:XGap}}Mtr",
    "dm2_xctr":    "XF:23ID2-OP{{DM2:Slt-Ax:XCtr}}Mtr",
    "kb_roll":     "XF:23ID2-OP{{KB:base-Ax:Theta}}Mtr",
    "kb_yi":       "XF:23ID2-OP{{KB:base-Ax:InB}}Mtr",
    "kb_yo":       "XF:23ID2-OP{{KB:base-Ax:OutB}}Mtr",
    "kb_x":        "XF:23ID2-OP{{KB:base-Ax:X}}Mtr",
    "kb_z":        "XF:23ID2-OP{{KB:base-Ax:Z}}Mtr",
    "kbph_y":      "XF:23ID2-OP{{KB:Pnh-Ax:Y}}Mtr",
    "kbph_x":      "XF:23ID2-OP{{KB:Pnh-Ax:X}}Mtr",
    "kbdiag_y":    "XF:23ID2-OP{{KB:Diag-Ax:Z}}Mtr",
    "kbdiag_rot":  "XF:23ID2-OP{{KB:Diag-Ax:Rot}}Mtr",
    "hkb_pitch":   "XF:23ID2-OP{{KB:MirH-Ax:Pitch}}Mtr",
    "hkb_roll":    "XF:23ID2-OP{{KB:MirH-Ax:Roll}}Mtr",
    "vkb_pitch":   "XF:23ID2-OP{{KB:MirV-Ax:Pitch}}Mtr",
    "bdc_x":       "XF:23ID2-OP{{IRm-Ax:X}}Mtr",
    "bdc_z":       "XF:23ID2-OP{{IRm-Ax:Z}}Mtr",
    "bdc_y":       "XF:23ID2-OP{{IRm-Ax:Y}}Mtr",
    # slt1 (SlitsGapCenter — four axes)
    "slt1_xg":     "XF:23ID2-OP{{Slt:1-Ax:XGap}}Mtr",
    "slt1_xc":     "XF:23ID2-OP{{Slt:1-Ax:XCtr}}Mtr",
    "slt1_yg":     "XF:23ID2-OP{{Slt:1-Ax:YGap}}Mtr",
    "slt1_yc":     "XF:23ID2-OP{{Slt:1-Ax:YCtr}}Mtr",
    # PGM axis motors
    "pgm_pit":     "XF:23ID2-OP{{Mono-Ax:MirP}}Mtr",
    "pgm_x":       "XF:23ID2-OP{{Mono-Ax:MirX}}Mtr",
    "pgm_grt_pit": "XF:23ID2-OP{{Mono-Ax:GrtP}}Mtr",
    "pgm_grt_x":   "XF:23ID2-OP{{Mono-Ax:GrtX}}Mtr",
    # M3A (MotorMirror)
    "m3a_x":       "XF:23ID2-OP{{Mir:3A-Ax:XAvg}}Mtr",
    "m3a_pit":     "XF:23ID2-OP{{Mir:3A-Ax:P}}Mtr",
    "m3a_bdr":     "XF:23ID2-OP{{Mir:3A-Ax:Bdr}}Mtr",
}
