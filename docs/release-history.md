# Retained release history

These statements describe their original revisions. Current status: release-0.4.md.

Version0.3.10 uses a separately pinned DevBench native startup-menu interface for
the explicit SE New Game policy. It reads/selects/confirms the actual movie before
Papyrus VM initialization; the0.3.9 main-menu Papyrus read timed out in qualification.
Real native New Game and world readiness remain mandatory. Provider and executor
source tests do not establish live acceptance; see [session lifecycle](docs/se-session-lifecycle.md).

Version0.3.9 on this branch adds bounded read-only settlement of an
exiting owned process's stale inventory row, preserves the original guardian
recovery cause, and offers explicit SE New Game UI startup before an unchanged
cell-based subject. These changes need their own live qualification. Read
[session lifecycle and qualification](docs/se-session-lifecycle.md).

The branch also contains the unqualified 0.3.8
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
