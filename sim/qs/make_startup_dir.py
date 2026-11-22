"""Make the startup directory of the mock Queueserver.

``start-re-manager --startup-dir`` loads every ``*.py`` file of a directory in alphabetical
order and reads ``user_group_permissions.yaml`` and ``existing_plans_and_devices.yaml`` from it
(and writes the latter). The directory made here holds

* ``00-00-sim-guard.py``: the guard (sim/qs/guard.py), which sorts before ``00-startup.py``, and
  ``zz-sim-paths.py``, which points the Xspress3 files at the simulation's directory, and
  ``zz-tiled-writer.py``, which writes the documents into a local Tiled if IOS_SIM_TILED_URI is set, and
  ``zz-xs3-trigger.py``, which sorts last and lets an Xspress3 trigger finish on the image counter too;
* symbolic links to the numbered profile files of ``startup/`` (the profile is not changed or
  copied), except the ones in EXCLUDE, and the Qt and logging helpers that are not numbered;
* ``user_group_permissions.yaml`` (sim/qs/).

It must be writable by the Queueserver, which stores ``existing_plans_and_devices.yaml`` in it.

    python sim/qs/make_startup_dir.py /var/lib/xas-mock-qs/startup
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil

REPO = pathlib.Path(__file__).resolve().parents[2]
# 47 loads a GUI toolkit. (21, the SPECS analyzer of the APPES end station, stays: E_ramp tests
# `specs in dets`, so a profile without it fails in every ramp. Its PVs are fabricated by the
# simulated IOC's fallback, see sim/run_iocs.py.)
EXCLUDE = {"47-IOS_gui.py"}
NUMBERED = re.compile(r"^\d\d-.*\.py$")


def make_startup_dir(target: pathlib.Path, repo: pathlib.Path = REPO) -> list[str]:
    """Create or refresh ``target``. Returns the names of the startup files in load order."""
    target.mkdir(parents=True, exist_ok=True)
    wanted: dict[str, pathlib.Path] = {"00-00-sim-guard.py": repo / "sim" / "qs" / "00-00-sim-guard.py"}
    for path in sorted((repo / "startup").iterdir()):
        if NUMBERED.match(path.name) and path.name not in EXCLUDE and path.is_file():
            wanted[path.name] = path
    # last: the sim's own paths for the Xspress3 files (it must not write the beamline's data directory)
    wanted["zz-sim-paths.py"] = repo / "sim" / "qs" / "zz-sim-paths.py"
    # after it: a second way for an Xspress3 trigger to finish (sim/qs/xs3_trigger.py)
    wanted["zz-xs3-trigger.py"] = repo / "sim" / "qs" / "zz-xs3-trigger.py"
    # the documents into a Tiled on this machine, when IOS_SIM_TILED_URI says so (otherwise it does nothing)
    wanted["zz-tiled-writer.py"] = repo / "sim" / "qs" / "zz-tiled-writer.py"
    for existing in target.iterdir():
        if existing.suffix == ".py" and existing.name not in wanted:
            existing.unlink()
    for name, source in wanted.items():
        link = target / name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(source)
    shutil.copyfile(repo / "sim" / "qs" / "user_group_permissions.yaml", target / "user_group_permissions.yaml")
    return sorted(wanted)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("target", type=pathlib.Path)
    args = parser.parse_args()
    names = make_startup_dir(args.target)
    print(f"{args.target}: {len(names)} startup files, first {names[0]}, last {names[-1]}")


if __name__ == "__main__":
    main()
