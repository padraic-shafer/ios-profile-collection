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

The IOC serves about **3600 PVs** on `127.0.0.1:5064` (`IOS_SIM_CA_PORT` changes the port).

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
- the Xspress3: stage, trigger, read, ROI totals that follow the ROI windows, and the file of the run

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
│   ├── beam.py              # the simulated beam: intensity over time, TEY peaks and PD dips
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

## The simulated beam and scaler

`sim/pvgroups/beam.py` gives the scaler and the Xspress3 a beam that changes with time, so that live plots
move. The relative intensity is 1 plus a 2 % oscillation (period about 97 s), a 0.6 % one (13 s) and a 1 %
drift (10 min). Scaler channel 3 (I0, the gold mesh), channel 2 (PD, the photodiode) and channel 4 (TEY, the
drain current of the sample) are Poisson counts of a rate times that intensity, times the count time, so PD/I0
(0.75) and TEY/I0 (0.6) are flat apart from noise; the Xspress3 spectrum follows the same intensity. The other
scaler channels are random, as before.

TEY has now and then a peak, a Gaussian in time whose top is 2 to 7 times the background, so that TEY/I0 runs
from the flat level to 2 to 7 times it. At the same moment PD dips, 10 to 80 % below its background (the
deeper the dip, the higher the peak): a stronger absorption raises the drain current and lowers the
transmission. Events never overlap and come at random with a mean gap of 30 s and a width (FWHM) of 6 s, so
that they are visible within a minute of watching. They run while the mono is **not** flying (the Counter, or
nothing running). While the mono flies, a scan has an **absorption edge** instead (the event schedule for a
scan, `IOS_SIM_PEAK_GAP_SCAN`, is off by default):

- **Where:** a fraction of the fly range from its low end (40 % by default; `IOS_SIM_EDGE_FRACTION`), or with
  `IOS_SIM_EDGE_TABLE=1` the lowest real edge energy of a small table (`REAL_EDGES` in `beam.py`: C, N, O K edges,
  3d metal L3 edges, Mg and Al K edges) that lies inside the range, at least 10 % from its ends. With no edge in the
  range it falls back to the fraction.
- **Shape:** a step (an error function, width 3 % of the range, at least 0.2 eV; `IOS_SIM_EDGE_WIDTH` sets it in
  eV) with a small white line just above it. The mono's energy readback is the energy; the same absorption is
  seen four ways:

| Signal | At the edge | Factor at full absorption (a = 1) |
| --- | --- | --- |
| PD (transmission), so PD/I0 | falls | exp(-0.9 a) |
| TEY, so TEY/I0 | rises | 1 + 2 a |
| Xspress3 ROI 4 (the resonant line, PFY) | rises | 1 + 3 a |
| Xspress3 ROI 3 (the non-resonant line) | dips, so IPFY = I0/ROI 3 rises | 1/(1 + 1.5 a) |

The edge applies only while the mono flies and ends with the fly, so the Counter afterwards is flat again,
apart from its events.

A count that a client starts (a put to `.CNT`) takes the preset time (`.TP`): the record says `Count`, the channels are
filled at the end, and the put completes then, as on a real scaler record. ophyd's trigger finishes on that put
completion, so a plan's point takes at least `.TP` (1 s by default, the dwell time once Apply sets it): a PD Scan
has one point per `.TP`, and a Single Scan one per the longer of `.TP` and the Xspress3 acquisition. (The scaler used
to finish at once, which gave a PD Scan about 40 points a second.)

The scaler starts in AutoCount (`.CONT` = 1), like the real one: every `.TP1` seconds (1 s) it counts by
itself, except while a count that `.CNT` started is running or the mono is flying.

Settings (environment): `IOS_SIM_SEED` (an integer; the default is the time at the start, logged by the IOC),
`IOS_SIM_PEAK_GAP_IDLE` and `IOS_SIM_PEAK_FWHM_IDLE` (30, 6 s), `IOS_SIM_PEAK_GAP_SCAN` and
`IOS_SIM_PEAK_FWHM_SCAN` (0, 100 s); a gap of 0 or less switches that schedule's events off;
`IOS_SIM_EDGE_FRACTION` (0.4), `IOS_SIM_EDGE_WIDTH` (0, which means 3 % of the range) and `IOS_SIM_EDGE_TABLE` (0). The tests are
`acceptance_tests/test_sim_beam.py` (`pixi run -e qs-sim python acceptance_tests/test_sim_beam.py`).

## The simulated Xspress3

`sim/pvgroups/xspress3.py`. The PV names are **read from the ophyd class that the profile builds**
(`build_xspress3_class` of nslsii, as in `startup/22-xspress3.py`), so the IOC serves exactly the PVs the
installed nslsii asks for (`MCA1ROI:n:Name`, `MCA1ROI:n:MinX`, `C1SCA:n:Value_RBV`, the `HDF1:` plugin ...).
The type of each PV is guessed from its name and component.

- Setpoints with a `_RBV` readback follow it.
- `det1:Acquire` = 1 holds `Acquire` and `Acquire_RBV` at 1 for `AcquireTime` (at most 0.5 s), then fills
  `MCA1:ArrayData` and `MCASUM1:ArrayData` with a simulated spectrum (a background and lines at bins 450 and
  820, scaled with the time), sets each ROI total to the sum over `[MinX, MinX + SizeX)`, counts the image and
  drops both back to 0.
