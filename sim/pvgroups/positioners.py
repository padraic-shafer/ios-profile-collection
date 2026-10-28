"""
sim/pvgroups/positioners.py
----------------------------
Caproto PVGroups for all PVPositioner / PVPositionerPC devices and the
Vortex MCA detector defined in the IOS profile collection.

EPICS PV naming note
~~~~~~~~~~~~~~~~~~~~
Many EPICS PV prefixes at IOS contain ``{...}`` substrings (ACF notation).
Caproto uses Python's ``str.format()`` on every prefix string, so literal
``{`` / ``}`` must be doubled to ``{{`` / ``}}``.

Several device prefixes are "split" across parent + child groups:
  e.g. parent = "XF:23ID-ID{EPU:1"  (opens brace, never closes it)
       child  = "-Ax:Gap}Pos-I"      (closes brace + PV name)

Caproto formats the parent prefix first, consuming the ``{{EPU:1`` into
``{EPU:1``, and then the child suffix ``-Ax:Gap}`` is invalid because ``}``
has no matching ``{``.  For such devices we use **absolute PV names** in
every ``pvproperty(name=...)`` and pass ``prefix=""`` to the PVGroup.

Devices affected (split brace):  EPU1, EPU2, all Mirrors.
Devices with self-contained brace pairs in prefix:  FeedbackLoop, PGM.
"""

from __future__ import annotations

import asyncio
import numpy as np

from caproto.server import PVGroup, pvproperty
from caproto import ChannelType


# ---------------------------------------------------------------------------
# EPU stop signals (absolute PV names, no prefix)
# ---------------------------------------------------------------------------

class EPUStopIOC(PVGroup):
    """Absolute-PV stop signals used by GapMotor/PhaseMotor FmCpt."""
    epu1_gap_stop   = pvproperty(name="SR:C23-ID:G1A{{EPU:1-Ax:Gap}}-Mtr.STOP",   value=0)
    epu1_phase_stop = pvproperty(name="SR:C23-ID:G1A{{EPU:1-Ax:Phase}}-Mtr.STOP", value=0)
    epu2_gap_stop   = pvproperty(name="SR:C23-ID:G1A{{EPU:2-Ax:Gap}}-Mtr.STOP",   value=0)
    epu2_phase_stop = pvproperty(name="SR:C23-ID:G1A{{EPU:2-Ax:Phase}}-Mtr.STOP", value=0)


# ---------------------------------------------------------------------------
# EPU1 — absolute PV names required (split-brace prefix)
# ---------------------------------------------------------------------------

class EPU1IOC(PVGroup):
    """EPU1 gap/phase/interpolators/table.  Must be instantiated with prefix=''."""

    # Gap axis (PVPositionerPC)
    gap_pos_i  = pvproperty(name="XF:23ID-ID{{EPU:1-Ax:Gap}}Pos-I",    value=0.0, read_only=True)
    gap_pos_sp = pvproperty(name="XF:23ID-ID{{EPU:1-Ax:Gap}}Pos-SP",   value=0.0)

    # Phase axis
    phase_pos_i  = pvproperty(name="XF:23ID-ID{{EPU:1-Ax:Phase}}Pos-I",  value=0.0, read_only=True)
    phase_pos_sp = pvproperty(name="XF:23ID-ID{{EPU:1-Ax:Phase}}Pos-SP", value=0.0)

    # Table selector
    table = pvproperty(name="XF:23ID-ID{{EPU:1}}Val:Table-Sel", value=0)

    # Interpolator flt
    flt_inp        = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Val:Inp1-SP",      value=0.0)
    flt_inp_off    = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Val:InpOff1-SP",   value=0.0)
    flt_inp_enbl   = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Enbl:Inp1-Sel",    value="Enabled",
                                dtype=str, max_length=16)
    flt_inp_pv     = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Val:Inp1-SP.DOL$", value="",
                                dtype=str, max_length=60)
    flt_output     = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Val:Out1-I",       value=0.0,
                                read_only=True)
    flt_out_enbl   = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Enbl:Out1-Sel",    value="Enable",
                                dtype=str, max_length=16, read_only=True)
    flt_out_pv     = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Calc1.OUT$",       value="",
                                dtype=str, max_length=60)
    flt_out_db     = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Val:DBand1-SP",    value=0.0)
    flt_out_drive  = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Val:OutDrv1-I",    value=0.0,
                                read_only=True)
    flt_interp_sts = pvproperty(name="XF:23ID-ID{{EPU:1-FLT}}Sts:Interp1-Sts", value="Interpolating",
                                dtype=str, max_length=20, read_only=True)

    # Interpolator rlt
    rlt_inp        = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Val:Inp1-SP",      value=0.0)
    rlt_inp_off    = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Val:InpOff1-SP",   value=0.0)
    rlt_inp_enbl   = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Enbl:Inp1-Sel",    value="Enabled",
                                dtype=str, max_length=16)
    rlt_inp_pv     = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Val:Inp1-SP.DOL$", value="",
                                dtype=str, max_length=60)
    rlt_output     = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Val:Out1-I",       value=0.0,
                                read_only=True)
    rlt_out_enbl   = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Enbl:Out1-Sel",    value="Enable",
                                dtype=str, max_length=16, read_only=True)
    rlt_out_pv     = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Calc1.OUT$",       value="",
                                dtype=str, max_length=60)
    rlt_out_db     = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Val:DBand1-SP",    value=0.0)
    rlt_out_drive  = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Val:OutDrv1-I",    value=0.0,
                                read_only=True)
    rlt_interp_sts = pvproperty(name="XF:23ID-ID{{EPU:1-RLT}}Sts:Interp1-Sts", value="Interpolating",
                                dtype=str, max_length=20, read_only=True)

    @gap_pos_sp.putter
    async def gap_pos_sp(self, instance, value):
        await self.gap_pos_i.write(value)
        return value

    @phase_pos_sp.putter
    async def phase_pos_sp(self, instance, value):
        await self.phase_pos_i.write(value)
        return value


