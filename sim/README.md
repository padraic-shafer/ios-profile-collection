# IOS Sim IOC

Simulated EPICS IOCs for the IOS profile collection, enabling offline
development and CI without a real beamline.

Every EPICS PV name and prefix is **identical** to the real beamline IOC.
Only the Channel Access addressing differs — the sim server binds to
`127.0.0.1` and clients point at it via `EPICS_CA_ADDR_LIST=127.0.0.1`.

---

## Quick start

### 1. Install the sim environment

```bash
pixi install --environment sim
```

### 2. Start external services (redis, kafka, zmq-proxy)

```bash
cd sim/externals
pixi run sim-up
```

Wait for all three containers to pass their healthchecks (~15 s).

### 3. Start the caproto sim IOC (separate terminal)

```bash
pixi run sim-iocs
```

The IOC serves **3248 PVs** on `127.0.0.1:5064`.

### 4. Launch the profile with sim stubs applied

```bash
pixi run sim-start
```

This opens an IPython session with:
- EPICS devices connecting to the local caproto IOC
- redis redirected to `localhost:6379` (TLS disabled — **sim only**)
- amostra and pyOlog stubbed as no-ops
- Xspress3 `roi_name` PVs pre-seeded

### 5. Run the acceptance tests

```bash
pixi run sim-test
```

Runs `sim/run_tests.py`, which exercises:
- Low-level CA connectivity (all device families)
- ophyd device connect
- `count([sclr], num=5)` — the existing acceptance test
- `scan([sclr], appes_x, 0, 1, 3)` — motor scan smoke test

### 6. Stop external services

```bash
pixi run sim-down
```

---

## pixi tasks reference

| Task | Description |
|---|---|
| `sim-up` | Start redis, kafka, zmq-proxy containers |
| `sim-down` | Stop and remove containers |
| `sim-iocs` | Start the caproto IOC (foreground) |
| `sim-list-pvs` | Print all 3248 served PV names |
| `sim-pv-types` | Print the PV inventory from ophyd device definitions |
| `sim-start` | Start IOC + launch IPython with stubs (convenience wrapper) |
| `sim-test` | Start IOC + run acceptance tests |

---

## File layout

```
sim/
├── __init__.py
├── pv_inventory.py          # get_pv_types(): full ophyd-derived PV set
├── run_iocs.py              # caproto server — assembles and serves all PVGroups
├── run_tests.py             # acceptance test suite
├── pvgroups/
│   ├── motors.py            # EpicsMotor records (47 motors)
│   ├── scaler_signals.py    # Scaler, standalone signals, valves, shutters
│   ├── positioners.py       # EPU, mirrors, PGM, Vortex MCA
│   └── detectors.py        # SPECS area detector, Xspress3
└── externals/
    ├── podman-compose.yml   # redis + bitnami/kafka + bluesky-0MQ-proxy
    ├── kafka.yml            # bluesky-kafka config → localhost:9092
    ├── catalog/
    │   └── config.yml       # local databroker catalog reference
    ├── stubs.py             # amostra/pyOlog/redis/kafka monkey-patches
    └── pre_exec.py          # IPython pre-exec: sets EPICS env + applies stubs
```

---

## EPICS environment variables

Set these before starting ophyd / the profile:

```bash
export EPICS_CA_ADDR_LIST=127.0.0.1
export EPICS_CA_AUTO_ADDR_LIST=NO
```

The `sim-iocs` task additionally sets:

```bash
export EPICS_CAS_AUTO_BEACON_ADDR_LIST=no
export EPICS_CAS_BEACON_ADDR_LIST=127.0.0.1
```

to suppress beacon broadcast errors on restricted networks.

Optional:

| Variable | Default | Effect |
|---|---|---|
| `IOS_SIM_CA_PORT` | `5064` | CA server port |
| `IOS_SIM_KAFKA` | `""` | Set to `1` to enable Kafka publishing |
| `IOS_SIM_LOG_LEVEL` | `WARNING` | Log level for `ios.sim` logger |

---

## Redis TLS override (WARNING)

> **WARNING:** The production profile uses `redis_ssl=True` against
> `xf23id2-ios-redis1.nsls2.bnl.gov:6380`.  The sim stack overrides this
> in `stubs.py` to `redis_ssl=False` / `host=localhost:6379` for the local
> plaintext redis container.  **Do not carry this override into production.**
> A `WARNING`-level log message is emitted at startup to make this visible.

---

## Adding a new device

1. Add its PVs to `sim/pv_inventory.py` (`build_inventory()`).
2. Add a caproto `PVGroup` in the appropriate `sim/pvgroups/*.py` file.
3. Register it in `sim/run_iocs.py` (`build_ioc_groups()`).
4. Run `pixi run sim-list-pvs` to confirm the new PVs appear.

If the device prefix contains `{...}` (EPICS ACF notation):
- Caproto uses `str.format()` on prefix strings, so `{` → `{{` and `}` → `}}`.
- If the prefix is "split" (e.g. `"XF:23ID-ID{EPU:1"` — the `{` is closed
  by the child suffix), use **absolute PV names** in `pvproperty(name=...)`
  and instantiate the group with `prefix=""`.  See `EPU1IOC` for an example.

---

## PV inventory

Run at any time to see the full set of PVs the profile connects to:

```bash
pixi run sim-pv-types
```

This calls `sim.pv_inventory.get_pv_types()` and prints a table of every
PV name and its ophyd type, grouped by device.

The same function is wired to the existing `pvs` pixi task (terminal env):

```bash
pixi run pvs   # requires the profile env, not just sim
```
