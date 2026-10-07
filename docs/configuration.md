# Configuration contract (schemaVersion 1)

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
| staged_plugins | External source files staged into MO2 overwrite before launch, with source/destination/sha256 |
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
