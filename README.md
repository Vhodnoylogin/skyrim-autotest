# Skyrim Autotest

The `feature/se-morph-presets` branch contains the unqualified 0.3.8
[semantic preset/link adapter](docs/morph-presets.md). The native-tested SE
baseline remains the exact 0.3.7 configuration in [SE setup](docs/se-qualified.md).

Version0.3.7 prepares background activity only in the copied SE profile and waits
for native dataLoaded/Main Menu events before probing SKSE tasks. World readiness
and action assertions remain separate mandatory stages. Its exact SE configuration
completed the21-step native smoke on2026-10-26; this includes a separately staged
DevBench `alwaysActive:true` configuration. Read [qualified SE setup](docs/se-qualified.md)
for the tested build, repeatable setup and limits; the generated template alone
does not supply this configuration.

Version0.3.6 includes the exact [modern DevBench acquisition/build recipe](docs/devbench-modern-se.md)
for the SkyrimSE1.7.104 candidate and records its separate SDK configuration.
The provider passed offline compilation/tests and the later bounded SE smoke
described above; it is not bundled in the agent kit. Existing safety guards
from0.3.5 remain unchanged.

Version0.3.5 refuses owned-process shutdown when an unowned or unidentified game
is present, before stopping the shared VR runtime. It rechecks between shutdown
groups and releases only its own input first. The0.3.4 live attempt did not reach
DevBench readiness; no gameplay/data qualification is claimed. See
[validation and retained limits](docs/validation.md).

Version0.3.4 adds an explicit pinned Root Builder5.1.1 copy-mode lifecycle for
cold-owned VR launches. It validates the source SKSEVR bundle before deployment,
checks the actual deployed bundle and preserves Root-source/overwrite/cache
changes during restoration. See [Root Builder contract](docs/root-builder.md).
Typed assertions also validate actual returned JSON primitives and arrays.
Source tests do not establish live qualification of this new launch path.

Version0.3.3 adds the optional owned-session `native14` read: exact endpoint and
declared loaded-module checks, bounded fresh native samples, explicit load/body
transition comparisons and transactional evidence tags. See [live-read contract](docs/native14-live.md).
It does not attach to another runner or qualify a new platform without a game run.

Version0.3.2 adds [read-only native14 result validation](docs/native14.md), exact
uint64/IEEE preservation, mask-aware measurements and bounded haptic-request
history checks. `validate-native14` checks an already collected file without a
game/configuration; its success is not live platform or mod-test acceptance.

Version0.3.1 adds a separate **Skyrim SE** launch path, a reproducible narrow
DevBench1.32 compatibility build, and a vendor-neutral [AI-agent kit](agent-kit/START-HERE.md).
`review-plan` critiques declared behavior coverage and priority without claiming
whole-mod or executed coverage. See [current toolchain and qualification limits](docs/toolchain-refresh.md).

Planning includes selected tool-preparation time in the recommendation budget;
a plan with no selected subject behavior is explicitly incomplete.

This version also includes the previously prepared [generic disposable NPC photography candidate](docs/photography.md):
tagged actors, keyed morph readback, owned VR camera framing, original PNG custody,
paired metadata, complete shot index/contact sheet and restoration. Its native
readback builds offline; actual render/provider qualification is still required.
Do not treat these source capabilities as a ready photography platform.

A standalone Windows executor for bounded Skyrim SE and VR functional tests. It owns an
isolated MO2 profile, synthetic HMD/controller input for VR, result assertions and an
independent recovery process. No project journal, AI client, shell toolkit, or
Python third-party package is needed at runtime.

For headset-assisted chat sessions, the optional [voice delivery companion](docs/assisted-voice.md)
provides whole-utterance audio capture and a buffered private ASR inbox with
separate receipt, host delivery, first reply and completion records. Version0.2.0
keeps the legacy inbox explicit; see [voice v2 setup and qualification](docs/voice-v2.md).
The AI host must wake the operator chat; microphone health alone does not provide
continuous responses. This companion does not change automatic game execution.

Version0.2.2 provides [operator-owned voice setup and polling](docs/voice-operator.md):
Polygon uses the channel directly without an intermediary chat or per-phrase app
messages. Healthy existing listeners/cursors are preserved; new listener controls
open a bounded dialog after the owner's typed game-start statement. Fresh live
qualification of this new setup remains pending.

The independently extracted build passed a complete physical-input/world/physics
scenario and restoration verification on 2026-10-04. See [validation](docs/validation.md)
for the exact build, measured scope, retained failures and prototype limits.

