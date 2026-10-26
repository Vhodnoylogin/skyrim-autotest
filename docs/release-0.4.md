# Release0.4: composition and verification

One executor, two explicit editions. Core lifecycle, evidence, setup and command
transport are shared; editions.py and the physical VR backend retain separate
requirements. No second product or duplicated runner is required.

## Layers

1. Upstream DevBench1.32.0 (938c392d5e0fc19260c65f689ff4a80fbec4007c),
   included in the owner fork5068162637dc2b5621b7224b8eded76a0c9e3d4f.
   The fork adds generic native readiness/UTF8/SDK/startup support. Load one
   winning DLL. Build externally using devbench-native-startup.md.
2. This independent executor owns application/MO2 lifecycle, common verified
   gameplay initialization, local fixtures, controls, assertions and restoration.
   Optional Observer, Dashboard and sound adapters remain separate dependencies.
   The persistent command API receives text/final-ASR independently of an AI turn;
   it never executes game actions or becomes another game owner.
3. The included agent-kit prompt, setup specification and integrated setup/doctor
   configure the external installation and chosen host/audio connections.

## Retained native evidence

The0.4.0 RC6 executor ee9bd5b8a94394e8c9fe230de86aa430a8f3dbe8 passed
its bounded SE execution on26October2026 with the same provider DLL below.
Packet SHA2563524b8ae0ea6c5fde4b72b9df3c420f5a66075db53a66e2ca0baef9e9b6c94a3
retains10passed/3unavailable declared checks and an incomplete subject-coverage
label; execution and restoration passed. Separate technical evidence verifies
native New Game through Realm to QASmoke,141.493units of player XY movement,
one same-run-created stock NPC and two actual race readbacks, reception during
a running command, eight completed commands and owned game exit0. Collection,
restoration and copied-profile archive/removal were independently verified.
This is tool qualification, not CLAW morph/render acceptance. A later VR attempt
failed before gameplay with no matching DevBench and incomplete restoration;
VR refresh is deferred by the owner's SE-only instruction. No VR pass is claimed.

Earlier retained evidence:

Exact SE0.3.10/provider5068162 DLL SHA256
8930942502a5f75d9f0c03586cd067af37373eef60f93ac656dcf8a836abf3ec
passed Q4 on26October2026:27declared checks plus initial-world readiness, five
true admissions, actual native New Game, normal owned close, complete collection,
restoration and archived/removed copied profile, no guardian takeover. Packet
SHA256 b1d29faf74d0e61d7a9e91648e756d65212f1ad3947c8098b0e312fa482aa03d.
The exact SE104 Observer separately passed14checks. A later subject actually
started and produced an assertion-stop result; that is not a launch failure.

These measured subsets do not qualify arbitrary providers, mod mechanics,
rendered geometry, contacts, the refreshed VR composition or a fresh hardware
voice path. New source, packaged/offline, protocol and native release checks are
recorded separately. A responding endpoint or offline doctor is not gameplay.

## Acquisition and sound

External tools, SDKs, binaries, private saves, models and recordings stay outside
Git. dependencies.json and provider build recipes record reacquisition, not bundled
third-party installations. Setup reports missing requirements and preserves
existing configuration; it does not download licensed assets or change MO2.

Sound is optional and separately connected. External ASR submits complete final
transcripts to the command API. External TTS consumes speech requests and returns
playback evidence. Text is primary; short speech is exceptional. The channel
neither guarantees recognition accuracy nor wakes a host that has no supported
connector. Do not start competing microphone owners or treat the installed modern
Speech Broker C ABI as an external Whisper CLI service.
