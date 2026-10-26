# Configuration contract (schemaVersion 1)

Optional `native14_live` pins the actual modules/expected absence and freshness
policy for executor-local read-only native14 steps. It is VR-only and requires
separate live qualification; see [owned native14 reads](native14-live.md).

Optional `root_builder` and `root_builder_data` select the explicitly pinned VR
Root Builder copy-mode lifecycle. The loader may be absent in the physical game
root before MO2 autobuild, but its exact enabled source bundle must be present.
Borrowed/reusable MO2 and SE are not admitted in this mode. See
[Root Builder planning and restoration](root-builder.md). Without this policy,
the legacy physical game-root loader requirement remains in force.

`game_edition` is `vr` (legacy default) or `se`. Generate separate templates with
`init --edition vr|se`; use separate external runtimes and MO2 installations. SE
requires `SkyrimSE.exe`, `skse64_loader.exe`, a registered SKSE entry with that
exact loader/game working directory and no hidden arguments. No `openvr_paths`,
SteamVR, VRIK or HIGGS are required for data-only SE tests. Runtime discovery uses
the `devbench/se` mirror instead of `devbench/vr`; explicit runtime paths win.
SE preflight rejects Root Builder installations/root mods, borrowed/reusable MO2
profiles and VR-control configuration until those combinations are qualified.
SE New Game UI is not part of the qualified baseline. The0.3.9 candidate offers
explicit `se_new_game_ui:true` in the separate platform configuration for a fresh
cell-based subject, without rewriting its order. It cannot replace a pinned save.
This opt-in needs separate qualification of actual UI/native lifecycle, gameplay,
subject API admission and normal teardown; see [session lifecycle](se-session-lifecycle.md).
The legacy default cell route is unchanged and does not prove New Game initialization.

For the exact live-tested SE setup, including the required separately staged
DevBench `alwaysActive:true` configuration, read [qualified SE setup](se-qualified.md).
`init --edition se` creates a path template and does not create that provider
configuration or install its dependencies.

SE preparation sets `General/bAlwaysActive=1` in `Skyrim.ini` and
`SkyrimCustom.ini` of the owned copied profile, retaining before/after hashes.
The source profile remains unchanged and the copied files follow normal archive
and removal. These INI values alone did not make the first0.3.7 SE candidate
complete its task probes. The successful configuration also staged DevBench's
`alwaysActive:true` setting and verified its effective native readback; do not
infer successful background execution from an INI write alone. Before the first
SKSE task probe, the executor waits on the independent
native event stream for contiguous `dataLoaded` and an open `Main Menu`, checking
the owned process identity. Event gaps, resets, unexpected world transitions and
late responses refuse admission. This startup admission is not world readiness;
the task, menu, world and scenario checks still run afterward.

The optional tool-owned `boundary_collection` plan records supplementary semantic
reads at exact, reviewed settled main-scenario boundaries. It defaults to absent
and needs its own live qualification. See [boundary collection](boundary-collection.md)
for the strict pin/anchor schema, deadlines, raw evidence and availability limits.

The executor records an identity-bound `heartbeat.json` separately from the
main run state, including only health and locked process/input recovery data.
The guardian validates that pulse against the exact run and runner identity;
stale, mismatched or malformed pulses cannot extend its deadline. Recovery
preserves late owned-process discoveries and newer input state without replacing
newer durable main-thread data. `result.json` includes `heartbeatHealth`; a
failed or non-stopping monitor makes the technical result fail even when game
checks and file restoration succeeded. Heartbeat health is not gameplay readiness.

Cleanup releases its own synthetic input, then checks current game/loader
identities before quitting any owned process. An unidentified, reused or unowned
game PID prevents shutdown, including shutdown of the owned shared SteamVR
runtime. Checks repeat between role groups and before individual close/terminate
requests. This is sampled observation, not an atomic exclusion of later manual
launches. It never adopts a Steam-created game merely because path/time matches.
The exact refusal remains in state/logs; ordinary recovery must wait for the
foreign session to end rather than closing it or altering live files under it.

Optional `allow_steam_client_restart: true` requires an explicit `steam_exe` path.
It authorizes one graceful `steam.exe -shutdown` only if the exact preflight
client is still alive, holds our staged null-driver module, its executable and
driver/backup hashes match, and current process ancestry plus Steam running-app
registry hints show no game/VR or non-helper descendant. The client is never
added to owned processes or force-terminated. Unknown identities, unavailable
inspection or a shutdown timeout block restoration. Durable shutdown/reopen
intents are not replayed after an interruption. After verified file restoration,
the executor reopens the matching client with `-silent` and records its new
identity; this proves presence, not application readiness or ownership. The
process/registry inventory is sampled, not an atomic exclusion of later manual
launches. Disabled by default; the exact opt-in configuration requires live
qualification. Missing Steam registry observations fail conservatively.

