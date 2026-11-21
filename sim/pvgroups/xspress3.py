"""
sim/pvgroups/xspress3.py
------------------------
The simulated Xspress3 (``XF:23ID2-ES{Xsp:1}:``): the cam (``det1:``), the MCA arrays, the ROIs
(``MCA1ROI:n:``), the scalars (``C1SCA:n:``) and the HDF5 plugin (``HDF1:``).

The PV names are not typed in here: they are read from the ophyd class that the profile builds
(``build_xspress3_class`` of nslsii, as in startup/22-xspress3.py), so the simulation serves exactly
the PVs that the installed nslsii asks for, under the names it uses. The type of each PV (string,
enumeration, array, number) is guessed from its name and its ophyd component.

Behaviour
---------
* Every setpoint with a ``_RBV`` readback follows it.
* ``det1:Acquire`` = 1 starts an acquisition: ``Acquire`` and ``Acquire_RBV`` stay 1 for
  ``AcquireTime`` seconds (at most ``MAX_ACQUIRE_S``), then the simulated spectrum (a background and
  two fluorescence lines, scaled with the time and the beam intensity) goes into ``MCA1:ArrayData`` and ``MCASUM1:ArrayData``,
  the ROI totals are the sums over ``[MinX, MinX + SizeX)``, the counters count, and both go back to 0.
  ROIs 3 and 4 start with a window around each line (:data:`ROI_WINDOWS`), so the totals count from the start.
* ``HDF1:Capture`` = 1 starts a capture and makes the file that the plugin names (``FilePath``,
  ``FileName``, ``FileNumber`` and ``FileTemplate``) a symbolic link to one shared simulated file
  (:func:`ensure_shared_file`); ending it increments the file number. Every image of every run is the
  same spectrum, so the file is the same for all of them.
* The IOC writes only below ``IOS_SIM_DATA_DIR``. A file path outside it is reported as missing
  (``FilePathExists_RBV`` = 0) and nothing is written, so that a profile that still points at the
  beamline's data directory cannot create files there.

Settings (environment): ``IOS_SIM_XS3_PUT_COMPLETION`` (default on, ``0`` switches it off: a put to ``Acquire``
completes when the acquisition has ended, as on a real IOC, and not at once), ``IOS_SIM_DATA_DIR`` (default ``/tmp/ios-sim-data``),
``IOS_SIM_XS3_FRAMES`` (frames in the shared file, default 20000).
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib

import numpy as np
from caproto import ChannelType
from caproto.server import PVGroup, pvproperty

from . import beam

log = logging.getLogger("ios.sim")

PREFIX = "XF:23ID2-ES{Xsp:1}:"
N_BINS = 4096
MAX_ACQUIRE_S = 0.5
DATASET = "entry/instrument/detector/data"
SHARED_NAME = "xspress3-sim.h5"

ENUMS: dict[str, tuple[str, ...]] = {
    "acquire": ("Done", "Acquire"),
    "capture": ("Done", "Capture"),
    "enablecallbacks": ("Disable", "Enable"),
    "arraycallbacks": ("Disable", "Enable"),
    "blockingcallbacks": ("No", "Yes"),
    "autoincrement": ("No", "Yes"),
    "autosave": ("No", "Yes"),
    "lazyopen": ("No", "Yes"),
    "storeattr": ("No", "Yes"),
    "storeperform": ("No", "Yes"),
    "deletedriverfile": ("Disable", "Enable"),
    "compression": ("None", "N-bit", "szip", "zlib", "blosc"),
    "filewritemode": ("Single", "Capture", "Stream"),
    "use": ("No", "Yes"),
}
TEXT_ENDINGS = (
    "Name", "Name_RBV", "FilePath", "FilePath_RBV", "FileName", "FileName_RBV", "FileTemplate",
    "FileTemplate_RBV", "FullFileName_RBV", "StatusMessage_RBV", "PluginType_RBV", "PortName_RBV",
    "NDArrayPort", "NDArrayPort_RBV", "ADCoreVersion_RBV", "DriverVersion_RBV", "SDKVersion_RBV",
    "SerialNumber_RBV", "FirmwareVersion_RBV", "Manufacturer_RBV", "Model_RBV", "XMLFileName",
    "XMLFileName_RBV", "LastNameError_RBV", "WriteMessage", "XMLValid_RBV", ".EGU", ".DESC",
    "Dimensions", "ExtraDimName", "PluginType", "ExtraDimNameN_RBV",
)
# Text PVs that a real IOC serves as strings of at most 40 characters (the others, such as file paths,
# are char arrays). ophyd reads a char array as an array unless the signal asks for a string.
SHORT_TEXT = (
    "PortName_RBV", "NDArrayPort", "NDArrayPort_RBV", "PluginType_RBV", "ADCoreVersion_RBV",
    "DriverVersion_RBV", "SDKVersion_RBV", "SerialNumber_RBV", "FirmwareVersion_RBV",
    "Manufacturer_RBV", "Model_RBV", "Name",
)
DEFAULTS: dict[str, object] = {
    "PortName_RBV": "HDF1",
    "NDArrayPort": "PROC1",
    "NDArrayPort_RBV": "PROC1",
    "FileTemplate": "%s%s_%6.6d.h5",
    "FileTemplate_RBV": "%s%s_%6.6d.h5",
    "PluginType_RBV": "NDFileHDF5",
    "NumCapture": 1,
    "NumCapture_RBV": 1,
    "FilePathExists_RBV": 0,
    "ArraySizeX_RBV": N_BINS,
    "ArraySizeY_RBV": 1,
    "ArraySize_RBV": N_BINS,
    "ArraySize0": N_BINS,
    "ArraySize0_RBV": N_BINS,
    "ArraySize1": 1,
    "ArraySize1_RBV": 1,
    "ArraySize2": 1,
    "ArraySize2_RBV": 1,
    "EnableCallbacks": 1,
    "EnableCallbacks_RBV": 1,
    "ArrayCallbacks": 1,
    "ArrayCallbacks_RBV": 1,
    "AcquireTime": 0.1,
    "AcquireTime_RBV": 0.1,
    "NumImages": 1,
    "NumImages_RBV": 1,
    "MinX": 0,
    "SizeX": 0,
}

# The windows that the ROIs start with, so that the totals count something before anyone applies a
# preset: ROI 4 (PFY) around the line at bin 820 and ROI 3 (IPFY) around the one at bin 450, each
# +-3 sigma. ROIs 1 and 2 stay empty.
ROI_WINDOWS: dict[int, tuple[int, int]] = {4: (775, 90), 3: (414, 72)}


class Needed:
    """One PV the profile's class asks for."""

    __slots__ = ("name", "ro", "string")

    def __init__(self, name: str, ro: bool, string: bool):
        self.name, self.ro, self.string = name, ro, string


