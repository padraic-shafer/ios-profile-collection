"""A second way for a simulated Xspress3 trigger to finish, for the mock Queueserver only.

nslsii's ``Xspress3Trigger`` finishes the status of a trigger when it sees ``Acquire_RBV`` go from 1
to 0. A Channel Access monitor does not promise to deliver every intermediate value: a client that is
busy (a scan writes two spectra and 32 scaler channels a point, and prints a table line) can receive
the 0 without ever having received the 1 of an acquisition that lasted 0.1 s, and then the status never
finishes and the scan waits forever. ``install`` makes a trigger also finish when the image counter
(``ArrayCounter_RBV``) is above its value at the time of the trigger. The counter only goes up and the
simulated detector writes it before it writes the readback, so a lost 1 does not hide the end of an
acquisition. The production profile and nslsii are not changed: the real detector's acquisitions last
much longer than a scan's period, and the edge is its own.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("ios.sim")

# How long the readback edge has to finish a trigger after the counter has moved.
GRACE_S = 0.5


def _keep_the_status(detector) -> None:
    """Make ``detector.trigger`` return its status even when the acquisition has ended before it returns.

    nslsii's ``trigger`` returns ``self._acquire_status``, which the end of the acquisition sets to None. A
    short acquisition on a busy worker (the Tiled writer's thread, a long table print) can end between the
    write and the return, and the RunEngine then gets None and fails the plan ('NoneType' has no attribute
    'done'). The status is remembered when it is made and returned in that case; it is already finished.
    """
    make = getattr(detector, "new_acquire_status", None)
    if make is None or getattr(detector, "_xs3_keeps_status", False):
        return
    detector._xs3_keeps_status = True
    original = detector.trigger

    def new_acquire_status(*args, **kwargs):
        status = make(*args, **kwargs)
        detector._xs3_last_status = status
        return status

    def trigger():
        status = original()
        return status if status is not None else getattr(detector, "_xs3_last_status", None)

    detector.new_acquire_status = new_acquire_status
    detector.trigger = trigger


def install(detector, grace: float = GRACE_S) -> None:
    """Wrap ``detector.trigger`` so that its status also finishes on the image counter."""
    _keep_the_status(detector)
    original = detector.trigger
    counter = detector.cam.array_counter

    def trigger():
        before = counter.get()
        status = original()

        def finish_if_still_waiting():
            if status.done:
                return  # the usual case: the readback edge came
            try:
                status.set_finished()
            except Exception:  # the edge finished it at the same moment
                return
            # nslsii's callback would finish it a second time when the readback falls
            if getattr(detector, "_acquire_status", None) is status:
                detector._acquire_status = None
            log.warning("xs3 trigger finished by the image counter (the readback edge was not seen)")

        def counted(value=None, **kwargs):
            if value is None or value <= before:
                return
            counter.clear_sub(counted)
            if not status.done:
                timer = threading.Timer(grace, finish_if_still_waiting)
                timer.daemon = True
                timer.start()

        counter.subscribe(counted, run=True)
        if status.done:
            counter.clear_sub(counted)
        else:
            status.add_callback(lambda _status: counter.clear_sub(counted))
        return status

    detector.trigger = trigger


def _ignore_the_edge(value=None, old_value=None, **kwargs) -> None:
    """Stands in for nslsii's ``_acquire_changed``, which finishes a trigger on the 1 to 0 of the readback."""


def install_put_completion(detector, keep_edge: bool = False) -> None:
    """Make nslsii's ``acquire.put(1, wait=False)`` use put completion, and finish the trigger from it.

    An areaDetector IOC completes a put to ``Acquire`` when the acquisition has ended (the busy-record
    convention), so the reply to the write says the point is done and cannot be lost the way a short
    monitor value can. nslsii's trigger does not wait for it; this wrapper sends the same write with
    ``use_complete=True`` and finishes the trigger's status from the callback.

    nslsii's own edge callback is switched off (``keep_edge=True`` keeps it): with two things that finish the same
    status in no fixed order (they run on different ophyd threads), the second raised InvalidState (167 times in 3
    hours on sb1) and a late edge could finish the next trigger early, so that a point read the previous frame.
    The put completion finishes each trigger, with the image counter as a backstop if that is installed.
    """
    _keep_the_status(detector)
    if not keep_edge and hasattr(detector, "_acquire_changed"):
        # stage() subscribes self._acquire_changed, and unstage() clears the same attribute
        detector._acquire_changed = _ignore_the_edge
    acquire = detector.cam.acquire
    original_put = acquire.put

    def put(value, *args, **kwargs):
        if value == 1 and kwargs.get("wait") is False and "callback" not in kwargs and not kwargs.get("use_complete"):
            status = getattr(detector, "_acquire_status", None)

            def done(**_kwargs):
                if status is None or status.done:
                    return
                try:
                    status.set_finished()
                except Exception:  # the readback edge finished it at the same moment
                    return
                if getattr(detector, "_acquire_status", None) is status:
                    detector._acquire_status = None
                log.debug("xs3 trigger finished by put completion")

            return original_put(value, *args, use_complete=True, callback=done, **kwargs)
        return original_put(value, *args, **kwargs)

    acquire.put = put
