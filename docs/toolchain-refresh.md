# SE and VR toolchain review (2026-10-25)

| Component | Verified version/source | Role and limits |
|---|---|---|
| [DevBench](https://github.com/alandtse/devbench/releases/tag/v1.32.0) |1.32, commit938c392d5e0fc19260c65f689ff4a80fbec4007c|In-game REST/MCP engine operations, not a game launcher|
| [Skyrim Claude Code Toolkit](https://github.com/WingedGuardian/skyrimvr-claude-toolkit/releases/tag/v3.7) |3.7 requested baseline;3.9.1 separately inspected|Development environment/CLI and agent guidance; requires an already running game|
| [SkyrimVR Devkit](https://github.com/DubiousDuo/VR-Emulator-Driver---SkyrimVR-Devkit/releases/tag/Release_v2.0.1) |2.0.1, commit32ec30294a871683254b944b4129cbdec2591e6a|Keyboard/manual frontend and emulator diagnostics; not our unattended physical control protocol|
| Skyrim Autotest |0.3.0 source/offline candidate|Owns exclusive processes/profile, common bootstrap, actions, evidence and independent restoration|

DevBench1.32 retains GET `/api/tools`, GET `/api/health` and POST
`/api/tool/<name>` with raw argument/result objects. No new result wrapper is
needed. Its stdio bridge also does not launch Skyrim. New useful capabilities
include native always-active control with readback, form metadata, actor idle,
capture bursts and inline console output. They need capability discovery and
per-build qualification rather than version-only selection. Time-scale requests
must inspect reached/applied/state, or use `requireReached:true`.

Toolkit3.7 improves setup/hook paths and behavioral checks. Later3.9.1 improves
hook observation/timeouts/knowledge preservation. Neither supplies owned startup,
profile restoration or an independent guardian. Do not install its foreign AI
hooks as a side effect of obtaining the toolkit. Its shell runtime discovery is
less strict than our JSON/PID/frame discovery and can miss MO2 virtual paths.

## DevBench1.32 compatibility candidate

Stock1.32 does not expose the native per-menu states required by our readiness
predicate. Its scenario noBlockingMenu assertion has different, weaker semantics.
It also still pins an object-array pointer decoder that clears enum11 instead of
bit0, and strict JSON serialization can fail on invalid engine text. A responding
stock API is therefore insufficient for this executor.

The narrow owned recipe preserves upstream transport and adds:

- `menu.list(includeFlags:true)` with six independent native flags and explicit
  unavailable menu objects, read on the main thread;
- invalid-text diagnostics, preserving unavailable display fields rather than
  inventing replacement subject data;
- the one-bit CommonLib object-array decoder correction.

```powershell
python C:/Tools/skyrim-autotest/tools/build_devbench_current.py --build-dir C:/TestBuilds/devbench132
```

Use a new external build directory. Sources, SDKs, archives, compiler output and
all binaries stay outside Git. Exact pins/hashes are in the recipe and
dependencies.json. The existing older fork recipes remain historical candidates;
they do not build1.32. The new DLL still reports upstream1.32: identify our
candidate by build manifest/DLL hash, not that version string.

Offline qualification completed:314 native unit cases, eight real-library
decoder/alignment cases and an intentionally failing unpatched decoder control.
These checks do not prove a fresh game launch, arbitrary Papyrus introspection,
rendering, physics or every mod's behavior in either game. The executor verifies
native menu metadata before any world-changing bootstrap; unavailable support
is an explicit preparation failure.

## Separate startup paths

SE: MO2 → registered SKSE64 → owned SkyrimSE process → matching fresh DevBench
with advancing frames/task queue → native readiness contract → declared cell or
pinned save → stable playable world → subject checks. Compatible SKSE and Address
Library must match the actual executable; for1.7.104 the inspected sources list
SKSE2.3.1 and AddressLibraryv13. This target is an offline-tested candidate until
that complete installation is exercised in game. Root Builder, borrowed/reusable
MO2 and actual New Game UI transitions are deliberately refused for SE for now.

VR adds SteamVR/OpenVR, separate head/hand poses, physical buttons/axes and
calibration before the same world-ready boundary. The supplied2.0.1 archive is
the small AHK frontend, not the separate driver archive. Its stock driver shares
a pose and neutralizes grip/trigger/axes; replacing our driver with it would
remove necessary automation capabilities. Keep the exact owned physical backend
pins. The calibration frame now sends supported touch bits only. Lease/ACK
success still requires actual menu closure and world/physical readback.

Real-headset assisted testing uses the owner's hardware and operator-owned voice
channel. It is distinct from unattended emulated VR; neither mode is permission
to appropriate a running manual session.

## High-value test planning

Use the kit's case inventory and `review-plan` before creating subject scenarios.
Cover common user flows, independent major variants and persistence. Include a
minimal check for catastrophic data loss even when rare. Give weights a concrete
usage/impact rationale and challenge them against the mod design. A greedy
coverage-per-minute recommendation is planning advice, not an optimality proof.
Do not multiply assertions merely to improve a percentage. Capture/contact tests
need real providers; images and bone positions cannot establish physical contact.

Report both planned count/weighted coverage over the declared inventory and
actual executed coverage after the run. Whole-mod coverage remains unknown when
there is no measured denominator. The plan reviewer never launches the game,
claims a passing mod test or authorizes new attempts.
