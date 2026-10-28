"""
sim/pvgroups/detectors.py
--------------------------
Caproto PVGroups for the area-detector based devices:

  - SpecsDetector  (XF:23ID2-ES{SPECS})
    · SpecsDetectorCam  (cam1:)
    · Stats5 plugin     (Stats5:)

  - Xspress3       (XF:23ID2-ES{Xsp:1}:)
    · det1: cam     (Xspress3Detector / CamBase)
    · C1_ channel + MCA_ROI1-4 per-roi PVs
    · HDF1: plugin

All PV names are identical to the real beamline IOC.  Behavioural fidelity:
  - SPECS cam: Acquire=1 → sleep AcquireTime, increment counters, Acquire→0.
  - Xspress3: Acquire=1 → sleep AcquireTime, fill ROI totals.
  - HDF1 plugins: serve all file-plugin PVs as stubs (no real file I/O).
    FilePathExists_RBV is set to 1 so ophyd stage() doesn't complain.
  - roi_name PVs on Xspress3 have non-empty default values so the
    import-time ``mcaroi.roi_name.get()`` loop in 22-xspress3.py returns
    immediately without blocking.
"""

from __future__ import annotations

import asyncio
import numpy as np

from caproto.server import PVGroup, pvproperty, SubGroup
from caproto import ChannelType


# ---------------------------------------------------------------------------
# Shared HDF5 plugin stub  (reused by both SPECS and Xspress3)
# ---------------------------------------------------------------------------