The automation adapter is maintained here as our own backend. Devkit's author
has explained that a full automation API is outside that project's planned scope;
we do not assume this adapter will disappear after upstream changes. It remains
a versioned file protocol with exclusive owner tokens, monotonic leases and
driver component acknowledgements. Protocol v2 has native harness coverage;
its separate live-game qualification is still pending. See [ownership and credits](docs/ownership.md).

This is an external developer tool, not an SKSE mod. Skyrim World Observer is an
optional in-game data provider; install/stage it separately when a scenario uses
its `inspect` kind. DevBench provides the in-game tool transport. Devkit's AHK
frontend is optional and is not a serial prerequisite for this executor.

## Install and first configuration

Requires Windows and Python 3.11+. For a wheel:

```powershell
python -m pip install --no-deps ./skyrim_autotest-0.3.7-py3-none-any.whl
python -m skyrim_autotest init --directory C:/TestBench/config
```

For the flat game use `init --edition se --directory C:/TestBench/se`; the
default is `--edition vr`. Separate game targets need separate MO2/config/runtime
directories and Bridge ports. SE skips OpenVR acquisition/configuration and the
emulator. Follow [qualified SE setup](docs/se-qualified.md) before running SE:
the21-step smoke applies to the exact documented installation and provider.
Borrowed-profile, Root Builder and New Game UI paths remain explicitly unsupported.

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

The following physical-input installation applies to **VR**; SE uses the separate
path and boundaries described above and in docs/toolchain-refresh.md.

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

The optional candidate `reuse_test_profile` lifecycle keeps an already-open idle
MO2 and reuses a cached isolated profile within and between compatible series.
See [configuration](docs/configuration.md) for prerequisites, non-game validation
status and recovery limits. It is disabled by default pending live qualification.

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

Polygon's semantic subject interface can use the executor-local
[platform backend](docs/platform.md). Its mapping is a candidate, requiring
operator-reviewed live qualification; no mod order selects provider versions.

Generic scenarios use DevBench tools with explicit returned-state assertions.
`tool: "driver"` is routed to our owned physical adapter, not to DevBench input
injection. Full HMD/left/right frames have bounded leases, then buttons/axes are
released. Driver status returns a separate ACK tied to the exact owned VR
process, owner, command and publication sequence. It records pose submission
and successful component updates; game consumption and physical effects require
their own observations.
Healthy-run button/axis release is checked at one-second heartbeat intervals;
short leases do not guarantee exact short-pulse timing. Driver expiry after client
loss is five seconds. Protocol v2 uses the Windows boot clock for publication age
and a driver-local monotonic clock for expiry; replaying a file cannot renew it.
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

The common executor prepares initialized gameplay before dispatching any scenario:
recognized startup confirmation, optional pinned save load, declared initial cell
and verified scene/menu readiness. Orders describe the initial world via `cell`
and/or `fixture`; they do not script instrument-specific startup UI. Technical
`gameplay-ready` is distinct from factual subject-test start and results.

The recognized `CalibrationOptionMenu` in `VRPlayroom01` uses at most four
observed physical candidates: right/left Trigger, then right/left Grip. Each
candidate requires a fresh owned menu/scene check, releases in `finally`, and
waits for actual menu closure. One shared 20-second deadline bounds the sequence;
unknown dialogs, changed worlds and unrelated menus stop further input. Driver
acknowledgement is logged separately and never substitutes for closure/readiness.

The `vr-mobility-probe` diagnostic can run in a minimal Realm world without
VRIK/HIGGS: it records player movement/jump and game-accessed tracked hands,
separates physical-controller candidates from keyboard diagnostics, and attempts
vanilla inventory pickup only with an exact observed activation target. Optional
physical holding uses the existing HIGGS probe. See the scenario contract for
bounded inputs and honest unavailable/render domains.

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

The portable source also includes our native fixture integration and its
external-build recipes; the wheel provides the runtime clients and docs.
See [runtime fixtures](docs/runtime-fixtures.md) and
[effective subject state](docs/subject-state-provider.md) for the new opt-in
candidates and required live qualification. Structural support for a scenario
is not evidence that its gameplay assertions passed.

Fault injection is available only for deliberate recovery acceptance:
`run ... --fault after-setup`, `after-ready` or `while-held`. These runs are
expected to fail; guardian logs and verified restoration are their acceptance
criteria. They are not part of a normal mod test.

Reliable visual capture requires a registered DevBench capture provider. An
unavailable/black capture must never pass a visual test. Physics assertions need
an actual physics data provider and available quality/phase metadata; reference
or bone position alone does not prove a contact or a solver result.

## Development assistance

Developed with assistance from [Codex (OpenAI)](https://github.com/codex).
