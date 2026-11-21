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


def install(detector, grace: float = GRACE_S) -> None:
    """Wrap ``detector.trigger`` so that its status also finishes on the image counter."""
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


def install_put_completion(detector) -> None:
    """Make nslsii's ``acquire.put(1, wait=False)`` use put completion, and finish the trigger from it.

    An areaDetector IOC completes a put to ``Acquire`` when the acquisition has ended (the busy-record
    convention), so the reply to the write says the point is done and cannot be lost the way a short
    monitor value can. nslsii's trigger does not wait for it; this wrapper sends the same write with
    ``use_complete=True`` and finishes the trigger's status from the callback. The readback edge may finish
    it first (the usual order); then nothing happens.
    """
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