def profile_class():
    """The ophyd class of the profile's ``xs3`` (startup/22-xspress3.py)."""
    from nslsii.areadetector.xspress3 import (
        Xspress3HDF5Plugin,
        Xspress3Trigger,
        build_xspress3_class,
    )
    from ophyd import Component as Cpt
    from ophyd.areadetector import Xspress3Detector

    return build_xspress3_class(
        channel_numbers=(1,),
        mcaroi_numbers=(1, 2, 3, 4),
        image_data_key="data",
        xspress3_parent_classes=(Xspress3Detector, Xspress3Trigger),
        extra_class_members={
            "hdf5plugin": Cpt(
                Xspress3HDF5Plugin,
                "HDF1:",
                name="h5p",
                root_path="/",
                path_template="/%Y",
                resource_kwargs={},
            ),
        },
    )


def needed_pvs() -> list[Needed]:
    """Every PV of the profile's Xspress3 class, by walking its components (nothing connects)."""
    from ophyd import Device
    from ophyd.signal import EpicsSignalBase, EpicsSignalRO

    found: dict[str, Needed] = {}

    def add(name: str, ro: bool, string: bool) -> None:
        old = found.get(name)
        found[name] = Needed(name, ro and (old.ro if old else True), string or (old.string if old else False))

    def walk(klass, prefix: str) -> None:
        for _, cpt in klass._sig_attrs.items():
            cls, suffix, kwargs = cpt.cls, cpt.suffix or "", cpt.kwargs
            if not isinstance(cls, type):
                continue
            if issubclass(cls, Device):
                walk(cls, prefix + suffix)
            elif issubclass(cls, EpicsSignalBase):
                string = bool(kwargs.get("string"))
                if "WithRBV" in cls.__name__ or cls.__name__ == "EpicsPathSignal":
                    add(prefix + suffix, False, string)
                    add(prefix + suffix + "_RBV", True, string)
                else:
                    add(prefix + suffix, issubclass(cls, EpicsSignalRO), string)
                    write_pv = kwargs.get("write_pv")
                    if write_pv:
                        add(prefix + write_pv, False, string)

    walk(profile_class(), PREFIX)
    return list(found.values())


