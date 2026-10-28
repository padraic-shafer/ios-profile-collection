"""
sim/pvgroups/scaler_signals.py
-------------------------------
Caproto PVGroups for:
  - DodgyEpicsScaler  (XF:23ID2-ES{Sclr:1})
  - Standalone EpicsSignal / EpicsSignalRO PVs (valves, ring current,
    mirror signals, temps, current amps, sputter, suspender PVs, …)
  - Valve devices (Valve, TwoButtonShutter)

The scaler is the device exercised by the existing acceptance test::

    RE(count([sclr], num=5))

so its behavioural fidelity matters most in Phase 1.

Shutter PVs carry enum strings matching what TwoButtonShutter expects::

    Pos-Sts   : ('Unknown', 'Open', 'Closed', 'Not Closed')
    Cmd:Opn-Cmd / Cmd:Cls-Cmd : ('None', 'Open', 'Close')
    Sts:FailCls-Sts / Sts:FailOpn-Sts : ('OK', 'Fail')
"""

from __future__ import annotations

import asyncio
import numpy as np

from caproto.server import PVGroup, pvproperty, SubGroup
from caproto import ChannelType


# ---------------------------------------------------------------------------
# Scaler
# ---------------------------------------------------------------------------

def _make_scaler_channel_props(n: int):
    """Return a dict of pvproperty objects for one scaler channel."""
    return {
        f"S{n}":  pvproperty(name=f".S{n}",  value=0,   dtype=int, read_only=False),
        f"NM{n}": pvproperty(name=f".NM{n}", value=f"Chan{n}", dtype=str, max_length=28),
        f"PR{n}": pvproperty(name=f".PR{n}", value=0,   dtype=int),
        f"G{n}":  pvproperty(name=f".G{n}",  value=1,   dtype=int),
    }