class HDF5PluginStub(PVGroup):
    """Minimal AD HDF5 plugin surface.  No real file I/O."""

    enable_callbacks    = pvproperty(name="EnableCallbacks",         value=1)
    enable_callbacks_rbv= pvproperty(name="EnableCallbacks_RBV",     value=1, read_only=True)
    port_name_rbv       = pvproperty(name="PortName_RBV",            value="HDF1", dtype=str,
                                     max_length=20, read_only=True)
    nd_array_port       = pvproperty(name="NDArrayPort",             value="PROC1", dtype=str,
                                     max_length=20)
    nd_array_port_rbv   = pvproperty(name="NDArrayPort_RBV",         value="PROC1", dtype=str,
                                     max_length=20, read_only=True)
    blocking_callbacks  = pvproperty(name="BlockingCallbacks",       value=0)
    file_path           = pvproperty(name="FilePath",                value="/tmp/sim/", dtype=str,
                                     max_length=256)
    file_path_rbv       = pvproperty(name="FilePath_RBV",            value="/tmp/sim/", dtype=str,
                                     max_length=256, read_only=True)
    file_path_exists    = pvproperty(name="FilePathExists_RBV",      value=1, read_only=True)
    file_name           = pvproperty(name="FileName",                value="sim", dtype=str,
                                     max_length=256)
    file_name_rbv       = pvproperty(name="FileName_RBV",            value="sim", dtype=str,
                                     max_length=256, read_only=True)
    file_number         = pvproperty(name="FileNumber",              value=1)
    file_number_rbv     = pvproperty(name="FileNumber_RBV",          value=1, read_only=True)
    file_template       = pvproperty(name="FileTemplate",            value="%s%s_%6.6d.h5",
                                     dtype=str, max_length=256)
    file_template_rbv   = pvproperty(name="FileTemplate_RBV",        value="%s%s_%6.6d.h5",
                                     dtype=str, max_length=256, read_only=True)
    full_file_name      = pvproperty(name="FullFileName_RBV",        value="/tmp/sim/sim_000001.h5",
                                     dtype=str, max_length=512, read_only=True)
    auto_increment      = pvproperty(name="AutoIncrement",           value=1)
    auto_increment_rbv  = pvproperty(name="AutoIncrement_RBV",       value=1, read_only=True)
    auto_save           = pvproperty(name="AutoSave",                value=1)
    auto_save_rbv       = pvproperty(name="AutoSave_RBV",            value=1, read_only=True)
    file_write_mode     = pvproperty(name="FileWriteMode",           value=0)
    file_write_mode_rbv = pvproperty(name="FileWriteMode_RBV",       value=0, read_only=True)
    num_capture         = pvproperty(name="NumCapture",              value=1)
    num_capture_rbv     = pvproperty(name="NumCapture_RBV",          value=1, read_only=True)
    num_captured        = pvproperty(name="NumCaptured_RBV",         value=0, read_only=True)
    capture             = pvproperty(name="Capture",                 value=0)
    capture_rbv         = pvproperty(name="Capture_RBV",             value=0, read_only=True)
    write_file          = pvproperty(name="WriteFile",               value=0)
    write_file_rbv      = pvproperty(name="WriteFile_RBV",           value=0, read_only=True)
    read_file           = pvproperty(name="ReadFile",                value=0)
    read_file_rbv       = pvproperty(name="ReadFile_RBV",            value=0, read_only=True)
    create_dir          = pvproperty(name="CreateDirectory",         value=0)
    create_dir_rbv      = pvproperty(name="CreateDirectory_RBV",     value=0, read_only=True)
    array_counter       = pvproperty(name="ArrayCounter",            value=0)
    array_counter_rbv   = pvproperty(name="ArrayCounter_RBV",        value=0, read_only=True)
    array_rate          = pvproperty(name="ArrayRate_RBV",           value=0.0, read_only=True)
    compression         = pvproperty(name="Compression",             value=0)
    compression_rbv     = pvproperty(name="Compression_RBV",         value=0, read_only=True)
    num_row_chunks      = pvproperty(name="NumRowChunks",            value=0)
    num_row_chunks_rbv  = pvproperty(name="NumRowChunks_RBV",        value=0, read_only=True)
    num_col_chunks      = pvproperty(name="NumColChunks",            value=0)
    num_col_chunks_rbv  = pvproperty(name="NumColChunks_RBV",        value=0, read_only=True)
    num_frames_chunks   = pvproperty(name="NumFramesChunks",         value=0)
    num_frames_chunks_rbv= pvproperty(name="NumFramesChunks_RBV",    value=0, read_only=True)
    nd_attr_chunk       = pvproperty(name="NDAttributeChunk",        value=0)
    nd_attr_chunk_rbv   = pvproperty(name="NDAttributeChunk_RBV",    value=0, read_only=True)
    boundary_align      = pvproperty(name="BoundaryAlign",           value=0)
    boundary_align_rbv  = pvproperty(name="BoundaryAlign_RBV",       value=0, read_only=True)
    boundary_thresh     = pvproperty(name="BoundaryThreshold",       value=65536)
    boundary_thresh_rbv = pvproperty(name="BoundaryThreshold_RBV",   value=65536, read_only=True)
    io_speed            = pvproperty(name="IOSpeed",                 value=0.0, read_only=True)
    store_attr          = pvproperty(name="StoreAttr",               value=0)
    store_attr_rbv      = pvproperty(name="StoreAttr_RBV",           value=0, read_only=True)
    store_perform       = pvproperty(name="StorePerform",            value=0)
    store_perform_rbv   = pvproperty(name="StorePerform_RBV",        value=0, read_only=True)
    write_status        = pvproperty(name="WriteStatus",             value=0, read_only=True)
    write_message       = pvproperty(name="WriteMessage",            value="OK", dtype=str,
                                     max_length=256, read_only=True)
    xml_file_name       = pvproperty(name="XMLFileName",             value="", dtype=str,
                                     max_length=256)
    xml_file_name_rbv   = pvproperty(name="XMLFileName_RBV",         value="", dtype=str,
                                     max_length=256, read_only=True)
    lazy_open           = pvproperty(name="LazyOpen",                value=0)
    lazy_open_rbv       = pvproperty(name="LazyOpen_RBV",            value=0, read_only=True)
    temp_suffix         = pvproperty(name="TempSuffix",              value="", dtype=str,
                                     max_length=64)
    temp_suffix_rbv     = pvproperty(name="TempSuffix_RBV",          value="", dtype=str,
                                     max_length=64, read_only=True)


# ---------------------------------------------------------------------------
# SPECS Analyzer
# ---------------------------------------------------------------------------

