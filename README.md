# Skyrim Autotest

A standalone Windows executor for bounded Skyrim VR functional tests. It owns an
isolated MO2 profile, synthetic HMD/controller input, result assertions and an
independent recovery process. No project journal, AI client, shell toolkit, or
Python third-party package is needed at runtime.

The automation adapter is maintained here as our own backend. Devkit's author
has explained that a full automation API is outside that project's planned scope;
we do not assume this adapter will disappear after upstream changes. It remains
a prototype file protocol: versioned ownership, sequence acknowledgements and
monotonic lease hardening are future interface work. See [ownership and credits](docs/ownership.md).

This is an external developer tool, not an SKSE mod. Skyrim World Observer is an
optional in-game data provider; install/stage it separately when a scenario uses
its `inspect` kind. DevBench provides the in-game tool transport. Devkit's AHK
frontend is optional and is not a serial prerequisite for this executor.

## Install and first configuration

Requires Windows and Python 3.11+. For a wheel:

```powershell
python -m pip install --no-deps ./skyrim_autotest-0.1.0-py3-none-any.whl
python -m skyrim_autotest init --directory C:/TestBench/config
```

Alternatively extract the portable ZIP and run its `run.py` by absolute path,
from any working directory. A Python interpreter must be installed; third-party
programs, interpreter binaries, driver binaries and game saves are not bundled.

```powershell
python C:/Tools/skyrim-autotest/run.py init --directory C:/TestBench/config
```

Edit the external `config.json` with your own installation paths. See
[configuration](docs/configuration.md), [scenario contract](docs/scenarios.md),
[dependency acquisition](dependencies.json) and the [AI-agent guide](AGENTS.md).
The generated physical-probe examples deliberately contain replacement fixture
names/hashes and cannot run until an authorized save pair is supplied. Calculate
SHA-256 of each `.ess` and `.skse` using your file tools, put their common stem and
hashes in the scenario, and point `fixture_dir` to their external directory.

Install licensed Skyrim VR 1.4.15, SKSEVR 2.0.12, MO2, Root Builder and DevBench.
Install MO2 API Bridge and register the SKSE loader in MO2 with the executable
name `SKSE`. The qualified physical probe also requires VRIK and HIGGS and their
ordinary dependencies. For data-only tests, use `required_mods: ["DevBench"]` plus
the dependencies of the subject mod. These directory names are configurable.
The runner currently expects exactly one stock `openvr_api.dll` in Root Builder's
Backup tree, and refuses separately registered external SteamVR drivers.

The emulator adapter is built from pinned external source, not copied into Git:

```powershell
python -m skyrim_autotest --config C:/TestBench/config/config.json config-check
python -m skyrim_autotest --config C:/TestBench/config/config.json build-driver
python -m skyrim_autotest --config C:/TestBench/config/config.json preflight --profile TestProfile --restart-idle-mo2
python -m skyrim_autotest --config C:/TestBench/config/config.json run --profile TestProfile --scenario C:/TestBench/config/vr-hand-probe.json --restart-idle-mo2
python -m skyrim_autotest --config C:/TestBench/config/config.json status
```

`build-driver` requires Visual Studio desktop C++ tools. It retrieves
only exact-commit, hash-pinned source files/SDK header to `runtime/dependencies`, applies our adapter, and records
compiler, source, protocol and binary hashes. Rebuild if that source changes.
Downloads are checked by digest; no mutable-main source is used for the driver.

## Session ownership and recovery

Preflight refuses a running game/VR session. `--restart-idle-mo2` authorizes a
restart only of the configured MO2 installation when it has no running children;
the original profile is restored and idle MO2 is reopened afterwards.
A shared Windows mutex excludes concurrent runners/recovery. Process ownership
requires executable path, creation time, PID and launch ancestry. No process is
killed solely by name or PID. PID reuse and later unrelated manual launches are
excluded from ownership.