# ---------------------------------------------------------------------------
# EPU2 — absolute PV names required (split-brace prefix)
# ---------------------------------------------------------------------------

class EPU2IOC(PVGroup):
    """EPU2 gap/phase.  Must be instantiated with prefix=''."""

    gap_pos_i    = pvproperty(name="XF:23ID-ID{{EPU:2-Ax:Gap}}Pos-I",    value=0.0, read_only=True)
    gap_pos_sp   = pvproperty(name="XF:23ID-ID{{EPU:2-Ax:Gap}}Pos-SP",   value=0.0)
    phase_pos_i  = pvproperty(name="XF:23ID-ID{{EPU:2-Ax:Phase}}Pos-I",  value=0.0, read_only=True)
    phase_pos_sp = pvproperty(name="XF:23ID-ID{{EPU:2-Ax:Phase}}Pos-SP", value=0.0)

    @gap_pos_sp.putter
    async def gap_pos_sp(self, instance, value):
        await self.gap_pos_i.write(value)
        return value

    @phase_pos_sp.putter
    async def phase_pos_sp(self, instance, value):
        await self.phase_pos_i.write(value)
        return value


# ---------------------------------------------------------------------------
# Mirror axes — absolute PV names required (split-brace prefix)
# ---------------------------------------------------------------------------
# Mirror prefixes like "XF:23IDA-OP:1{Mir:1" open a brace that is closed
# by the axis suffix "-Ax:Z}".  We use absolute names for all PVs.

def _esc(s: str) -> str:
    """Escape { and } in *s* for caproto's str.format() expansion."""
    return s.replace("{", "{{").replace("}", "}}")


def _make_mirror_ioc(prefix: str, axes=("Z", "Y", "X", "Pit", "Yaw", "Rol")):
    """Dynamically build a PVGroup for one mirror with *prefix* (unescaped real PV prefix)."""
    attrs: dict = {}

    for ax in axes:
        # Build full absolute PV names, then escape for caproto
        mon_pv_real = prefix + "-Ax:" + ax + "}Mtr_MON"
        sp_pv_real  = prefix + "-Ax:" + ax + "}Mtr_POS_SP"
        mon_name = "ax_" + ax.lower() + "_mon"
        sp_name  = "ax_" + ax.lower() + "_sp"
        attrs[mon_name] = pvproperty(name=_esc(mon_pv_real), value=0.0, read_only=True)
        attrs[sp_name]  = pvproperty(name=_esc(sp_pv_real),  value=0.0)

    attrs["move_cmd"] = pvproperty(name=_esc(prefix + "}MOVE_CMD.PROC"), value=0)
    attrs["stop_cmd"] = pvproperty(name=_esc(prefix + "}STOP_CMD.PROC"), value=0)
    attrs["busy_sts"] = pvproperty(name=_esc(prefix + "}BUSY_STS"),      value=0, read_only=True)

    # Add setpoint putters that echo to readbacks
    for ax in axes:
        sp_key  = "ax_" + ax.lower() + "_sp"
        mon_key = "ax_" + ax.lower() + "_mon"

        def _make_putter(mk):
            async def putter(self, instance, value):
                await getattr(self, mk).write(value)
                return value
            return putter

        attrs[sp_key] = attrs[sp_key].putter(_make_putter(mon_key))

    # Move command putter: briefly set busy then clear
    async def _move_putter(self, instance, value):
        if value:
            await self.busy_sts.write(1)
            await asyncio.sleep(0.05)
            await self.busy_sts.write(0)
        return 0

    attrs["move_cmd"] = attrs["move_cmd"].putter(_move_putter)

    tag = prefix.replace("{", "").replace("}", "").split(":")[-1]
    return type("Mirror_" + tag, (PVGroup,), attrs)