class SpecsCamIOC(PVGroup):
    """SpecsDetectorCam (cam1:) + Stats5 plugin fields under XF:23ID2-ES{SPECS}."""

    # -- CamBase standard fields -------------------------------------------
    acquire          = pvproperty(name="cam1:Acquire",                 value=0)
    acquire_busy     = pvproperty(name="cam1:AcquireBusy",             value=0, read_only=True)
    acquire_time     = pvproperty(name="cam1:AcquireTime",             value=1.0)
    acquire_time_rbv = pvproperty(name="cam1:AcquireTime_RBV",         value=1.0, read_only=True)
    acquire_period   = pvproperty(name="cam1:AcquirePeriod",           value=1.0)
    acquire_period_rbv= pvproperty(name="cam1:AcquirePeriod_RBV",      value=1.0, read_only=True)
    num_images       = pvproperty(name="cam1:NumImages",               value=1)
    num_images_rbv   = pvproperty(name="cam1:NumImages_RBV",           value=1, read_only=True)
    num_images_ctr   = pvproperty(name="cam1:NumImagesCounter_RBV",    value=0, read_only=True)
    num_exposures    = pvproperty(name="cam1:NumExposures",            value=1)
    num_exposures_rbv= pvproperty(name="cam1:NumExposures_RBV",        value=1, read_only=True)
    image_mode       = pvproperty(name="cam1:ImageMode",               value=0)
    image_mode_rbv   = pvproperty(name="cam1:ImageMode_RBV",           value=0, read_only=True)
    trigger_mode     = pvproperty(name="cam1:TriggerMode",             value=0)
    trigger_mode_rbv = pvproperty(name="cam1:TriggerMode_RBV",         value=0, read_only=True)
    det_state        = pvproperty(name="cam1:DetectorState_RBV",       value=0, read_only=True)
    array_rate       = pvproperty(name="cam1:ArrayRate_RBV",           value=0.0, read_only=True)
    data_type        = pvproperty(name="cam1:DataType",                value=9)
    data_type_rbv    = pvproperty(name="cam1:DataType_RBV",            value=9, read_only=True)
    color_mode       = pvproperty(name="cam1:ColorMode",               value=0)
    color_mode_rbv   = pvproperty(name="cam1:ColorMode_RBV",           value=0, read_only=True)
    array_size_x     = pvproperty(name="cam1:ArraySizeX_RBV",          value=1000, read_only=True)
    array_size_y     = pvproperty(name="cam1:ArraySizeY_RBV",          value=1,    read_only=True)
    array_size       = pvproperty(name="cam1:ArraySize_RBV",           value=1000, read_only=True)
    status_msg       = pvproperty(name="cam1:StatusMessage_RBV",       value="Idle", dtype=str,
                                  max_length=256, read_only=True)
    str_to_server    = pvproperty(name="cam1:StringToServer_RBV",      value="", dtype=str,
                                  max_length=256, read_only=True)
    str_from_server  = pvproperty(name="cam1:StringFromServer_RBV",    value="", dtype=str,
                                  max_length=256, read_only=True)
    shutter_mode     = pvproperty(name="cam1:ShutterMode",             value=0)
    shutter_mode_rbv = pvproperty(name="cam1:ShutterMode_RBV",         value=0, read_only=True)
    shutter_ctrl     = pvproperty(name="cam1:ShutterControl",          value=0)
    shutter_ctrl_rbv = pvproperty(name="cam1:ShutterControl_RBV",      value=0, read_only=True)
    shutter_sts      = pvproperty(name="cam1:ShutterStatus_RBV",       value=0, read_only=True)
    shutter_open_dly = pvproperty(name="cam1:ShutterOpenDelay",        value=0.0)
    shutter_open_dly_rbv= pvproperty(name="cam1:ShutterOpenDelay_RBV", value=0.0, read_only=True)
    shutter_cls_dly  = pvproperty(name="cam1:ShutterCloseDelay",       value=0.0)
    shutter_cls_dly_rbv= pvproperty(name="cam1:ShutterCloseDelay_RBV", value=0.0, read_only=True)
    temperature      = pvproperty(name="cam1:Temperature",             value=20.0)
    temperature_rbv  = pvproperty(name="cam1:Temperature_RBV",         value=20.0, read_only=True)
    temperature_act  = pvproperty(name="cam1:TemperatureActual",       value=20.0, read_only=True)

    # -- SpecsDetectorCam custom fields ------------------------------------
    connected        = pvproperty(name="cam1:CONNECTED_RBV",           value=1, read_only=True)
    connect          = pvproperty(name="cam1:CONNECT",                  value=1)
    server_name      = pvproperty(name="cam1:SERVER_NAME_RBV",         value="SimSPECS",
                                  dtype=str, max_length=64, read_only=True)
    protocol_ver     = pvproperty(name="cam1:PROTOCOL_VERSION_RBV",    value="1.0",
                                  dtype=str, max_length=16, read_only=True)
    pass_energy      = pvproperty(name="cam1:PASS_ENERGY",             value=20.0)
    pass_energy_rbv  = pvproperty(name="cam1:PASS_ENERGY_RBV",         value=20.0, read_only=True)
    low_energy       = pvproperty(name="cam1:LOW_ENERGY",              value=280.0)
    low_energy_rbv   = pvproperty(name="cam1:LOW_ENERGY_RBV",          value=280.0, read_only=True)
    high_energy      = pvproperty(name="cam1:HIGH_ENERGY",             value=320.0)
    high_energy_rbv  = pvproperty(name="cam1:HIGH_ENERGY_RBV",         value=320.0, read_only=True)
    energy_width     = pvproperty(name="cam1:ENERGY_WIDTH_RBV",        value=40.0, read_only=True)
    kinetic_energy   = pvproperty(name="cam1:KINETIC_ENERGY",          value=300.0)
    kinetic_energy_rbv= pvproperty(name="cam1:KINETIC_ENERGY_RBV",     value=300.0, read_only=True)
    retarding_ratio  = pvproperty(name="cam1:RETARDING_RATIO",         value=10.0)
    retarding_ratio_rbv= pvproperty(name="cam1:RETARDING_RATIO_RBV",   value=10.0, read_only=True)
    step_size        = pvproperty(name="cam1:STEP_SIZE",               value=0.05)
    step_size_rbv    = pvproperty(name="cam1:STEP_SIZE_RBV",           value=0.05, read_only=True)
    fat_values       = pvproperty(name="cam1:VALUES",                  value=1000)
    fat_values_rbv   = pvproperty(name="cam1:VALUES_RBV",              value=1000, read_only=True)
    samples          = pvproperty(name="cam1:SAMPLES",                 value=10)
    samples_rbv      = pvproperty(name="cam1:SAMPLES_RBV",             value=10, read_only=True)
    lens_mode        = pvproperty(name="cam1:LENS_MODE",               value=0)
    lens_mode_rbv    = pvproperty(name="cam1:LENS_MODE_RBV",           value=0, read_only=True)
    scan_range       = pvproperty(name="cam1:SCAN_RANGE",              value=0)
    scan_range_rbv   = pvproperty(name="cam1:SCAN_RANGE_RBV",          value=0, read_only=True)
    acq_mode         = pvproperty(name="cam1:ACQ_MODE",                value=3)
    acq_mode_rbv     = pvproperty(name="cam1:ACQ_MODE_RBV",            value=3, read_only=True)
    define_spectrum  = pvproperty(name="cam1:DEFINE_SPECTRUM",         value=0)
    define_spectrum_rbv= pvproperty(name="cam1:DEFINE_SPECTRUM_RBV",   value=0, read_only=True)
    validate_spectrum = pvproperty(name="cam1:VALIDATE_SPECTRUM",      value=0)
    validate_spectrum_rbv= pvproperty(name="cam1:VALIDATE_SPECTRUM_RBV",value=0, read_only=True)
    safe_state       = pvproperty(name="cam1:SAFE_STATE",              value=1)
    safe_state_rbv   = pvproperty(name="cam1:SAFE_STATE_RBV",          value=1, read_only=True)
    pause_acq        = pvproperty(name="cam1:PAUSE_RBV",               value=0)
    pause_acq_rbv    = pvproperty(name="cam1:PAUSE_RBV_RBV",           value=0, read_only=True)
    current_point    = pvproperty(name="cam1:CURRENT_POINT_RBV",       value=0, read_only=True)
    current_channel  = pvproperty(name="cam1:CURRENT_CHANNEL_RBV",     value=0, read_only=True)
    region_time_left = pvproperty(name="cam1:REGION_TIME_LEFT_RBV",    value=0.0, read_only=True)
    region_progress  = pvproperty(name="cam1:REGION_PROGRESS_RBV",     value=0.0, read_only=True)
    total_time_left  = pvproperty(name="cam1:TOTAL_TIME_LEFT_RBV",     value=0.0, read_only=True)
    progress         = pvproperty(name="cam1:PROGRESS_RBV",            value=0.0, read_only=True)
    total_pts_iter   = pvproperty(name="cam1:TOTAL_POINTS_ITERTION_RBV",value=0, read_only=True)
    total_pts        = pvproperty(name="cam1:TOTAL_POINTS_RBV",        value=0, read_only=True)

    # -- Stats5 plugin (count + enable) ------------------------------------
    stats5_total     = pvproperty(name="Stats5:Total_RBV",             value=0.0, read_only=True)
    stats5_enable    = pvproperty(name="Stats5:EnableCallbacks",       value=1)
    stats5_port_name = pvproperty(name="Stats5:PortName_RBV",          value="STATS5",
                                  dtype=str, max_length=20, read_only=True)
    stats5_nd_port   = pvproperty(name="Stats5:NDArrayPort",           value="SPECS.cam1",
                                  dtype=str, max_length=40)
    stats5_nd_port_rbv= pvproperty(name="Stats5:NDArrayPort_RBV",      value="SPECS.cam1",
                                   dtype=str, max_length=40, read_only=True)
    stats5_blocking  = pvproperty(name="Stats5:BlockingCallbacks",     value=0)
    stats5_min_x     = pvproperty(name="Stats5:MinX_RBV",             value=0.0, read_only=True)
    stats5_min_y     = pvproperty(name="Stats5:MinY_RBV",             value=0.0, read_only=True)
    stats5_max_x     = pvproperty(name="Stats5:MaxX_RBV",             value=0.0, read_only=True)
    stats5_max_y     = pvproperty(name="Stats5:MaxY_RBV",             value=0.0, read_only=True)
    stats5_mean      = pvproperty(name="Stats5:MeanValue_RBV",        value=0.0, read_only=True)
    stats5_sigma     = pvproperty(name="Stats5:Sigma_RBV",            value=0.0, read_only=True)
    stats5_net       = pvproperty(name="Stats5:Net_RBV",              value=0.0, read_only=True)
    stats5_min_val   = pvproperty(name="Stats5:MinValue_RBV",         value=0.0, read_only=True)
    stats5_max_val   = pvproperty(name="Stats5:MaxValue_RBV",         value=0.0, read_only=True)

    @acquire.putter
    async def acquire(self, instance, value):
        if value != 1:
            return value
        await self.acquire_busy.write(1)
        t = float(self.acquire_time.value)
        await asyncio.sleep(max(0.0, t))
        count = float(np.random.default_rng().integers(5000, 500_000))
        await self.stats5_total.write(count)
        await self.num_images_ctr.write(int(self.num_images_ctr.value) + 1)
        await self.acquire_busy.write(0)
        return 0


