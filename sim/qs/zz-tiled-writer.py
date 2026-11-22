# If IOS_SIM_TILED_URI is set, the mock Queueserver writes the documents of every run
# into that Tiled while the run goes on, one row at a time (TiledWriter's batch_size=1; its default of 10000
# shows nothing until the run ends). The IOS Skybeam page reads the live rows from there.
# The key is in IOS_SIM_TILED_API_KEY (or in the file named by IOS_SIM_TILED_API_KEY_FILE). Only a Tiled on
# this machine is accepted: the mock must never write to the real one.
#
# The writer runs in a thread of its own: TiledWriter retries a failed request for about 40 s and then raises into
# the RunEngine, so a Tiled that is down or slow would stall a scan and then fail it. Here the RunEngine only puts
# the document in a queue; a document that cannot be written is logged and dropped, and the run goes on.
import os as _os
from urllib.parse import urlparse as _urlparse

_uri = _os.environ.get("IOS_SIM_TILED_URI", "")
if _uri:
    _host = _urlparse(_uri).hostname
    if _host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"IOS_SIM_TILED_URI must be on this machine, not {_host!r}")
    _key = _os.environ.get("IOS_SIM_TILED_API_KEY", "")
    _key_file = _os.environ.get("IOS_SIM_TILED_API_KEY_FILE", "")
    if not _key and _key_file:
        with open(_key_file, encoding="utf-8") as _handle:
            _key = _handle.read().strip()
    if not _key:
        raise RuntimeError("IOS_SIM_TILED_URI is set without IOS_SIM_TILED_API_KEY or IOS_SIM_TILED_API_KEY_FILE")

    import numpy as _np
    from bluesky_tiled_plugins import TiledWriter as _TiledWriter
    from tiled.client import from_uri as _from_uri

    def _numpy_dtype_strings(descriptor):
        # nslsii's Xspress3 describes its external array with dtype_str "uint32"; the writer turns that into
        # dtype_numpy, whose schema wants a numpy type string such as "<u4", and rejects the run.
        for spec in descriptor["data_keys"].values():
            dtype_str = spec.get("dtype_str")
            if isinstance(dtype_str, str) and not dtype_str[:1] in "|<>=":
                spec["dtype_str"] = _np.dtype(dtype_str).str
        return descriptor

    import copy as _copy
    import logging as _logging
    import queue as _queue
    import threading as _threading

    class _BackgroundWriter:
        def __init__(self, writer, maxsize=100_000):
            self._writer = writer
            self._queue = _queue.Queue(maxsize)
            self._log = _logging.getLogger("ios.sim")
            _threading.Thread(target=self._run, name="tiled-writer", daemon=True).start()

        def __call__(self, name, doc):
            try:
                self._queue.put_nowait((name, _copy.deepcopy(doc)))
            except _queue.Full:
                self._log.warning("SIM: the Tiled queue is full; a %s document is dropped", name)

        def _run(self):
            while True:
                name, doc = self._queue.get()
                try:
                    self._writer(name, doc)
                except Exception as exc:  # the run goes on without it
                    self._log.warning("SIM: Tiled did not take a %s document: %s: %s", name, type(exc).__name__, exc)

    _tiled_client = _from_uri(_uri, api_key=_key)
    RE.subscribe(
        _BackgroundWriter(_TiledWriter(_tiled_client, batch_size=1, patches={"descriptor": _numpy_dtype_strings}))
    )
    del _key