File changes have durable backups before mutation, and restore verifies SHA-256.
Root Builder physical files, backup/build metadata, driver resources, SteamVR
settings, enabled-mod INI/TOML/JSON and declared extra files are covered. The
copied profile uses local saves/settings and disables autosave. Input is leased
and automatically released after client loss. The independent guardian watches
runner/game health and phase deadlines, then recovers if the executor dies.

The run contains a durable resolved configuration (paths only, no token value),
so the guardian does not depend on the original configuration file remaining.
Keep the installed package/distribution and the runtime directory until recovery
is complete. After a reboot use `recover`; a changed config must still point at
the original runtime directory:

```powershell
python -m skyrim_autotest --config C:/TestBench/config/config.json recover
```

Always check `restored:true` and `restoreErrors:[]` in `result.json`; `passed`
without successful restoration is not successful completion. Runtime logs,
backups, reports and credentials remain external and must not be committed.
This is not a universal filesystem sandbox: declare additional files that a mod
may overwrite before testing it. Do not install/edit mods concurrently with a run.

## Scenarios and orders

Generic scenarios use DevBench tools with explicit returned-state assertions.
`tool: "driver"` is routed to our owned physical adapter, not to DevBench input
injection. Full HMD/left/right frames have bounded leases, then buttons/axes are
released. A published frame is not an acknowledged frame or proof of game behavior.
Healthy-run button/axis release is checked at one-second heartbeat intervals;
short leases do not guarantee exact short-pulse timing. Driver expiry after client
loss is five seconds and uses wall clock in this prototype.
A test containing only frame-publication checks cannot pass.

The built-in `vr-hand-probe` enters QASmoke, verifies both hands, spawns dynamic
non-equippable firewood, calibrates an approach, and checks exact-reference HIGGS
grab, stable one-second hold, release and continued world presence. The larger
`NearCastRadius=0.5` is a temporary fixture setting, not general grip qualification.
Only the exact known one-button Speech Broker startup message may be dismissed;
unknown modals fail. Optional `postSteps` append ordinary declarative tests, with
`{"$state":"probeObject"}` inserting the exact spawned FormID. This reference
must not be reused after loading another world.

Observation-only steps do not become success assertions. Poll only supported
read-only inspection/status. Mutations are executed once, and whole scenarios
are never automatically retried to hide failure. Direct DevBench VR injection
is retained as `--input-backend devbench` for diagnostics; its hand motion is not
qualified physical HIGGS interaction. Optional `raw_openvr.py` observations are
application-specific and cannot attest the game's scene input.

```powershell
python -m skyrim_autotest --config C:/TestBench/config/config.json queue add --order C:/TestBench/orders/mod-test.json
python -m skyrim_autotest --config C:/TestBench/config/config.json queue next --restart-idle-mo2
python -m skyrim_autotest --config C:/TestBench/config/config.json queue list
python -m skyrim_autotest --config C:/TestBench/config/config.json queue reconcile
```

The queue is local with append-only `queue-events.jsonl` for external dashboards.
Its states are ordered -> running -> reported; explicit owner acceptance is
separate (`queue accept <id> --note <decision>`). Submission pins the scenario
hash, and changed scenarios require a new order. No journal or dashboard service
is required.

## Build and checks

```powershell
python -m unittest discover -s tests -p "test_*.py" -q
python tools/build_distribution.py --output C:/TestBench/distribution
```

The stdlib builder emits a portable ZIP, installable wheel and SHA-256 manifest
outside the checkout. Fresh extraction and wheel installation checks are in
[validation](docs/validation.md). Source contains no third-party binaries,
programs, archives, source headers, saves or tokens. `dependencies.json` records
how to reacquire dependencies and honestly leaves unknown hashes unset.

Fault injection is available only for deliberate recovery acceptance:
`run ... --fault after-setup`, `after-ready` or `while-held`. These runs are
expected to fail; guardian logs and verified restoration are their acceptance
criteria. They are not part of a normal mod test.

Reliable visual capture requires a registered DevBench capture provider. An
unavailable/black capture must never pass a visual test. Physics assertions need
an actual physics data provider and available quality/phase metadata; reference
or bone position alone does not prove a contact or a solver result.