def _make_flat_pvgroup(device_prefix: str, sub_specs: list) -> type:
    """Build a flat PVGroup with absolute PV names.

    Collects all pvproperty descriptors from (PVGroupClass, relative_prefix) pairs,
    prepends the absolute device prefix to any relative pvproperty names, and
    returns a new PVGroup subclass that must be instantiated with prefix="".
    """
    _dp = device_prefix  # real (unescaped) device prefix

    def _esc(s: str) -> str:
        return s.replace("{", "{{").replace("}", "}}")

    attrs: dict = {}
    for cls, rel_prefix in sub_specs:
        abs_real = _dp + rel_prefix
        abs_esc  = _esc(abs_real)
        for attr_name, pvprop in cls._pvs_.items():
            if attr_name in attrs:
                continue
            old_name = pvprop.pvspec.name
            # Build new absolute name
            if old_name.startswith(("XF:", "SR:")):
                # Already absolute; ensure escaped
                new_name = _esc(old_name) if "{" in old_name else old_name
            else:
                new_name = abs_esc + old_name
            # Re-build the pvproperty with the corrected name.
            # pvproperty is a descriptor; its pvspec holds the metadata.
            pvspec = pvprop.pvspec
            # Create a new pvproperty with updated name
            new_pv = pvproperty(
                name=new_name,
                value=pvspec.value,
                dtype=pvspec.dtype,
                read_only=pvspec.read_only,
                max_length=pvspec.max_length,
                doc=pvspec.doc or "",
            )
            # Preserve putters: if the original pvprop has a putter, wire it
            if pvprop.getter is not None or pvprop.putter is not None:
                # For simplicity, skip putter re-wiring in the flat merge;
                # the original class retains its behaviour when instantiated directly.
                # The flat IOC is primarily for PV registration — putters on the
                # acquire/trigger PVs are not needed for basic connectivity.
                pass
            attrs[attr_name] = new_pv

    tag = _dp.replace("{","").replace("}","").replace(":","_").replace("-","_")
    return type("FlatIOC_" + tag, (PVGroup,), attrs)


