# Acquire the direct startup UI compatibility candidate

Current retained native status: exact executor0.3.10/provider5068162 and DLL
89309425 passed Q4 actual New Game,27declared+1readiness checks and normal
restoration on26October2026. This is the measured composition only. The current
release/setup contract is in release-0.4.md; old candidate claims below retain
their original temporal scope.

The explicit SE New Game path in0.3.10 requires `devbench-startup-ui/1`.
This is a native main-menu interface on the fenced SKSE UI task queue, not Papyrus UI.GetString before VM startup.
It is not part of stock DevBench1.32; do not infer it from a version string.

Obtain the owner compatibility fork at
[5068162637dc2b5621b7224b8eded76a0c9e3d4f](https://github.com/Vhodnoylogin/devbench/commit/5068162637dc2b5621b7224b8eded76a0c9e3d4f),
branch `fix/native-startup-ui`. Follow the external acquisition/build instructions
and exact flags in [the modern SE recipe](devbench-modern-se.md), selecting this
commit instead of3bb1673. Retain its modern CommonLib gitlink0c95630 and OpenVR
60eb187; do not replace the SDK with an old VR archive or unrelated prebuilt library.
Build/run devbench-tests and build devbench externally. The observed candidate
passed316native cases and compilation; neither is actual main-menu qualification.

Observed candidate DLL SHA256:
`8930942502a5f75d9f0c03586cd067af37373eef60f93ac656dcf8a836abf3ec`.
Rebuilding can change artifact hashes; record the actual DLL/PDB/build logs and
dependency lock. Stage the exact DLL through the normal operator-owned
`staged_plugins` snapshot/restoration mechanism, without editing installed third-party
mod files or bundling the DLL into this repo/agent kit. Keep previous provider
artifacts and failed native packets unchanged.

`menu` action `startup` takes `startupOperation` snapshot/select-new/confirm-new.
The runtime adapter verifies the actual contract and typed state, invokes each
mutation once, and still requires real SKSE newGame and settled gameplay. It has
no Papyrus fallback and does not replay uncertain invocation timeouts. Unknown
dialogs and incompatible/replaced movies retain their refusal. Full startup,
character completion, subject API admission and normal teardown remain separate
live qualification requirements; see [session lifecycle](se-session-lifecycle.md).

Startup snapshots use the common read-only abandonment policy within the original
20-second main-state / 10-second confirmation-state deadlines. Only the exact
`menu {action: startup, startupOperation: snapshot}` request can be repeated when
the pinned producer proves it was abandoned before starting. Every failure and
retry is retained. A started/uncertain request, transport loss, other HTTP504 or
unknown menu remains terminal; NEW selection and confirmation are each invoked
once. The exact pinned five-second queued-abandoned response with no frame
advancement is also retryable for this startup snapshot only, within the same
stage deadline. A frozen frame sample does not establish permanent failure;
persistent stalls still exhaust the original deadline. Other frozen-frame game
reads remain refused. Advancing render frames alone do not prove the UI queue or gameplay ready.
The same original stage deadline guards the raw mutation dispatch after logging
and fresh listener checks; those checks cannot refresh an exhausted stage. A late
mutation receipt is retained but never followed by another startup invocation.
This executor correction is offline-tested; it requires a new exact-runtime game
qualification and does not change the provider's five-second task timeout.