class ScalerIOC(PVGroup):
    """Simulated SynApps scaler record for DodgyEpicsScaler.

    Prefix: ``XF:23ID2-ES{Sclr:1}``

    When ``.CNT`` is written with 1 the scaler counts for ``.TP`` seconds
    (simulated via asyncio.sleep) then fills channel values with random
    integers and resets ``.CNT`` to 0.
    """

    # -- Control -----------------------------------------------------------
    CNT  = pvproperty(name=".CNT",  value=0, dtype=ChannelType.ENUM,
                      enum_strings=("Done", "Count"), doc="Count trigger")
    CONT = pvproperty(name=".CONT", value=0, dtype=ChannelType.ENUM,
                      enum_strings=("OneShot", "AutoCount"), doc="Auto-count mode")
    DLY  = pvproperty(name=".DLY",  value=0.0, dtype=float)
    DLY1 = pvproperty(name=".DLY1", value=0.0, dtype=float)
    T    = pvproperty(name=".T",    value=0.0, dtype=float, read_only=True, doc="Elapsed time")
    FREQ = pvproperty(name=".FREQ", value=1e7, dtype=float, doc="Clock frequency (Hz)")
    TP   = pvproperty(name=".TP",   value=1.0, dtype=float, doc="Preset time (s)")
    TP1  = pvproperty(name=".TP1",  value=1.0, dtype=float)
    RATE = pvproperty(name=".RATE", value=0,   dtype=int)
    RAT1 = pvproperty(name=".RAT1", value=0,   dtype=int)
    EGU  = pvproperty(name=".EGU",  value="counts", dtype=str, max_length=16)

    # -- 32 channels -------------------------------------------------------
    S1  = pvproperty(name=".S1",  value=0, dtype=int)
    S2  = pvproperty(name=".S2",  value=0, dtype=int)
    S3  = pvproperty(name=".S3",  value=0, dtype=int)
    S4  = pvproperty(name=".S4",  value=0, dtype=int)
    S5  = pvproperty(name=".S5",  value=0, dtype=int)
    S6  = pvproperty(name=".S6",  value=0, dtype=int)
    S7  = pvproperty(name=".S7",  value=0, dtype=int)
    S8  = pvproperty(name=".S8",  value=0, dtype=int)
    S9  = pvproperty(name=".S9",  value=0, dtype=int)
    S10 = pvproperty(name=".S10", value=0, dtype=int)
    S11 = pvproperty(name=".S11", value=0, dtype=int)
    S12 = pvproperty(name=".S12", value=0, dtype=int)
    S13 = pvproperty(name=".S13", value=0, dtype=int)
    S14 = pvproperty(name=".S14", value=0, dtype=int)
    S15 = pvproperty(name=".S15", value=0, dtype=int)
    S16 = pvproperty(name=".S16", value=0, dtype=int)
    S17 = pvproperty(name=".S17", value=0, dtype=int)
    S18 = pvproperty(name=".S18", value=0, dtype=int)
    S19 = pvproperty(name=".S19", value=0, dtype=int)
    S20 = pvproperty(name=".S20", value=0, dtype=int)
    S21 = pvproperty(name=".S21", value=0, dtype=int)
    S22 = pvproperty(name=".S22", value=0, dtype=int)
    S23 = pvproperty(name=".S23", value=0, dtype=int)
    S24 = pvproperty(name=".S24", value=0, dtype=int)
    S25 = pvproperty(name=".S25", value=0, dtype=int)
    S26 = pvproperty(name=".S26", value=0, dtype=int)
    S27 = pvproperty(name=".S27", value=0, dtype=int)
    S28 = pvproperty(name=".S28", value=0, dtype=int)
    S29 = pvproperty(name=".S29", value=0, dtype=int)
    S30 = pvproperty(name=".S30", value=0, dtype=int)
    S31 = pvproperty(name=".S31", value=0, dtype=int)
    S32 = pvproperty(name=".S32", value=0, dtype=int)

    # Channel names
    NM1  = pvproperty(name=".NM1",  value="Time",    dtype=str, max_length=28)
    NM2  = pvproperty(name=".NM2",  value="Chan2",   dtype=str, max_length=28)
    NM3  = pvproperty(name=".NM3",  value="Chan3",   dtype=str, max_length=28)
    NM4  = pvproperty(name=".NM4",  value="Chan4",   dtype=str, max_length=28)
    NM5  = pvproperty(name=".NM5",  value="Chan5",   dtype=str, max_length=28)
    NM6  = pvproperty(name=".NM6",  value="Chan6",   dtype=str, max_length=28)
    NM7  = pvproperty(name=".NM7",  value="Chan7",   dtype=str, max_length=28)
    NM8  = pvproperty(name=".NM8",  value="Chan8",   dtype=str, max_length=28)
    NM9  = pvproperty(name=".NM9",  value="Chan9",   dtype=str, max_length=28)
    NM10 = pvproperty(name=".NM10", value="Chan10",  dtype=str, max_length=28)
    NM11 = pvproperty(name=".NM11", value="Chan11",  dtype=str, max_length=28)
    NM12 = pvproperty(name=".NM12", value="Chan12",  dtype=str, max_length=28)
    NM13 = pvproperty(name=".NM13", value="Chan13",  dtype=str, max_length=28)
    NM14 = pvproperty(name=".NM14", value="Chan14",  dtype=str, max_length=28)
    NM15 = pvproperty(name=".NM15", value="Chan15",  dtype=str, max_length=28)
    NM16 = pvproperty(name=".NM16", value="Chan16",  dtype=str, max_length=28)
    NM17 = pvproperty(name=".NM17", value="Chan17",  dtype=str, max_length=28)
    NM18 = pvproperty(name=".NM18", value="Chan18",  dtype=str, max_length=28)
    NM19 = pvproperty(name=".NM19", value="Chan19",  dtype=str, max_length=28)
    NM20 = pvproperty(name=".NM20", value="Chan20",  dtype=str, max_length=28)
    NM21 = pvproperty(name=".NM21", value="Chan21",  dtype=str, max_length=28)
    NM22 = pvproperty(name=".NM22", value="Chan22",  dtype=str, max_length=28)
    NM23 = pvproperty(name=".NM23", value="Chan23",  dtype=str, max_length=28)
    NM24 = pvproperty(name=".NM24", value="Chan24",  dtype=str, max_length=28)
    NM25 = pvproperty(name=".NM25", value="Chan25",  dtype=str, max_length=28)
    NM26 = pvproperty(name=".NM26", value="Chan26",  dtype=str, max_length=28)
    NM27 = pvproperty(name=".NM27", value="Chan27",  dtype=str, max_length=28)
    NM28 = pvproperty(name=".NM28", value="Chan28",  dtype=str, max_length=28)
    NM29 = pvproperty(name=".NM29", value="Chan29",  dtype=str, max_length=28)
    NM30 = pvproperty(name=".NM30", value="Chan30",  dtype=str, max_length=28)
    NM31 = pvproperty(name=".NM31", value="Chan31",  dtype=str, max_length=28)
    NM32 = pvproperty(name=".NM32", value="Chan32",  dtype=str, max_length=28)

    # Presets / gates
    PR1  = pvproperty(name=".PR1",  value=0, dtype=int)
    PR2  = pvproperty(name=".PR2",  value=0, dtype=int)
    PR3  = pvproperty(name=".PR3",  value=0, dtype=int)
    PR4  = pvproperty(name=".PR4",  value=0, dtype=int)
    PR5  = pvproperty(name=".PR5",  value=0, dtype=int)
    PR6  = pvproperty(name=".PR6",  value=0, dtype=int)
    PR7  = pvproperty(name=".PR7",  value=0, dtype=int)
    PR8  = pvproperty(name=".PR8",  value=0, dtype=int)
    PR9  = pvproperty(name=".PR9",  value=0, dtype=int)
    PR10 = pvproperty(name=".PR10", value=0, dtype=int)
    PR11 = pvproperty(name=".PR11", value=0, dtype=int)
    PR12 = pvproperty(name=".PR12", value=0, dtype=int)
    PR13 = pvproperty(name=".PR13", value=0, dtype=int)
    PR14 = pvproperty(name=".PR14", value=0, dtype=int)
    PR15 = pvproperty(name=".PR15", value=0, dtype=int)
    PR16 = pvproperty(name=".PR16", value=0, dtype=int)
    PR17 = pvproperty(name=".PR17", value=0, dtype=int)
    PR18 = pvproperty(name=".PR18", value=0, dtype=int)
    PR19 = pvproperty(name=".PR19", value=0, dtype=int)
    PR20 = pvproperty(name=".PR20", value=0, dtype=int)
    PR21 = pvproperty(name=".PR21", value=0, dtype=int)
    PR22 = pvproperty(name=".PR22", value=0, dtype=int)
    PR23 = pvproperty(name=".PR23", value=0, dtype=int)
    PR24 = pvproperty(name=".PR24", value=0, dtype=int)
    PR25 = pvproperty(name=".PR25", value=0, dtype=int)
    PR26 = pvproperty(name=".PR26", value=0, dtype=int)
    PR27 = pvproperty(name=".PR27", value=0, dtype=int)
    PR28 = pvproperty(name=".PR28", value=0, dtype=int)
    PR29 = pvproperty(name=".PR29", value=0, dtype=int)
    PR30 = pvproperty(name=".PR30", value=0, dtype=int)
    PR31 = pvproperty(name=".PR31", value=0, dtype=int)
    PR32 = pvproperty(name=".PR32", value=0, dtype=int)

    G1   = pvproperty(name=".G1",   value=1, dtype=int)
    G2   = pvproperty(name=".G2",   value=1, dtype=int)
    G3   = pvproperty(name=".G3",   value=1, dtype=int)
    G4   = pvproperty(name=".G4",   value=1, dtype=int)
    G5   = pvproperty(name=".G5",   value=1, dtype=int)
    G6   = pvproperty(name=".G6",   value=1, dtype=int)
    G7   = pvproperty(name=".G7",   value=1, dtype=int)
    G8   = pvproperty(name=".G8",   value=1, dtype=int)
    G9   = pvproperty(name=".G9",   value=1, dtype=int)
    G10  = pvproperty(name=".G10",  value=1, dtype=int)
    G11  = pvproperty(name=".G11",  value=1, dtype=int)
    G12  = pvproperty(name=".G12",  value=1, dtype=int)
    G13  = pvproperty(name=".G13",  value=1, dtype=int)
    G14  = pvproperty(name=".G14",  value=1, dtype=int)
    G15  = pvproperty(name=".G15",  value=1, dtype=int)
    G16  = pvproperty(name=".G16",  value=1, dtype=int)
    G17  = pvproperty(name=".G17",  value=1, dtype=int)
    G18  = pvproperty(name=".G18",  value=1, dtype=int)
    G19  = pvproperty(name=".G19",  value=1, dtype=int)
    G20  = pvproperty(name=".G20",  value=1, dtype=int)
    G21  = pvproperty(name=".G21",  value=1, dtype=int)
    G22  = pvproperty(name=".G22",  value=1, dtype=int)
    G23  = pvproperty(name=".G23",  value=1, dtype=int)
    G24  = pvproperty(name=".G24",  value=1, dtype=int)
    G25  = pvproperty(name=".G25",  value=1, dtype=int)
    G26  = pvproperty(name=".G26",  value=1, dtype=int)
    G27  = pvproperty(name=".G27",  value=1, dtype=int)
    G28  = pvproperty(name=".G28",  value=1, dtype=int)
    G29  = pvproperty(name=".G29",  value=1, dtype=int)
    G30  = pvproperty(name=".G30",  value=1, dtype=int)
    G31  = pvproperty(name=".G31",  value=1, dtype=int)
    G32  = pvproperty(name=".G32",  value=1, dtype=int)

    # calc5 sub-record used by norm_ch4
    calc5_VAL = pvproperty(name="_calc5.VAL", value=0.0, dtype=float, read_only=True)

    @CNT.putter
    async def CNT(self, instance, value):
        """Simulate a count.

        Caproto sends the CA put-complete acknowledgement immediately after
        the putter returns — the async body runs as a background task.
        EpicsScaler.trigger() fires its 'done' callback on put-complete, so
        ophyd reads channels immediately after.

        We therefore fill channel values BEFORE yielding (no sleep) so the
        data is ready when ophyd reads it.  A background asyncio task handles
        the CNT reset back to 0 after the nominal preset time, which keeps
        the scaler state consistent for back-to-back counts.
        """
        # value=1 means "Count" (enum index 1); 0 = "Done" (reset)
        if int(value) != 1:
            return value

        preset = float(self.TP.value)
        rng = np.random.default_rng()

        # Fill channels immediately with plausible random counts
        channel_pvs = [
            self.S1,  self.S2,  self.S3,  self.S4,  self.S5,  self.S6,
            self.S7,  self.S8,  self.S9,  self.S10, self.S11, self.S12,
            self.S13, self.S14, self.S15, self.S16, self.S17, self.S18,
            self.S19, self.S20, self.S21, self.S22, self.S23, self.S24,
            self.S25, self.S26, self.S27, self.S28, self.S29, self.S30,
            self.S31, self.S32,
        ]
        for i, ch in enumerate(channel_pvs):
            if i == 0:
                await ch.write(int(preset * self.FREQ.value))
            else:
                await ch.write(int(rng.integers(1000, 100_000)))
        await self.T.write(preset)
        await self.calc5_VAL.write(float(rng.integers(1000, 50_000)))

        # Reset CNT→0 ("Done") after preset time (background task)
        async def _reset():
            await asyncio.sleep(max(0.01, preset))
            await self.CNT.write(0)  # "Done"

        asyncio.ensure_future(_reset())
        # Return 1 ("Count") to leave CNT=1 until the background reset fires.
        return 1