# Build mirror PVGroups at module load — these are referenced by run_iocs.py
_MIRROR_DEFS = {
    "m1a":  ("XF:23IDA-OP:1{Mir:1",  ("Z", "Y", "X", "Pit", "Yaw", "Rol")),
    "m1b1": ("XF:23IDA-OP:2{Mir:1A", ("Z", "Y", "X", "Pit", "Yaw", "Rol")),
    "m1b2": ("XF:23IDA-OP:2{Mir:1B", ("Z", "Y", "X", "Pit", "Yaw", "Rol")),
    "m3b":  ("XF:23ID2-OP{Mir:3B",   ("Z", "Y", "X", "Pit", "Yaw", "Rol")),
}

M1A_IOC  = _make_mirror_ioc("XF:23IDA-OP:1{Mir:1")
M1B1_IOC = _make_mirror_ioc("XF:23IDA-OP:2{Mir:1A")
M1B2_IOC = _make_mirror_ioc("XF:23IDA-OP:2{Mir:1B")
M3B_IOC  = _make_mirror_ioc("XF:23ID2-OP{Mir:3B")

# Also serve the standalone m3b_pitch/m1b1_cp mirror positional signals
# that 10-optics.py creates outside the Device classes.
class MirrorStandaloneIOC(PVGroup):
    """Standalone mirror PVs not served by the axis PVGroups.

    The Mtr_MON / Mtr_POS_SP for standard axes (Z/Y/X/Pit/Yaw/Rol) are
    served by M1A_IOC / M1B1_IOC / etc.  Only truly additional PVs go here:
      - FPit (fine pitch) axis — not in the standard 6-axis set
      - Jog TWV/TWN/TWP (not served by MirrorAxisIOC)
      - m3b_pitch standalone signal (same PV as m3b Mirror axis)
        -> actually served by M3B_IOC, so omitted here.
    """
    # Fine pitch axis on m1b1 — not in the standard axis set
    m1b1_fp       = pvproperty(name=_esc("XF:23IDA-OP:2{Mir:1A-Ax:FPit}Mtr_POS_SP"), value=0.0)
    m1b1_fp_rb    = pvproperty(name=_esc("XF:23IDA-OP:2{Mir:1A-Ax:FPit}Mtr_MON"),    value=0.0, read_only=True)
    # Jog/tweak step size (not served by mirror axis PVGroup)
    m1b1_cp_jog_sp= pvproperty(name=_esc("XF:23IDA-OP:2{Mir:1A-Ax:Pit}Mtr_TWV_SP"),       value=0.1)
    m1b1_cp_jog_ng= pvproperty(name=_esc("XF:23IDA-OP:2{Mir:1A-Ax:Pit}Mtr_TWN_CMD.PROC"), value=0)
    m1b1_cp_jog_ps= pvproperty(name=_esc("XF:23IDA-OP:2{Mir:1A-Ax:Pit}Mtr_TWP_CMD.PROC"), value=0)


# ---------------------------------------------------------------------------
# FeedbackLoop (prefix is self-contained: XF:23ID2-OP{FBck})
# ---------------------------------------------------------------------------