- **Put completion.** As on an areaDetector IOC, a put to `Acquire` completes when the acquisition has ended, not at
  once (`IOS_SIM_XS3_PUT_COMPLETION=0` switches it off). A client that waits for put completion therefore does not
  depend on seeing the readback go to 1 and back to 0, which a Channel Access monitor does not promise (a busy client
  can miss a 1 that lasts 0.1 s). nslsii's `Xspress3Trigger` does not wait for it; the mock Queueserver's startup file
  `sim/qs/zz-xs3-trigger.py` (`sim/qs/xs3_trigger.py`) makes its write use put completion (and switches off nslsii's readback-edge callback, which raced with it) and also lets a trigger finish
  on the image counter after a 0.5 s grace (`IOS_SIM_XS3_TRIGGER`: `put+counter`, the default, `put`, `counter` or
  `edge`, nslsii's own, for comparisons). Without it, scans stalled when the client missed the 1.
- `HDF1:Capture` = 1 makes the file that the plugin names a **symbolic link to one shared simulated file**,
  `$IOS_SIM_DATA_DIR/.shared/xspress3-sim.h5` (written when the IOC starts: `IOS_SIM_XS3_FRAMES` frames,
  20000 by default, of the same spectrum; about 3 MB). Every image of every run is that spectrum.
  `entry/instrument/detector/data` has shape `(frames, 1, 4096)`, as the `XSP3` handler reads it.
- The IOC writes only below `IOS_SIM_DATA_DIR` (default `/tmp/ios-sim-data`); a file path outside it is
  reported as missing (`FilePathExists_RBV` = 0) and nothing is written, so that a profile that still points at
  `/nsls2/data/ios/legacy/xspress3_data` cannot create files there.

The mono fly (`Cmd:FlyStart-Cmd.PROC`) moves the energy readback from the start to the stop energy at the fly
velocity and reports `Scanning` and then `Ready` (`IOS_SIM_FLY_SPEEDUP` shortens it), so `E_ramp` runs. A new energy setpoint (`Enrgy-SP`, which `E_ramp`'s clean-up writes after a scan, also after a stop) or the stop command ends the fly at once, where it is, as on the mono; the scanning state of the beam model, and with it the edge, ends with it.

## PVs that are not simulated: the fallback

`IOS_SIM_FALLBACK=1` makes the IOC answer for **every PV name that no PVGroup serves**, with a plain value
(0.0, or a string for names that look like text), and log each fabricated name once. It is for a mock
Queueserver that must load the whole profile although the simulation does not cover every PV yet (see the
drift check for the gaps: the Vortex, the SPECS and a few valves). It is off by default. Fabricated PVs have
no behaviour: a run that depends on one is not tested.

## Mock Queueserver (`sim/qs/`)

A Queueserver against these IOCs, for developing and testing the XAS experiment model without risk to
equipment or people (`pixi install --environment qs-sim`).

```bash
sim/qs/run-local.sh /tmp/ios-mock-qs          # redis, IOC, RE Manager, HTTP server; Ctrl-C stops
python sim/qs/smoke.py --api-key KEY \
    --documents /tmp/ios-mock-qs/documents.jsonl --data-dir /tmp/ios-mock-qs/xspress3_data
```

Everything is on `127.0.0.1` on non-default ports (Channel Access 5864). The pieces:

- `sim/qs/guard.py` (run first, as `00-00-sim-guard.py`): confines Channel Access and PV Access to
  `127.0.0.1` and refuses to load the profile unless the sentinel PV `IOS-SIM:Sentinel`, which only this IOC
  serves, answers.
- `sim/qs/make_startup_dir.py`: a startup directory of links to the profile's numbered files (except
  `47-IOS_gui.py`), the guard first and `zz-sim-paths.py` last (it points the Xspress3 files at
  `IOS_SIM_DATA_DIR`), and `user_group_permissions.yaml`: the group may run `xas_edge_ascan`, `xas_pd_ascan`,
  `XAS_scan`, `PD_scan`, `find_sample`, `count` and `mv`.
- `sim/qs/smoke.py`: queues `xas_edge_ascan` and `xas_pd_ascan` items with `meta.xas`, checks that both
  complete, that the start documents carry `meta.xas`, that a plan outside the list is refused, and that each
  run's Xspress3 file is a link to the shared one.
- The stubs keep the run metadata (`RE.md`) in the Queueserver's redis under a prefix
  (`IOS_SIM_REDIS_PREFIX`): without it a queue (a redis list) makes every run fail with `WRONGTYPE`. If
  `IOS_SIM_DOC_LOG` is set, the worker appends every start and stop document to that file.
- Deployment: the Ansible role `skybeam_mock_queueserver` (NSLS2/ansible).

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

### Checking a happi database against the profile

The ophyd-service configuration service loads a happi database (`integration/happi/sites/ios` and,
for the simulation, `sites/ios-sim`). `sim/check_happi.py` compares it with the profile: PV sets per
device, and the PVs of the database that the simulated IOC does not serve. The profile wins where
they differ. It changes nothing.

```bash
pixi run -e qs-sim python sim/check_happi.py --happi PATH/TO/happi_db.json
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
