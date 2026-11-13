# Unreleased runtime source reconciliation

Version **0.4.0.dev0** is an unreleased development source candidate. It brings the
previously retained private runtime into the source tree alongside the existing
agent guide, examples, tests, documentation and build tools. A source import does
not replace a frozen executor, qualify a provider or authorize a game launch.
Historical runs retain their original file pins and results.

## Provider compatibility

Actor-domain operations now require the observer's actual `baseForm` identity in
both reference snapshots around a read. Missing or changed identity refuses the
operation. The old Papyrus `GetActorBase` fallback is absent; an older observer
without this field is incompatible with these actor-domain operations. Other
observations do not acquire that requirement merely by importing this module.

The explicit SE New Game path uses `devbench-gfx-main-menu/1`: actual Scaleform
movie reads, typed selection, one guarded selection write/invocation and actual
confirmation. It requires the owned listener's Main Menu admission and original
stage deadlines. Unknown mutation completion permits no replay. Native NEW and
initialized-world evidence remain separate gates; a GFX acknowledgement alone is
insufficient. The older `devbench-startup-ui/1` transport described for0.3.10 is
historical, not an automatic fallback in this candidate.

## Exit evidence

The report preserves an earlier identity-verified, retained-handle exit code when
later recovery observations are unavailable. Selection requires exactly matching
PID, creation time and executable path in both identity brackets. Unverified,
malformed or conflicting trusted code records do not become known exit evidence.
Every raw observation remains in the result; a later recovery diagnostic remains
visible separately. This changes reporting only, not cleanup or acceptance.

Exit code0 establishes neither cause nor an unforced normal exit. In the retained
VR13b failure SteamVR launched room setup and forcibly terminated SkyrimVR; the
known code0 cannot convert that failed attempt into success.

## Qualification boundary

This source candidate has **no new VR qualification**. VR13b failed before NEW,
character input and menu checks; its later verified restoration does not promote
the platform or renew a launch allowance. Compositor process presence does not
prove settled SteamVR calibration or scene-application state. A prospective
pregame readiness repair and separate qualification remain necessary.

Offline tests cover source contracts and reporting. They are not exhaustive
qualification of every imported module, an installation, body dispatch, physical
controllers, collision/contact behavior or rendered output. Choose exact source,
provider and runtime inputs for each separately authorized future attempt.