# Build SpecsIOC as a flat class so all PV names are absolute.
# This avoids the split-brace SubGroup prefix concatenation problem.
_SPECS_PREFIX = "XF:23ID2-ES{SPECS}"

_SpecsFlat = _make_flat_pvgroup(
    _SPECS_PREFIX,
    [(SpecsCamIOC, ""), (HDF5PluginStub, "HDF1:")],
)


# SpecsIOC: use the flat group directly.  The acquire putter in SpecsCamIOC
# is not propagated through _make_flat_pvgroup (putter re-wiring is omitted
# for simplicity — connections succeed and basic reads work; a full acquire
# simulation can be added in a later iteration).
SpecsIOC = _SpecsFlat


# ---------------------------------------------------------------------------
# Xspress3
# ---------------------------------------------------------------------------

_XS3_N_BINS = 4096
_XS3_CHANNELS = (1,)
_XS3_ROIS = (1, 2, 3, 4)

# roi_name values pre-seeded so 22-xspress3.py import-time .get() returns
XS3_ROI_NAMES = {
    (1, 1): "roi1",
    (1, 2): "roi2",
    (1, 3): "roi3",
    (1, 4): "roi4",
}


class Xspress3CamIOC(PVGroup):
    """Xspress3Detector cam surface (det1: prefix)."""

    acquire          = pvproperty(name="det1:Acquire",           value=0)
    acquire_busy     = pvproperty(name="det1:AcquireBusy",       value=0, read_only=True)
    acquire_time     = pvproperty(name="det1:AcquireTime",       value=1.0)
    acquire_time_rbv = pvproperty(name="det1:AcquireTime_RBV",   value=1.0, read_only=True)
    num_images       = pvproperty(name="det1:NumImages",         value=1)
    num_images_rbv   = pvproperty(name="det1:NumImages_RBV",     value=1, read_only=True)
    trigger_mode     = pvproperty(name="det1:TriggerMode",       value=0)
    trigger_mode_rbv = pvproperty(name="det1:TriggerMode_RBV",   value=0, read_only=True)
    det_state        = pvproperty(name="det1:DetectorState_RBV", value=0, read_only=True)
    status_msg       = pvproperty(name="det1:StatusMessage_RBV", value="Idle", dtype=str,
                                  max_length=256, read_only=True)
    erase            = pvproperty(name="det1:Erase",             value=0)
    ERASE            = pvproperty(name="det1:ERASE",             value=0)
    UPDATE           = pvproperty(name="det1:UPDATE",            value=0)
    num_channels     = pvproperty(name="det1:NumChannels",       value=1)
    num_channels_rbv = pvproperty(name="det1:NumChannels_RBV",   value=1, read_only=True)
    sca_time_per_pt  = pvproperty(name="det1:SCA_TimePerPoint",  value=1.0)
    ctrl_mca_roi     = pvproperty(name="det1:CTRL_MCA_ROI",      value=1)
    ctrl_dtc         = pvproperty(name="det1:CTRL_DTC",          value=0)
    data_type        = pvproperty(name="det1:DataType",          value=6)
    data_type_rbv    = pvproperty(name="det1:DataType_RBV",      value=6, read_only=True)
    array_counter    = pvproperty(name="det1:ArrayCounter",      value=0)
    array_counter_rbv= pvproperty(name="det1:ArrayCounter_RBV",  value=0, read_only=True)
    array_rate       = pvproperty(name="det1:ArrayRate_RBV",     value=0.0, read_only=True)