# ---------------------------------------------------------------------------
# Standalone signals IOC  (one flat PVGroup)
# ---------------------------------------------------------------------------

class StandaloneSignalsIOC(PVGroup):
    """All standalone EpicsSignal/RO PVs that don't belong to a Device class."""

    # -- Mirror / optics standalone signals (10-optics.py) -----------------
    # Note: mirror axis Mtr_MON / Mtr_POS_SP and MOVE_CMD/STOP_CMD/BUSY_STS are
    # served by MirrorStandaloneIOC and mirror PVGroups in positioners.py.
    yag_centroid     = pvproperty(name="XF:23ID2-BI{{ExitSlt-Cam:1}}Stats1:CentroidX_RBV",value=512.0, read_only=True)

    # -- Valves (11-valves.py) ---------------------------------------------
    valve_diag3      = pvproperty(name="XF:23ID2-VA{{Diag:03-GV:1}}Cmd:Opn-Cmd", value=0)
    valve_mir        = pvproperty(name="XF:23ID2-VA{{Mir:3-GV:1}}Cmd:Opn-Cmd",   value=0)
    valve_slt3       = pvproperty(name="XF:23ID2-VA{{Slt:3-GV:1}}Cmd:Opn-Cmd",   value=0)
    valve_slt1       = pvproperty(name="XF:23ID2-VA{{Slt:1-GV:1}}Cmd:Opn-Cmd",   value=0)
    valve_pmp1       = pvproperty(name="XF:23ID2-VA{{Pmp:Inl:01-GV:1}}Cmd:Opn-Cmd", value=0)
    valve_pmp2       = pvproperty(name="XF:23ID2-VA{{Pmp:Inl:02-GV:1}}Cmd:Opn-Cmd", value=0)
    valve_mono       = pvproperty(name="XF:23ID2-VA{{Mon-GV:1}}Cmd:Opn-Cmd",     value=0)
    valve_diag1      = pvproperty(name="XF:23ID2-VA{{Diag:01-GV:1}}Cmd:Opn-Cmd", value=0)
    valve_diag3_cls  = pvproperty(name="XF:23ID2-VA{{Diag:03-GV:1}}Cmd:Cls-Cmd", value=0)
    valve_mir3_cls   = pvproperty(name="XF:23ID2-VA{{Mir:3-GV:1}}Cmd:Cls-Cmd",   value=0)
    valve_ioxas_open = pvproperty(name="XF:23ID2-VA{{IOXAS-GV:4}}Cmd:Opn-Cmd",   value=0)
    valve_ioxas_cls  = pvproperty(name="XF:23ID2-VA{{IOXAS-GV:4}}Cmd:Cls-Cmd",   value=0)
    valve_appes_open = pvproperty(name="XF:23ID2-VA{{IOXAS-GV:5}}Cmd:Opn-Cmd",   value=0)
    valve_appes_cls  = pvproperty(name="XF:23ID2-VA{{IOXAS-GV:5}}Cmd:Cls-Cmd",   value=0)
    # valve_appes Device fields
    valve_appes_opn  = pvproperty(name="XF:23ID2-VA{{APPES-GV:3}}Cmd:Opn-Cmd",   value=0)
    valve_appes_clsd = pvproperty(name="XF:23ID2-VA{{APPES-GV:3}}Cmd:Cls-Cmd",   value=0)
    valve_appes_sts  = pvproperty(name="XF:23ID2-VA{{APPES-GV:3}}Pos-Sts",       value=0)

    # -- Mirror feedback (11-valves.py / 20-detectors.py) ------------------
    # XF:23ID2-OP{FBck}Sts:FB-Sel is served by FeedbackLoopIOC in positioners.py;
    # do not duplicate it here.

    # -- Ring current (20-detectors.py) ------------------------------------
    ring_curr        = pvproperty(name="XF:23ID-SR{{}}I-I",                       value=400.0, read_only=True)
    # Note: XF:23ID2-ES{Sclr:1}.TP is served by ScalerIOC; omit here to avoid duplicate.

    # -- Current amplifiers (20-detectors.py) ------------------------------
    sample_gain      = pvproperty(name="XF:23ID2-ES{{CurrAmp:3}}Gain:Val-SP",    value="1 nA/V",  dtype=str, max_length=16)
    sample_decade    = pvproperty(name="XF:23ID2-ES{{CurrAmp:3}}Gain:Decade-SP", value="1e-9",    dtype=str, max_length=16)
    aumesh_gain      = pvproperty(name="XF:23ID2-ES{{CurrAmp:2}}Gain:Val-SP",    value="1 nA/V",  dtype=str, max_length=16)
    aumesh_decade    = pvproperty(name="XF:23ID2-ES{{CurrAmp:2}}Gain:Decade-SP", value="1e-9",    dtype=str, max_length=16)
    pd_gain          = pvproperty(name="XF:23ID2-ES{{CurrAmp:1}}Gain:Val-SP",    value="1 nA/V",  dtype=str, max_length=16)
    pd_decade        = pvproperty(name="XF:23ID2-ES{{CurrAmp:1}}Gain:Decade-SP", value="1e-9",    dtype=str, max_length=16)

    # Note: XF:23ID-ID{EPU:1}Val:Table-Sel and XF:23ID-ID{EPU:1-FLT}Val:InpOff1-SP
    # are served by EPU1IOC in positioners.py; omit here.

    # -- SPECS sputter gun (23-devices.py) --------------------------------
    sputter          = pvproperty(name="XF:23ID2-ES{{SPECS-PS1}}Mode:Opr-Sel",    value=0)
    degas            = pvproperty(name="XF:23ID2-ES{{SPECS-PS1}}Cmd:Degas-Cmd",   value=0)

    # Note: XF:23ID-PPS{Sh:FE}Pos-Sts and XF:23ID2-PPS{PSh}Pos-Sts are
    # served by ShutterIOC (fe_shutter, ds_shutter); omit here.

    # -- Temperatures (97-misc.py) ----------------------------------------
    di_supply        = pvproperty(name="XF:23IDA-UT{{DI}}P:Supply-I",            value=20.0, read_only=True)
    di_return        = pvproperty(name="XF:23IDA-UT{{DI}}P:Return-I",            value=19.5, read_only=True)
    tctrl_a          = pvproperty(name="XF:23ID1-OP{{TCtrl:1-Chan:A}}T-I",       value=25.0, read_only=True)
    tctrl_c          = pvproperty(name="XF:23ID1-OP{{TCtrl:1-Chan:C}}T-I",       value=25.0, read_only=True)
    tctrl_b          = pvproperty(name="XF:23ID1-OP{{TCtrl:1-Chan:B}}T-I",       value=25.0, read_only=True)
    tctrl_d          = pvproperty(name="XF:23ID1-OP{{TCtrl:1-Chan:D}}T-I",       value=25.0, read_only=True)
    tctrl_d5         = pvproperty(name="XF:23ID1-OP{{TCtrl:1-Chan:D5}}T-I",      value=25.0, read_only=True)
    mono_mir_t       = pvproperty(name="XF:23ID2-OP{{Mon-Mir}}T-I",              value=25.0, read_only=True)
    mono_grt1_t      = pvproperty(name="XF:23ID2-OP{{Mon-Grt:1}}T-I",           value=25.0, read_only=True)
    mono_grt2_t      = pvproperty(name="XF:23ID2-OP{{Mon-Grt:2}}T-I",           value=25.0, read_only=True)


