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

## Keeping the sim in sync

The sim IOC is a parallel representation of the real profile devices.  It
will drift whenever `startup/*.py` devices change.  A dedicated script
detects and reports this drift automatically.

### Drift detection (run this after any device change)

```bash
pixi run sim-check-drift
```

This runs `sim/check_drift.py`, which:

1. **Loads the real profile devices offline** — executes the device-defining
   `startup/*.py` files in an isolated namespace without connecting to EPICS
   or any external service, then walks every ophyd Device/Signal object to
   collect the authoritative PV set.
2. **Loads the sim IOC PV set** — introspects `build_ioc_groups()` without
   starting a server.
3. **Compares and reports:**

| Severity | Condition | Action needed |
|---|---|---|
| **FAIL** | Profile needs a PV the sim doesn't serve | Add a caproto PVGroup (see below) |
| **FAIL** | A device file failed to load | Fix the stub namespace in `check_drift.py` |
| WARN | Sim serves a PV no device requests | May be dead; consider removing |
| WARN | `pv_inventory.py` diverges from the live walk | Run `--write` (see below) |

Exit code: `0` if no FAILs, `1` if any FAIL (use `--strict` to also exit `1` on WARNs).

### Typical workflow after changing a device

```bash
# 1. Edit startup/10-optics.py (or whichever file)
# 2. Run the drift check — it tells you exactly what's missing
pixi run sim-check-drift

# 3. Add the missing PVs to sim/pvgroups/<file>.py and register in run_iocs.py
# 4. Regenerate the hand-written inventory to match the new device walk
pixi run sim-write-inventory          # runs check_drift.py --write
git diff sim/pv_inventory.py          # review the generated changes

# 5. Confirm clean
pixi run sim-check-drift
```

### What `--write` does (and doesn't do)

`pixi run sim-write-inventory` regenerates the `build_inventory()` function
in `sim/pv_inventory.py` from the live device walk.  This keeps the
hand-written inventory in step with reality so `get_pv_types()` stays
accurate.

It does **not** write caproto PVGroups — those require behavioral logic
(putters, move simulation, enum strings) that a generator can't supply.
The drift check tells you *which* device needs a new PVGroup and *which*
PVs are missing; writing the PVGroup remains a human task.

### Adding a new device

When adding a new device to `startup/*.py`:

1. Run `pixi run sim-check-drift` — it names the device and lists its missing PVs.
2. Add a caproto `PVGroup` in the appropriate `sim/pvgroups/*.py` file.
3. Register it in `sim/run_iocs.py` (`build_ioc_groups()`).
4. Run `pixi run sim-list-pvs` to confirm the new PVs appear.
5. Run `pixi run sim-write-inventory` to update `pv_inventory.py`.
6. Run `pixi run sim-check-drift` again to confirm clean.

If the device prefix contains `{...}` (EPICS ACF notation):
- Caproto uses `str.format()` on prefix strings, so `{` → `{{` and `}` → `}}`.
- If the prefix is "split" (e.g. `"XF:23ID-ID{EPU:1"` — the `{` is closed
  by the child suffix), use **absolute PV names** in `pvproperty(name=...)`
  and instantiate the group with `prefix=""`.  See `EPU1IOC` for an example.

### CI drift checking

The GitHub Actions workflow runs two jobs on every PR touching `sim/**` or
`startup/**`:

- **drift-check** (fast, no live IOC): runs `check_drift.py --json --strict`
  and fails the build if any profile PV is missing from the sim.
- **integration** (live IOC + acceptance tests): starts the caproto IOC and
  runs `sim/run_tests.py` for end-to-end verification.

A PR that adds a new device to `startup/*.py` **must** also add the
corresponding sim PVGroup, or the drift-check CI job will block it.

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
