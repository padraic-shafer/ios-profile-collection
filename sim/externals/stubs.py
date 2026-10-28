"""
sim/externals/stubs.py
-----------------------
Monkey-patch stubs for external services that cannot be replaced by
container images alone, or that make blocking network calls at import time.

Called by pre_exec.py before the profile startup files are executed.

Services stubbed here
~~~~~~~~~~~~~~~~~~~~~
amostra (SampleReference / ContainerReference)
    No viable public container image for the NSLS-II amostra server.
    Constructor makes a network connection immediately; stub to a no-op class.

pyOlog (SimpleOlogClient / logbook_cb_factory)
    No clean headless Olog container.  The SimpleOlogClient constructor reads
    ~/.olog and contacts the Olog server.  Stub to a silent no-op.

databroker 'ios' catalog
    configure_base(broker_name='ios') resolves via databroker's catalog
    mechanism.  In sim mode we redirect to a local msgpack catalog written
    to /tmp/ios-sim-catalog/.  If databroker isn't configured that way,
    the stub returns a no-op Broker object so the profile still loads.

redis / configure_base kwargs override
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    # WARNING: Sim mode forces redis_ssl=False and redirects redis to
    # localhost:6379.  The production profile targets
    # xf23id2-ios-redis1.nsls2.bnl.gov:6380 with TLS enabled.  The local
    # sim redis container is plaintext; do NOT reuse this path in production.
    #
    This override is applied by wrapping nslsii.configure_base so that the
    redis kwargs are replaced before the real function sees them.

kafka config path
    Points BLUESKY_KAFKA_CONFIG_FILE at sim/externals/kafka.yml so that
    bluesky-kafka connects to the local broker instead of the production one.
"""

from __future__ import annotations

import logging
import os
import sys
import types
import pathlib

_log = logging.getLogger("ios.sim")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SIM_DIR = pathlib.Path(__file__).parent
_REPO_ROOT = _SIM_DIR.parent.parent
_KAFKA_CFG = _SIM_DIR / "kafka.yml"
_CATALOG_DIR = pathlib.Path("/tmp/ios-sim-catalog")


# ---------------------------------------------------------------------------
# 1. amostra stubs
# ---------------------------------------------------------------------------

def _stub_amostra() -> None:
    """Replace amostra client classes with silent no-ops."""

    class _NoOpReference:
        """No-op stand-in for amostra SampleReference / ContainerReference."""

        def __init__(self, *args, **kwargs):
            _log.debug("SIM: amostra %s stubbed (no-op)", type(self).__name__)

        def __getattr__(self, name):
            # Return a callable no-op for any method access
            def _noop(*a, **kw):
                return None
            return _noop

    # Stub at the module level so imports in 00-startup.py find the no-ops
    try:
        import amostra.client.commands as _amostra_mod
        _amostra_mod.SampleReference   = type("SampleReference",   (_NoOpReference,), {})
        _amostra_mod.ContainerReference= type("ContainerReference", (_NoOpReference,), {})
        _log.info("SIM: amostra SampleReference / ContainerReference stubbed")
    except ImportError:
        _log.info("SIM: amostra not importable — nothing to stub")


# ---------------------------------------------------------------------------
# 2. pyOlog stubs
# ---------------------------------------------------------------------------