A Steam process-list row may disappear before its executable identity is read
during graceful exit. The executor resamples the complete client inventory up to
three times,50ms apart. Only a fresh inventory establishes absence. A persistent
unidentified row, different executable or multiple clients still blocks cleanup;
this never replays shutdown or authorizes killing a process.
After a shutdown/reopen request is durably issued, unavailable identities remain
explicitly unknown and may be reobserved within that same45/25second wait window.
They never establish absence or extend the window; foreign identities still stop.

The opt-in path observes the exact client's modules for up to eight seconds,
allowing its delayed post-VR watchdog startup before deciding a restart is
unnecessary. A later Win32 sharing violation on this exact staged driver permits
one file-restoration retry only after the same guarded graceful shutdown is
observed. The original sharing error remains logged; unrelated file failures,
unobserved modules and repeated retries remain blockers.

Configuration is a JSON object supplied using `--config`. Relative paths resolve
against the config file's directory, never the working directory. Unknown fields
are rejected. No path value includes credentials; only `bridge_token` names a
file whose content is read immediately before an authenticated request.

| Field | Meaning |
|---|---|
| runtime | External writable backups/dependencies/queue/results root; outside Git and live MO2/game directories |
| mo2 | Installation folder |
| mo2_exe / mo2_ini | Optional explicit overrides; otherwise ModOrganizer.exe / ModOrganizer.ini in mo2 |
| game | Skyrim VR installation root |
| mods / profiles / overwrite | Explicit MO2 instance directories |
| bridge_token | MO2 API Bridge token file path |
| bridge_port | Local API port, default 8930, integer 1..65535 |
| openvr_paths | Actual openvrpaths.vrpath file, used to discover runtime/config/logs |
| skse_logs | External SKSE log directory |
| fixture_dir | Optional external authorized save-pair directory; if absent/null use selected source profile's saves |
| required_mods | Nonempty exact MO2 directory names; default DevBench, VRIK Player Avatar and HIGGS - Enhanced VR Interaction |
| extra_files | Explicit paths to regular files that may change; existence/content snapshotted before launch |
| collected_files | Optional explicit subset of extra_files to capture before restoration; each file is required, at most64MiB, and hash-pinned in evidence; defaults to empty |
| staged_plugins | External source files staged into MO2 overwrite before launch, with source/destination/sha256 |
| root_builder / root_builder_data | Optional audited copy-5.1.1 policy and exact existing game/version cache directory; see root-builder.md |
| devbench_runtime_files | Optional discovery file override list; default LOCALAPPDATA/devbench/vr/runtime.json and overwrite/SKSE/Plugins/devbench/runtime.json |
| controller_start_positions_metres | Optional platform-owned left/right tracking translations, three finite metre values each within [-2,2]; open-hand pose applied once after common gameplay readiness and before subject actions |
| reuse_test_profile | Optional boolean, default false; candidate lifecycle requiring an already-open idle MO2 with session-bound native Bridge selection; reuse an owned archived profile across compatible runs/series |
| allow_background_physical_vr | Optional boolean, default false; semantic platform physical actions observe owned focus without requesting it and may proceed in background only with the owned file driver; native gameplay assertions remain mandatory |

Background permission applies only to semantic platform physical checkpoints.
Startup operations that send desktop keyboard/mouse input retain owned foreground
checks. Identified character creation uses native Papyrus/UI and menu calls without
requiring desktop foreground, and still verifies confirmation, name readback, actual
menu closure and gameplay readiness. This allows an operator to read another app
without making native character completion depend on Windows activation requests.
It does not prove the game consumes background input; qualify exact
hand acquisition, hold and release in the actual session. No background keyboard
or UI automation is authorized by this option.

The optional controller start pose is explicit fixture preparation in the frozen
platform configuration, not a subject-order action or a larger reach allowance.
It requires the owned file driver; defaults remain unchanged. The executor logs
its publication without claiming consumed/gameplay state. A later bounded reach
starts at this recorded initial pose and keeps its original maximum displacement.
Qualify the configuration and actual measured hand behavior; never change it mid-run.

A staged plugin is `{ "source": "C:/Build/WorldObserver.dll", "destination":
"SKSE/Plugins/WorldObserver.dll", "sha256": "<64 lower-case hex digits>" }`.
Destination must be relative and remain under overwrite; existing files are
backed up/restored, new files removed. Source hashes are verified before setup
and again at staging. Include the mod's configuration/output files in extra_files
when they are not already captured under enabled mod directories.

