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
| allow_background_physical_vr | Optional boolean, default false; semantic platform physical actions observe owned focus without requesting it and may proceed in background only with the owned file driver; native gameplay assertions remain mandatory |

Background permission applies only to semantic platform physical checkpoints.
Common startup UI still requires its normal owned foreground checks. This allows
an operator to read another app after world loading without repeated activation
requests. It does not prove the game consumes background input; qualify exact
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

`config-check` validates schema and path policy without launching programs. It
is not live dependency readiness. `preflight` checks actual configured binaries,
profile, busy processes, SteamVR input profile, Root Builder stock DLL and
selected mod configurations. Each run stores its resolved config for recovery.
Do not move runtime or installed code before recovery finishes.