def _escape(name: str) -> str:
    return name.replace("{", "{{").replace("}", "}}")


def _last(short: str) -> str:
    return short.split(":")[-1]


def _index(value, strings: tuple[str, ...]) -> int:
    """The index of an enumeration value that arrives as an index, a string or bytes."""
    if isinstance(value, bytes):
        value = value.decode()
    if isinstance(value, str):
        return strings.index(value) if value in strings else int(float(value))
    return int(value)


def roi_window_default(short: str) -> int | None:
    """The starting ``MinX`` or ``SizeX`` (or its readback) of an ROI named like ``MCA1ROI:4:MinX``."""
    parts = short.split(":")
    if len(parts) != 3 or parts[0] != "MCA1ROI" or not parts[1].isdigit():
        return None
    window = ROI_WINDOWS.get(int(parts[1]))
    field = parts[2].removesuffix("_RBV")
    if window is None or field not in ("MinX", "SizeX"):
        return None
    return window[0] if field == "MinX" else window[1]


def _short(name: str) -> str:
    return name[len(PREFIX):] if name.startswith(PREFIX) else name


def _enum_key(short: str) -> str:
    last = short.split(":")[-1]
    if last.endswith("_RBV"):
        last = last[:-4]
    return last.lower()


def spectrum(seconds: float, rng: np.random.Generator, intensity: float = 1.0) -> np.ndarray:
    """A simulated fluorescence spectrum: a falling background and two lines.

    ``intensity`` scales the rate (the relative beam intensity, sim/pvgroups/beam.py).
    """
    bins = np.arange(N_BINS)
    rate = (
        5.0
        + 200.0 * np.exp(-bins / 1500.0)
        + 3000.0 * np.exp(-0.5 * ((bins - 450) / 12.0) ** 2)
        + 2000.0 * np.exp(-0.5 * ((bins - 820) / 15.0) ** 2)
    )
    return rng.poisson(rate * max(seconds, 0.01) * max(intensity, 0.0)).astype(np.int32)


def data_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("IOS_SIM_DATA_DIR", "/tmp/ios-sim-data")).resolve()


def ensure_shared_file(directory: pathlib.Path | None = None, frames: int | None = None) -> pathlib.Path:
    """Write the one file that stands in for every run's Xspress3 file, if it is not there.

    Shape ``(frames, 1, 4096)``: frame, channel, bin; the same spectrum in every frame. Chunks of
    256 identical frames compress to little at gzip level 9, so the file is about 3 MB.
    """
    import h5py

    directory = directory or data_dir()
    frames = frames or int(os.environ.get("IOS_SIM_XS3_FRAMES", "20000"))
    path = directory / ".shared" / SHARED_NAME
    if path.exists():
        with h5py.File(path, "r") as handle:
            if DATASET in handle and handle[DATASET].shape[0] >= frames:
                return path
    path.parent.mkdir(parents=True, exist_ok=True)
    one = spectrum(1.0, np.random.default_rng(2026)).reshape(1, 1, N_BINS)
    chunk = 256
    with h5py.File(path, "w") as handle:
        dataset = handle.create_dataset(
            DATASET, shape=(frames, 1, N_BINS), dtype="int32", chunks=(chunk, 1, N_BINS),
            compression="gzip", compression_opts=9,  # level 4 does not find the repeats 16 KB apart
        )
        block = np.repeat(one, chunk, axis=0)
        for start in range(0, frames, chunk):
            stop = min(start + chunk, frames)
            dataset[start:stop] = block[: stop - start]
    log.warning("wrote the shared Xspress3 file %s (%d frames)", path, frames)
    return path


def _inside(directory: pathlib.Path, candidate: pathlib.Path) -> bool:
    try:
        candidate.resolve().relative_to(directory)
    except (ValueError, OSError):
        return False
    return True