class FeedbackLoopIOC(PVGroup):
    """FeedbackLoop for M1B1 mirror: XF:23ID2-OP{{FBck}}"""
    enable    = pvproperty(name="Sts:FB-Sel",  value=0)
    setpoint  = pvproperty(name="PID-SP",      value=512.0)
    req_val   = pvproperty(name="PID.VAL",     value=512.0, read_only=True)
    act_val   = pvproperty(name="PID.CVAL",    value=512.0, read_only=True)
    out_val   = pvproperty(name="PID.OVAL",    value=0.0,   read_only=True)
    error     = pvproperty(name="PID.Err",     value=0.0,   read_only=True)
    high_lim  = pvproperty(name="PID.DRVH",   value=1024.0)
    low_lim   = pvproperty(name="PID.DRVL",   value=0.0)
    delta_t   = pvproperty(name="PID.DT",     value=1.0,   read_only=True)
    min_dt    = pvproperty(name="PID.MDT",    value=0.1)
    scan_mode = pvproperty(name="PID.SCAN",   value=0)
    deadband  = pvproperty(name="Val:Sbl-SP", value=5.0)

    @setpoint.putter
    async def setpoint(self, instance, value):
        await self.req_val.write(value)
        await self.act_val.write(value)
        return value


# ---------------------------------------------------------------------------
# PGM energy + MonoFly (prefix: XF:23ID2-OP{Mono — self-contained brace)
# ---------------------------------------------------------------------------

class PGMEnergyIOC(PVGroup):
    """PGMEnergy PVPositionerPC + MonoFly.  Must be instantiated with prefix=''."""
    enrgy_i       = pvproperty(name="XF:23ID2-OP{{Mono}}Enrgy-I",              value=400.0, read_only=True)
    enrgy_sp      = pvproperty(name="XF:23ID2-OP{{Mono}}Enrgy-SP",             value=400.0)
    stop_cmd      = pvproperty(name="XF:23ID2-OP{{Mono}}Cmd:Stop-Cmd",          value=0)
    fly_start_sp  = pvproperty(name="XF:23ID2-OP{{Mono}}Enrgy:Start-SP",       value=250.0)
    fly_stop_sp   = pvproperty(name="XF:23ID2-OP{{Mono}}Enrgy:Stop-SP",        value=800.0)
    fly_velo      = pvproperty(name="XF:23ID2-OP{{Mono}}Enrgy:FlyVelo-SP",     value=1.0)
    fly_start_cmd = pvproperty(name="XF:23ID2-OP{{Mono}}Cmd:FlyStart-Cmd.PROC",value=0)
    fly_stop_cmd  = pvproperty(name="XF:23ID2-OP{{Mono}}Cmd:Stop-Cmd.PROC",    value=0)
    scan_sts      = pvproperty(name="XF:23ID2-OP{{Mono}}Sts:Scan-Sts",         value="Idle", dtype=str,
                               max_length=20, read_only=True)
    move_sts      = pvproperty(name="XF:23ID2-OP{{Mono}}Sts:Move-Sts",         value="Done", dtype=str,
                               max_length=20, read_only=True)

    @enrgy_sp.putter
    async def enrgy_sp(self, instance, value):
        await self.enrgy_i.write(value)
        return value


# ---------------------------------------------------------------------------
# Vortex MCA  (EpicsMCA mca1 + EpicsDXP dxp1:)
# ---------------------------------------------------------------------------

_MCA_N_BINS = 2048
_N_ROIS = 5