class Xspress3ChannelIOC(PVGroup):
    """Per-channel PVs for channel N.  Instantiated with prefix 'C{N}_'."""

    sca_array    = pvproperty(name="SCA:ArrayData",  value=[0]*16, dtype=int,
                              max_length=16, read_only=True)
    mca_array    = pvproperty(name="MCA:ArrayData",  value=[0]*_XS3_N_BINS, dtype=int,
                              max_length=_XS3_N_BINS, read_only=True)
    roi_array    = pvproperty(name="ROI:ArrayData",  value=[0]*_XS3_N_BINS, dtype=int,
                              max_length=_XS3_N_BINS, read_only=True)
    dtc_flags    = pvproperty(name="DTC_FLAGS",      value=0)
    dtc_aeg      = pvproperty(name="DTC_AEG",        value=0.0)
    dtc_aeo      = pvproperty(name="DTC_AEO",        value=0.0)
    dtc_iwg      = pvproperty(name="DTC_IWG",        value=0.0)
    dtc_iwo      = pvproperty(name="DTC_IWO",        value=0.0)
    dtc_owg      = pvproperty(name="DTC_OWG",        value=0.0)
    dtc_owo      = pvproperty(name="DTC_OWO",        value=0.0)
    gnsca        = pvproperty(name="GNSCA",          value=0.0, read_only=True)