# ---------------------------------------------------------------------------
# TwoButtonShutter IOC — needs enum strings
# ---------------------------------------------------------------------------

_SHUTTER_POS_ENUMS    = ("Unknown", "Open", "Closed", "Not Closed")
_SHUTTER_CMD_ENUMS    = ("None", "Open", "Close")
_SHUTTER_FAIL_ENUMS   = ("OK", "Fail")


class ShutterIOC(PVGroup):
    """Simulated TwoButtonShutter for fe_shutter, ds_shutter, us_shutter.

    Pos-Sts starts as 'Open' (index 1) so the SuspendBoolHigh suspenders
    installed in 99-settings.py do not trigger (they suspend on high=closed).
    """

    opn_cmd  = pvproperty(name="Cmd:Opn-Cmd", value=0, dtype=ChannelType.ENUM,
                          enum_strings=_SHUTTER_CMD_ENUMS)
    cls_cmd  = pvproperty(name="Cmd:Cls-Cmd", value=0, dtype=ChannelType.ENUM,
                          enum_strings=_SHUTTER_CMD_ENUMS)
    # Pos-Sts: 0=Unknown,1=Open,2=Closed,3=Not Closed — start open (1)
    pos_sts  = pvproperty(name="Pos-Sts", value=1, dtype=ChannelType.ENUM,
                          enum_strings=_SHUTTER_POS_ENUMS, read_only=True)
    fail_cls = pvproperty(name="Sts:FailCls-Sts", value=0, dtype=ChannelType.ENUM,
                          enum_strings=_SHUTTER_FAIL_ENUMS, read_only=True)
    fail_opn = pvproperty(name="Sts:FailOpn-Sts", value=0, dtype=ChannelType.ENUM,
                          enum_strings=_SHUTTER_FAIL_ENUMS, read_only=True)

    @opn_cmd.putter
    async def opn_cmd(self, instance, value):
        await self.pos_sts.write(1)   # 'Open'
        return 0   # reset command

    @cls_cmd.putter
    async def cls_cmd(self, instance, value):
        await self.pos_sts.write(2)   # 'Closed'
        return 0


SHUTTER_PREFIX_MAP = {
    "fe_shutter": "XF:23ID-PPS{{Sh:FE}}",
    "ds_shutter": "XF:23ID2-PPS{{PSh}}",
    "us_shutter": "XF:23ID2-PPS:2{{PSh}}",
}