`extra_files` protects restoration; it does not publish file contents. Select
non-private runtime outputs explicitly through `collected_files` when the report
needs their full bytes. Missing, linked, changing or oversized selected files make
collection incomplete. Collection faults do not skip safe restoration: result/state
retain `collectionComplete:false` and `collectionErrors` separately from `restored`
and `restoreErrors`. Such a run is failed technical collection, never successful
subject evidence. SteamVR/Bridge logs and pre-restart artifact copies are also
declared in the flat hash manifest consumed by Polygon. Old packets remain unchanged.

For unattended crash collection, stage a pinned copy of the actual winning
`SKSE/Plugins/CrashLogger.ini` with `[Debug] Auto Open Crash Log = false`.
Crash Logger otherwise opens its default viewer after a crash; that child can
keep MO2's virtualized launch chain alive. Preserve every other setting and keep
the generated copy outside Git. The ordinary `staged_plugins` mechanism also
accepts this INI destination: it backs up the existing overwrite file, stages the
verified copy before launch, and restores its original content afterward. Logs
remain enabled and collected; do not solve this by terminating an unrelated
editor or disabling the logger. Record crash-spawned viewer identity/ancestry
when reviewing a blocked historical session.

`config-check` validates schema and path policy without launching programs. It
is not live dependency readiness. `preflight` checks actual configured binaries,
profile, busy processes, SteamVR input profile, Root Builder stock DLL and
selected mod configurations. Each run stores its resolved config for recovery.
Do not move runtime or installed code before recovery finishes.

## Candidate reusable profile lifecycle

`reuse_test_profile: true` keeps the exact preflight MO2 process open. It requires
Bridge `/session` and native `/profiles/select`; process path/birth, boot, instance,
profiles directory and selected profile are verified. No `selected_profile` disk
write occurs while MO2 is alive. An explicit restart flag does not override this
mode. The current source path is covered by non-game tests, not live qualification.
Keep existing qualified platform configurations unchanged until Polygon qualifies
this candidate outside any active attempt.

The inactive working profile is keyed by source path and hashes of its top-level
files. Saves are reset independently from the pinned fixture. Settings and lists
are reset from the source before each attempt, with local saves/settings and
no-autosave preparation retained. The original profile's saves are never copied
into the working save directory. Changes in source composition/settings select a
new compatibility key; old archived copies remain available as evidence.

At run completion the executor switches back through Bridge, verifies idle MO2,
restores per-run file snapshots, copies working-profile evidence into the run and
moves the same working profile outside MO2 into `runtime/reusable-profiles`.
The next compatible attempt moves that directory back, checks archive integrity
and resets saves/settings without constructing another profile. An interrupted
lease blocks reuse until the owning run is recovered. This applies across series;
profile lifecycle itself grants or revokes no launch authority.

If the borrowed MO2 exits or its Bridge boot changes, or the owner selects an
unrelated profile, automatic recovery stops with retained backups instead of
writing settings under an unknown instance. Recovery of that boundary is not yet
automated. Activation-hand startup selftest fixtures are unsupported in this
candidate. It is not a replacement for all existing recovery qualification.

Restoration waits up to30seconds for the verified borrowed MO2/Root Builder busy
status to clear after owned game exit. Each wait iteration rechecks process and
Bridge identity; a new game/VR process or identity failure stops recovery. Busy
responses remain logged as `bridge-restoration-idle-wait`; profile selection is
issued only once after an idle read. Setup continues to refuse a busy MO2 without
waiting. The first live reuse candidate exposed an immediate-busy cleanup failure;
its independent guardian subsequently restored the original profile/files. That
historical normal failure remains a failed qualification, not a retroactive pass.

Candidate allow_owned_save_load (boolean, default off) enables only attempt-owned
save/load actions. It sets absolute sLocalSavePath in the copied profile before
launch and validates the loaded native setting before any save or load. Generated
ESS/SKSE files stay in that disposable profile and its evidence archive. Require
an exact live qualification of the opt-in configuration; it does not enable
process restart or access to owner saves.

Additional opt-in candidates are `native_runtime_fixtures:true` and
`subject_state_bindings`. Read docs/runtime-fixtures.md and
docs/subject-state-provider.md before configuring/qualifying them. A read-only
binding maps a stable subject name to `inspectKind`; owned settings variants also
require exact overwrite-relative JSON/INI destinations, an allowed private
profile INI name and an external immutable slot-baseline path/SHA256. Configuration
automatically snapshots the declared overwrite targets and temporary files.
Never point the baseline at mutable mods/profiles/overwrite or edit installed
subject files during a run. Bytes written and native settings observed are
separate evidence. Collection pins every owned variant before restoration.
These capabilities do not install their providers, release orders or grant
launch authority. They remain pending live qualification in the paused setup.