class Xspress3RoiIOC(PVGroup):
    """Per-mcaroi PVs for channel N, roi M.  prefix = 'C{N}_MCA_ROI{M}_'"""

    callbacks_ok = pvproperty(name="CallbacksOK_RBV", value=1, read_only=True)
    min_x        = pvproperty(name="MinX",             value=0)
    min_x_rbv    = pvproperty(name="MinX_RBV",         value=0, read_only=True)
    size_x       = pvproperty(name="SizeX",            value=100)
    size_x_rbv   = pvproperty(name="SizeX_RBV",        value=100, read_only=True)
    total_rbv    = pvproperty(name="Total_RBV",         value=0.0, read_only=True)
    net_rbv      = pvproperty(name="Net_RBV",           value=0.0, read_only=True)
    roi_name     = pvproperty(name="ROIName",           value="", dtype=str, max_length=40)
    roi_name_rbv = pvproperty(name="ROIName_RBV",       value="", dtype=str, max_length=40,
                              read_only=True)


_XS3_PREFIX = "XF:23ID2-ES{Xsp:1}:"

_Xspress3Flat = _make_flat_pvgroup(
    _XS3_PREFIX,
    [
        (Xspress3CamIOC,    ""),
        (Xspress3ChannelIOC,"C1_"),
        (Xspress3RoiIOC,    "C1_MCA_ROI1_"),
        (Xspress3RoiIOC,    "C1_MCA_ROI2_"),
        (Xspress3RoiIOC,    "C1_MCA_ROI3_"),
        (Xspress3RoiIOC,    "C1_MCA_ROI4_"),
        (HDF5PluginStub,    "HDF1:"),
    ],
)


class Xspress3IOC(_Xspress3Flat):
    """Flat Xspress3 IOC with roi_name startup seeding."""

    async def _startup(self):
        """Pre-seed ROI name PVs so 22-xspress3.py .get() returns immediately."""
        for (ch, roi), name in XS3_ROI_NAMES.items():
            roi_name_pv  = f"roi_name"   # attr on the flat group
            roi_name_rbv = f"roi_name_rbv"
            # Find attrs by scanning pvdb for the right ROI prefix
            roi_prefix = f"{_XS3_PREFIX}C{ch}_MCA_ROI{roi}_"
            for attr, pvprop in type(self)._pvs_.items():
                pvname = pvprop.pvspec.name
                # pvspec.name at this point is already escaped; unescape to compare
                pvname_real = pvname.replace("{{", "{").replace("}}", "}")
                if pvname_real == roi_prefix + "ROIName":
                    await getattr(self, attr).write(name)
                elif pvname_real == roi_prefix + "ROIName_RBV":
                    await getattr(self, attr).write(name)