class VortexIOC(PVGroup):
    """Simulated Vortex MCA at XF:23ID2-ES{{Vortex}}.

    EpicsMCA record surface (mca1 suffix) + EpicsDXP (dxp1:).
    On erase_start the IOC waits for the preset live time then emits a
    Gaussian spectrum.
    """

    # EpicsMCA top-level fields
    spectrum     = pvproperty(name="mca1",       value=[0]*_MCA_N_BINS, dtype=int,
                              read_only=True, max_length=_MCA_N_BINS)
    erase        = pvproperty(name="mca1.ERAS",  value=0, dtype=int)
    start        = pvproperty(name="mca1.STRT",  value=0, dtype=int)
    erase_start  = pvproperty(name="mca1.ERST",  value=0, dtype=int)
    acquiring    = pvproperty(name="mca1.ACQG",  value=0, dtype=int, read_only=True)
    prtm         = pvproperty(name="mca1.PRTM",  value=1.0, dtype=float)
    pltm         = pvproperty(name="mca1.PLTM",  value=1.0, dtype=float)
    ertm         = pvproperty(name="mca1.ERTM",  value=0.0, dtype=float, read_only=True)
    eltm         = pvproperty(name="mca1.ELTM",  value=0.0, dtype=float, read_only=True)
    dtim         = pvproperty(name="mca1.DTIM",  value=0.0, dtype=float, read_only=True)
    idtim        = pvproperty(name="mca1.IDTIM", value=0.0, dtype=float, read_only=True)
    nuse         = pvproperty(name="mca1.NUSE",  value=_MCA_N_BINS, dtype=int)

    # ROIs 0-4
    r0    = pvproperty(name="mca1.R0",    value=0, dtype=int, read_only=True)
    r0lo  = pvproperty(name="mca1.R0LO",  value=0,   dtype=int)
    r0hi  = pvproperty(name="mca1.R0HI",  value=100, dtype=int)
    r0nm  = pvproperty(name="mca1.R0NM",  value="ROI0", dtype=str, max_length=16)
    r0bg  = pvproperty(name="mca1.R0BG",  value=0, dtype=int, read_only=True)

    r1    = pvproperty(name="mca1.R1",    value=0, dtype=int, read_only=True)
    r1lo  = pvproperty(name="mca1.R1LO",  value=200, dtype=int)
    r1hi  = pvproperty(name="mca1.R1HI",  value=400, dtype=int)
    r1nm  = pvproperty(name="mca1.R1NM",  value="ROI1", dtype=str, max_length=16)
    r1bg  = pvproperty(name="mca1.R1BG",  value=0, dtype=int, read_only=True)

    r2    = pvproperty(name="mca1.R2",    value=0, dtype=int, read_only=True)
    r2lo  = pvproperty(name="mca1.R2LO",  value=500, dtype=int)
    r2hi  = pvproperty(name="mca1.R2HI",  value=700, dtype=int)
    r2nm  = pvproperty(name="mca1.R2NM",  value="ROI2", dtype=str, max_length=16)
    r2bg  = pvproperty(name="mca1.R2BG",  value=0, dtype=int, read_only=True)

    r3    = pvproperty(name="mca1.R3",    value=0, dtype=int, read_only=True)
    r3lo  = pvproperty(name="mca1.R3LO",  value=800,  dtype=int)
    r3hi  = pvproperty(name="mca1.R3HI",  value=1000, dtype=int)
    r3nm  = pvproperty(name="mca1.R3NM",  value="ROI3", dtype=str, max_length=16)
    r3bg  = pvproperty(name="mca1.R3BG",  value=0, dtype=int, read_only=True)

    r4    = pvproperty(name="mca1.R4",    value=0, dtype=int, read_only=True)
    r4lo  = pvproperty(name="mca1.R4LO",  value=1200, dtype=int)
    r4hi  = pvproperty(name="mca1.R4HI",  value=1600, dtype=int)
    r4nm  = pvproperty(name="mca1.R4NM",  value="ROI4", dtype=str, max_length=16)
    r4bg  = pvproperty(name="mca1.R4BG",  value=0, dtype=int, read_only=True)

    # EpicsDXP fields
    peaking_time  = pvproperty(name="dxp1:PeakingTime",       value=1.0)
    energy_thresh = pvproperty(name="dxp1:EnergyThreshold",   value=0.5)
    trig_thresh   = pvproperty(name="dxp1:TriggerThreshold",  value=0.2)
    base_thresh   = pvproperty(name="dxp1:BaselineThreshold", value=0.1)
    max_width     = pvproperty(name="dxp1:MaxWidth",          value=1.0)

    def _gaussian_spectrum(self) -> list:
        rng = np.random.default_rng()
        x = np.arange(_MCA_N_BINS, dtype=float)
        center = rng.uniform(400, 1600)
        sigma = rng.uniform(20, 80)
        amplitude = rng.uniform(5000, 50000)
        spectrum = amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2)
        spectrum += rng.poisson(10, _MCA_N_BINS).astype(float)
        return spectrum.astype(int).tolist()

    @erase_start.putter
    async def erase_start(self, instance, value):
        if value != 1:
            return value
        await self.acquiring.write(1)
        await self.spectrum.write([0] * _MCA_N_BINS)
        preset = float(self.pltm.value)
        await asyncio.sleep(max(0.0, preset))
        spec = self._gaussian_spectrum()
        await self.spectrum.write(spec)
        await self.ertm.write(preset)
        await self.eltm.write(preset)
        roi_defs = [
            (self.r0lo, self.r0hi, self.r0),
            (self.r1lo, self.r1hi, self.r1),
            (self.r2lo, self.r2hi, self.r2),
            (self.r3lo, self.r3hi, self.r3),
            (self.r4lo, self.r4hi, self.r4),
        ]
        for lo_pv, hi_pv, cnt_pv in roi_defs:
            lo = int(lo_pv.value)
            hi = int(hi_pv.value)
            cnt = int(sum(spec[max(0, lo):min(_MCA_N_BINS, hi)]))
            await cnt_pv.write(cnt)
        await self.acquiring.write(0)
        return 0