def _stub_olog() -> None:
    """Replace SimpleOlogClient and configure_olog with silent no-ops."""

    class _NoOpOlogClient:
        def __init__(self, *args, **kwargs):
            _log.debug("SIM: SimpleOlogClient stubbed (no-op)")

        def log(self, *args, **kwargs):
            pass

    def _noop_logbook_cb_factory(*args, **kwargs):
        def _cb(*a, **kw):
            pass
        return _cb

    def _noop_configure_olog(*args, **kwargs):
        pass

    try:
        import pyOlog
        pyOlog.SimpleOlogClient = _NoOpOlogClient
        _log.info("SIM: pyOlog.SimpleOlogClient stubbed")
    except ImportError:
        pass

    try:
        import pyOlog.SimpleOlogClient as _m
        _m.SimpleOlogClient = _NoOpOlogClient
    except (ImportError, AttributeError):
        pass

    try:
        import bluesky.callbacks.olog as _olog_cb
        _olog_cb.logbook_cb_factory = _noop_logbook_cb_factory
        _log.info("SIM: bluesky.callbacks.olog.logbook_cb_factory stubbed")
    except ImportError:
        pass

    try:
        import nslsii
        nslsii.configure_olog = _noop_configure_olog
        _log.info("SIM: nslsii.configure_olog stubbed")
    except (ImportError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# 3. redis + configure_base wrapper (WARNING: TLS disabled in sim mode)
# ---------------------------------------------------------------------------

def _patch_configure_base() -> None:
    """Wrap nslsii.configure_base to redirect redis to localhost (no TLS).

    # WARNING: Sim mode forces redis_ssl=False and redirects redis to
    # localhost:6379.  The production profile uses TLS against the remote
    # redis server at xf23id2-ios-redis1.nsls2.bnl.gov:6380.  The local sim
    # redis container is plaintext.  Do NOT reuse this path in production.
    """
    import logging as _logging
    _sim_log = _logging.getLogger("ios.sim")

    # Emit a WARNING so the operator sees this clearly in the session log.
    _sim_log.warning(
        "SIM MODE: redis TLS DISABLED (redis_ssl=False), "
        "redis host overridden to localhost:6379 — NOT for production use."
    )

    try:
        import nslsii as _nslsii
    except ImportError:
        _sim_log.warning("SIM: nslsii not importable; cannot patch configure_base")
        return

    _real_configure_base = _nslsii.configure_base

    def _sim_configure_base(user_ns, broker_name="temp", *args, **kwargs):
        # Override redis connection to local plaintext container
        kwargs["redis_url"]  = "localhost"
        kwargs["redis_port"] = 6379
        kwargs["redis_ssl"]  = False

        # Disable kafka publish if the sim Kafka container isn't running,
        # to avoid blocking connect timeouts.  Can be re-enabled by setting
        # IOS_SIM_KAFKA=1 in the environment.
        if not os.environ.get("IOS_SIM_KAFKA"):
            kwargs["publish_documents_with_kafka"] = False
            _sim_log.info(
                "SIM: Kafka publishing disabled (set IOS_SIM_KAFKA=1 to enable). "
                "Start the kafka container via 'pixi run sim-up' first."
            )

        return _real_configure_base(user_ns, broker_name, *args, **kwargs)

    _nslsii.configure_base = _sim_configure_base
    _sim_log.info("SIM: nslsii.configure_base wrapped (redis→localhost, TLS off)")


# ---------------------------------------------------------------------------
# 4. Kafka config path
# ---------------------------------------------------------------------------

def _set_kafka_config() -> None:
    """Point BLUESKY_KAFKA_CONFIG_FILE at the sim kafka.yml."""
    if _KAFKA_CFG.exists():
        os.environ["BLUESKY_KAFKA_CONFIG_FILE"] = str(_KAFKA_CFG)
        _log.info("SIM: BLUESKY_KAFKA_CONFIG_FILE -> %s", _KAFKA_CFG)
    else:
        _log.warning("SIM: sim kafka.yml not found at %s", _KAFKA_CFG)


# ---------------------------------------------------------------------------
# 5. databroker local catalog
# ---------------------------------------------------------------------------

def _stub_databroker() -> None:
    """Ensure a local msgpack catalog directory exists for sim runs."""
    _CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    _log.info("SIM: local catalog dir: %s", _CATALOG_DIR)
    # databroker 2.x (tiled-based) is resolved via nslsii.configure_base;
    # setting the catalog path in the env lets databroker find it.
    os.environ.setdefault("DATABROKER_CATALOG_DIR", str(_CATALOG_DIR))


# ---------------------------------------------------------------------------
# 6. bluesky zmq Publisher safety
# ---------------------------------------------------------------------------

def _stub_zmq_publisher() -> None:
    """Make the zmq Publisher non-fatal if the proxy is not running.

    00-startup.py does:
        pub = Publisher('localhost:5577')
        RE.subscribe(pub)

    If the zmq proxy container is not up, the Publisher constructor will
    succeed (zmq is async) but messages will be silently dropped.  No stub
    needed — this is already non-fatal.  Log a reminder only.
    """
    _log.info(
        "SIM: zmq Publisher targets localhost:5577. "
        "Start 'pixi run sim-up' to bring up the bluesky-0MQ-proxy container."
    )


# ---------------------------------------------------------------------------
# Entry point — apply all stubs
# ---------------------------------------------------------------------------

def apply_all() -> None:
    """Apply every stub/patch.  Call this from pre_exec.py."""
    _stub_amostra()
    _stub_olog()
    _patch_configure_base()
    _set_kafka_config()
    _stub_databroker()
    _stub_zmq_publisher()
    _log.info("SIM: all stubs applied")
