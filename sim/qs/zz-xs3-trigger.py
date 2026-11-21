# Sorts after zz-sim-paths.py. Other ways for an Xspress3 trigger to finish in the mock Queueserver
# (sim/qs/xs3_trigger.py): scans stalled when the client missed the short 1 of Acquire_RBV.
# IOS_SIM_XS3_TRIGGER: "put+counter" (put completion, with the image counter after a grace as a backstop;
# the default), "put" (put completion), "counter" (the image counter) or "edge" (nslsii's own, for comparisons).
import os as _os

from sim.qs import xs3_trigger as _xs3_trigger

_mode = _os.environ.get("IOS_SIM_XS3_TRIGGER", "put+counter")
if "put" in _mode:
    _xs3_trigger.install_put_completion(xs3)
if "counter" in _mode:
    _xs3_trigger.install(xs3)
