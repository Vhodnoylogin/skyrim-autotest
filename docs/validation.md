# Validation and scope

The extracted independent source passes 53 regression checks: original recovery,
PID reuse, ancestry and delayed-modal checks, plus explicit configuration,
external runtime policy, staging confinement, durable config recovery, portable
guardian imports, fixture validation before mutation, queue independence, bounded
physical publication, numeric assertions and typed post-step reference contracts.
No test in that suite launches Skyrim or SteamVR.

Fresh ZIP extraction and standard wheel installation passed 12 smoke checks
from an unrelated working directory and an isolated Python process, including
the full 53-test extracted suite. The native C++ lease harness also passed: a
complete frame survives a partial read and original expiry releases input.
Regression mutex tests use their own real Windows mutex namespace, so they
cannot contend with an independently running game test.

A clean external driver rebuild fetches 15 exact-commit SHA-256-pinned files and
the pinned OpenVR SDK header, with source/compiler/binary metadata. The known
incomplete full-history Git cache is retained; it is not needed by the builder.

`tools/build_distribution.py` emits ZIP/wheel/manifest outside Git. Use
`tools/check_distribution.py --distribution <output> --work <new external dir>`
to verify fresh extraction from an unrelated working directory, init overwrite
refusal, standard pip --no-index --no-deps wheel installation, isolated Python
imports/commands and the extracted regression suite. Installed/extracted copies
do not reference the original project path provider or journal ledger.

The predecessor support executor was qualified in a combined physical grip plus
reference/node observer session with 20 passed checks and 739 verified restoration
paths. That evidence establishes the inherited workflow, not fresh acceptance of
this packaged source. Record each independent live qualification separately,
including the exact distribution manifest, scenario, external fixture hashes,
driver build manifest, session result and restoration checks. Physics/contact
coverage depends on the separately installed data provider.

Known limits: no universal filesystem sandbox; additional mod writes require
extra_files declarations. Ordinary-radius and arbitrary controller controls are
not qualified by the enlarged-radius firewood probe. Direct DevBench input and
background OpenVR observations are not proof of physical scene input. Reliable
visual goldens require a registered capture provider. A frame command publication
has no driver ACK; tests must assert the actual game outcome. Runtime dependencies
are separately installed licensed third-party programs/mods, not bundled files.

Independent live recovery acceptance (2026-10-04): session
20261004-221841-eb9c93 deliberately exited after-ready with code99. The independent
guardian completed recovery; all738 snapshot paths were independently compared
with their pre-run state, with no restoration errors. Original fixture save
hashes were unchanged. Expected run result is failed, not a passing mod test.
This run stages no observer plugin; physics acceptance is separately qualified.

Upstream scope update: Devkit's author does not plan the full automation API.
The maintained adapter is now treated as our owned automation-backend candidate;
its qualification and prototype limitations remain unchanged by that decision.
See ownership.md for the credited provenance and exact author reply.

Retained combined-run failure: 20261004-222952-4157c4 failed at owned foreground
acquisition before physical/physics assertions; restoration completed. The
executor had made one SetForegroundWindow request and immediately checked the
result. Browser activity during bootstrap is a possible contributor, not an
established cause. The revised helper uses asynchronous owned-window restoration,
bounded settling/repeated requests, rechecks process/window identity, and may
briefly attach only the executor and its own game's threads, always detaching.
It never attaches to the foreign foreground application's queue, injects keys,
or changes global foreground policy. A positive API return alone is insufficient;
Windows' actual foreground PID must match the live owned process. Four mocked
regressions cover settling, denial/deadline, PID loss and detach-on-error.

API references: [SetForegroundWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow),
[ShowWindowAsync](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showwindowasync),
[AttachThreadInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-attachthreadinput).
Windows can still deny focus; the probe fails closed in that case.

Configuration isolation correction: the failed 222952 run also exposed recovery
activating a completed historical session's saved configuration before checking
`done`, replacing the caller's staged-plugin/token settings. That run therefore
is not observer/physics evidence. Recovery now skips completed records before
constructing sessions, freezes its original scan directory, restores abandoned
sessions under their durable environment, and restores the caller configuration
in `finally` including exception paths. Four regressions cover live-owner refusal, completed old
runs, multiple abandoned runs with a different runtime, and failed recovery.

Retained setup failure: 20261004-223713-06a43c failed before game launch because
initial input publication and heartbeat used the same temporary frame file
concurrently. Restoration completed for733 snapshots. The intended observer
staging configuration was preserved, but this is not physics evidence. Initial
frame selection/publication now holds Session.lock, matching heartbeat, generic
driver steps, built-in pose/release and cleanup. The hardware writer separately
serializes file transactions. Deterministic threaded regressions verify the
shared temporary file cannot race and an expired heartbeat cannot overwrite a
newly selected pressed frame.

Retained foreground failure: 20261004-224033-9d21d3 staged observer0.2 correctly,
but Windows denied all31 foreground requests even without concurrent browser
interaction. All739 snapshot paths restored without mismatches. Focus acquisition
is not qualified by the mocked tests alone. Read-only diagnostics found a
foreground ChatGPT window in the interactive Windows session, rather than a
locked/service desktop. The helper now records owned window handles/classes/titles,
actual foreground PID/thread and AttachThreadInput success/errors, and initializes
its message queue with PeekMessageW before an owned-thread attach attempt.

An explicit allowBackgroundVR option can empirically qualify the same physical
probe without treating focus as a mandatory assumption. It is restricted to the
physical backend, records each failed focus request, and preserves every existing
controller/world outcome assertion. It is not enabled by default; the later run
below qualifies this mode. Five regressions cover strict default failure, recorded
opt-in semantics, backend gating before mutation, and scenario option validation.

Background physical qualification and retained combined failures: session
20261004-224650-11b401 passed all14 unchanged physical hand/grip/hold/release
checks with both foreground requests denied. This positively qualifies physical
input in that explicit background mode, but the complete run failed later. Its
own cleanup verified739 restoration paths; a later comparison made during
another live session is not independent before/after evidence for this run.

Updated-distribution recovery fault225005-d96d1c: independent guardian reported
failed/done/restored, and738 paths were independently compared with zero errors;
source save-pair hashes were unchanged. The fault intentionally terminates the
executor after-ready; no assertion is made about the PTY wrapper exit code.

Corrected failure attribution for224650-11b401,225250-e074c8 and225925-02925d:
the physical probe itself called Disable/Delete on its fixture before postSteps.
The observer correctly reported the deleted/disabled reference and unavailable
physics; missing bodies cannot be attributed solely to a Get3D/body getter.
Run225925's739 restoration paths were independently verified with zero errors.

Fixture lifetime now spans postSteps: the copied session's spawned entity stays
live until owned game shutdown; there is no late Delete of a potentially reused
FormID after a reload. Default no-continuation cleanup remains, but checks its
reference lifetime first. Typed probeObject substitutions check the contiguous
DevBench lifecycle event stream and fail closed on load/new-game transitions,
event gaps, stream resets or an unreconciled racing head. Explicit world-changing
post-step requests invalidate the variable before mutation. The cursor is captured
before spawning and immediately reconciled after creation, so a concurrent load
cannot be adopted as the newly spawned reference's baseline. Eleven additional
regressions cover live continuation, immediate default cleanup, stale-ID refusal,
world-changing command classification and event cursor/gap/race behavior.