def build() -> type:
    """The flat PVGroup of the simulated Xspress3 (instantiate with ``prefix=""``)."""
    pvs = needed_pvs()
    names = {p.name for p in pvs}
    attr_of = {p.name: f"pv_{i:03d}" for i, p in enumerate(pvs)}
    attrs: dict[str, object] = {}

    def attr(name: str) -> str:
        return attr_of[PREFIX + name]

    def put_echo(rbv_attr: str):
        async def putter(self, instance, value):
            await getattr(self, rbv_attr).write(value)
            return value

        return putter

    for p in pvs:
        short = _short(p.name)
        enum = ENUMS.get(_enum_key(short))
        value: object
        kwargs: dict = {}
        if "ArrayData" in short and not short.endswith(".EGU"):
            value, kwargs = np.zeros(N_BINS, dtype=np.int32), {"dtype": int, "max_length": N_BINS}
        elif enum is not None and not short.endswith(".EGU"):
            value = 1 if _enum_key(short) in ("enablecallbacks", "arraycallbacks") else 0
            kwargs = {"dtype": ChannelType.ENUM, "enum_strings": enum}
        elif _last(short) in SHORT_TEXT:
            value = str(DEFAULTS.get(_last(short), ""))
            kwargs = {"dtype": ChannelType.STRING}
        elif p.string or short.endswith(TEXT_ENDINGS):
            value, kwargs = str(DEFAULTS.get(_last(short), "")), {"dtype": str, "max_length": 256}
        else:
            value = DEFAULTS.get(_last(short), 0.0)
            window = roi_window_default(short)
            if window is not None:
                value = window
            if short.startswith("MCA1ROI:") and short.endswith(":Name"):
                value = ""
            kwargs = {"dtype": float if isinstance(value, float) else int}
        if short.startswith("MCA1ROI:") and short.endswith(":Name"):
            # a string PV (not a char array): 22-xspress3.py tests the truth of the value
            value, kwargs = f"roi{short.split(':')[1]}", {"dtype": ChannelType.STRING}
        prop = pvproperty(name=_escape(p.name), value=value, read_only=p.ro, **kwargs)
        rbv = p.name + "_RBV"
        if not p.ro and rbv in names and _short(p.name) not in ("det1:Acquire", "HDF1:Capture"):
            prop = prop.putter(put_echo(attr_of[rbv]))
        attrs[attr_of[p.name]] = prop

    # -- acquisition -------------------------------------------------------------------------
    async def acquire_put(self, instance, value):
        if _index(value, ENUMS["acquire"]) != 1:
            return value
        if getattr(self, "_acquiring", False):
            return value
        self._acquiring = True
        done = asyncio.Event()  # one per acquisition: the next put may arrive while this one is still ending
        await getattr(self, attr("det1:Acquire_RBV")).write(1)
        asyncio.get_event_loop().create_task(self._acquire(done))
        if os.environ.get("IOS_SIM_XS3_PUT_COMPLETION", "1") != "0":
            # As on an areaDetector IOC: the put to Acquire completes when the acquisition has ended, so a client
            # that waits for put completion does not depend on seeing the readback go to 1 and back to 0.
            await done.wait()
            return 0  # the value the setpoint has by then
        return value

    async def _acquire(self, done: asyncio.Event | None = None):
        rng = np.random.default_rng()
        seconds = float(getattr(self, attr("det1:AcquireTime")).value)
        await asyncio.sleep(min(max(seconds, 0.0), MAX_ACQUIRE_S))
        counts = spectrum(seconds, rng, beam.intensity())
        for array in ("MCA1:ArrayData", "MCASUM1:ArrayData"):
            if PREFIX + array in names:
                await getattr(self, attr(array)).write(counts)
        total = 0
        for roi in (1, 2, 3, 4):
            low = int(getattr(self, attr(f"MCA1ROI:{roi}:MinX")).value)
            size = int(getattr(self, attr(f"MCA1ROI:{roi}:SizeX")).value)
            roi_total = float(counts[max(low, 0): max(low + size, 0)].sum())
            await getattr(self, attr(f"MCA1ROI:{roi}:Total_RBV")).write(roi_total)
            if PREFIX + f"C1SCA:{roi}:Value_RBV" in names:
                await getattr(self, attr(f"C1SCA:{roi}:Value_RBV")).write(roi_total)
            total += roi_total
        if PREFIX + "C1SCA:0:Value_RBV" in names:
            await getattr(self, attr("C1SCA:0:Value_RBV")).write(float(counts.sum()))
        for name in ("det1:ArrayCounter", "det1:ArrayCounter_RBV"):
            if PREFIX + name in names:
                await getattr(self, attr(name)).write(getattr(self, attr(name)).value + 1)
        if PREFIX + "HDF1:NumCaptured_RBV" in names and getattr(self, "_capturing", False):
            captured = getattr(self, attr("HDF1:NumCaptured_RBV"))
            await captured.write(captured.value + 1)
        # The readback going to 0 is what a client waits for (nslsii's Xspress3Trigger finishes its status
        # on 1 -> 0), and the next trigger can follow at once, so the detector must be ready for it first:
        # setpoint to 0, not busy, and only then the readback.
        await getattr(self, attr("det1:Acquire")).write(0)
        self._acquiring = False
        await getattr(self, attr("det1:Acquire_RBV")).write(0)
        if done is not None:
            done.set()

    attrs[attr_of[PREFIX + "det1:Acquire"]] = attrs[attr_of[PREFIX + "det1:Acquire"]].putter(acquire_put)

    # -- the HDF5 plugin ---------------------------------------------------------------------
    def current(self, new: dict | None = None) -> dict:
        """The file settings, with ``new`` (the value being put, not stored yet) on top."""
        values = {
            key: getattr(self, attr("HDF1:" + key)).value
            for key in ("FilePath", "FileName", "FileNumber", "FileTemplate")
        }
        values.update(new or {})
        return values

    def full_name(self, new: dict | None = None) -> pathlib.Path:
        values = current(self, new)
        path = str(values["FilePath"])
        name = str(values["FileName"])
        number = int(values["FileNumber"])
        template = str(values["FileTemplate"])
        try:
            return pathlib.Path(template % (path, name, number))
        except (TypeError, ValueError):
            return pathlib.Path(path) / f"{name}_{number:06d}.h5"

    async def refresh_names(self, new: dict | None = None):
        await getattr(self, attr("HDF1:FullFileName_RBV")).write(str(full_name(self, new)))
        directory = pathlib.Path(str(current(self, new)["FilePath"]))
        ok = bool(str(directory)) and _inside(data_dir(), directory) and directory.is_dir()
        await getattr(self, attr("HDF1:FilePathExists_RBV")).write(1 if ok else 0)

    def refreshing(short: str):
        base = attrs[attr_of[PREFIX + short]]

        async def putter(self, instance, value):
            await getattr(self, attr_of[PREFIX + short + "_RBV"]).write(value)
            # the setpoint itself is stored when the putter returns: use the new value for the names
            await refresh_names(self, {_last(short): value})
            return value

        return base.putter(putter)

    for short in ("HDF1:FilePath", "HDF1:FileName", "HDF1:FileNumber", "HDF1:FileTemplate"):
        if PREFIX + short in names and PREFIX + short + "_RBV" in names:
            attrs[attr_of[PREFIX + short]] = refreshing(short)

    async def create_directory_put(self, instance, value):
        await getattr(self, attr("HDF1:CreateDirectory_RBV")).write(value)
        directory = pathlib.Path(str(getattr(self, attr("HDF1:FilePath")).value))
        if str(directory) and _inside(data_dir(), directory):
            directory.mkdir(parents=True, exist_ok=True)
        elif str(directory):
            log.warning("not creating %s: outside IOS_SIM_DATA_DIR %s", directory, data_dir())
        await refresh_names(self)
        return value

    async def capture_put(self, instance, value):
        capture = getattr(self, attr("HDF1:Capture_RBV"))
        if _index(value, ENUMS["capture"]) == 1:
            target = full_name(self)
            if _inside(data_dir(), target):
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(ensure_shared_file())
            else:
                log.warning("not writing %s: outside IOS_SIM_DATA_DIR %s", target, data_dir())
            self._capturing = True
            await getattr(self, attr("HDF1:NumCaptured_RBV")).write(0)
            await capture.write(1)
            await refresh_names(self)
        else:
            if getattr(self, "_capturing", False):
                self._capturing = False
                number = getattr(self, attr("HDF1:FileNumber"))
                if _index(getattr(self, attr("HDF1:AutoIncrement")).value, ENUMS["autoincrement"]) == 1:
                    await number.write(int(number.value) + 1)
                    await getattr(self, attr("HDF1:FileNumber_RBV")).write(int(number.value))
            await capture.write(0)
            await refresh_names(self)
        return value

    if PREFIX + "HDF1:CreateDirectory" in names:
        attrs[attr_of[PREFIX + "HDF1:CreateDirectory"]] = attrs[
            attr_of[PREFIX + "HDF1:CreateDirectory"]
        ].putter(create_directory_put)
    attrs[attr_of[PREFIX + "HDF1:Capture"]] = attrs[attr_of[PREFIX + "HDF1:Capture"]].putter(capture_put)
    attrs["_acquire"] = _acquire

    async def _startup(self):
        """Called by run_iocs.run_with_startup: write the shared file before clients connect."""
        ensure_shared_file()

    attrs["_startup"] = _startup
    return type("Xspress3SimIOC", (PVGroup,), attrs)
