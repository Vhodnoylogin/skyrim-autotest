# AI-agent instructions: Skyrim Autotest

Use this tool for autonomous, bounded Skyrim VR tests after the owner has
requested/authorized testing. Existing authorization persists; do not ask again
for ordinary reversible launches within that scope. New fixture setup and mod
installation must remain within the owner's requested scope.

1. Read README, docs/configuration.md and docs/scenarios.md. Discover the explicit
   external config; do not guess the owner's game/MO2 profile paths. `init`
   creates a template only, never installs mods or prepares a personal save.
2. Identify subject mod, dependencies, fixture, actions and game-observed success
   criteria. Put every mutable input/output file in `extra_files`, and stage an
   optional observation plugin through `staged_plugins` with SHA-256. Keep saves,
   tokens, binaries, backups and generated artifacts outside Git.
3. Run `config-check`, build the external pinned driver if missing/stale, then
   `preflight --profile <name>`. An idle MO2 restart is explicit. Never take over
   a user's running game/SteamVR or force-close unrelated processes.
4. Validate the scenario locally (`skyrim_autotest.scenarios.validate`). For
   physical controls use `tool:driver` full absolute frames and bounded leases.
   DevBench direct input is a separate diagnostic backend. Publication success,
   a command ACK, pointer values or HTTP success cannot substitute for observed
   mod/world behavior. Include assertions about the exact affected reference,
   resulting mod state and expected temporal behavior.
5. Prefer direct structured state over screenshots for functional assertions.
   Ask a provider for capabilities, availability, world generation, phase and
   units before using a domain. Missing physics/contacts/capture is unavailable,
   not success, zero contacts or a false collision. Empty contact events cannot
   prove absence of contact; collection gaps and stale generations invalidate
   such an inference. Tolerances do not make Havok deterministic.
   For positive physical contact require at least one callback record with
   signed separation <=0, speculative=false and disabled=false, matched to the
   exact body/reference and current generation. A speculative proximity event
   alone is not touching; a contact callback does not prove the final solver result.
   Use typed probeObject variables only within the spawned fixture's lifetime.
   A load, stream gap or world-changing request invalidates that variable.
   Lifecycle validation and the next request are separate operations, so this
   defensive guard is not an atomic producer-side generation contract.
6. Run once using `run --profile ... --scenario ...`. Poll only read-only tools
   with finite deadlines. Never blindly repeat spawn/load/console/Papyrus/input
   mutations, silently weaken assertions or automatically rerun failed tests.
   The executor may repeat a polling world_observer snapshot only when its
   structured outcome is abandoned_before_start; all attempts keep the same
   deadline and log. Started reads, unknown failures and mutations remain terminal.
   The built-in cell-readiness wait separately permits scene-only HTTP
   500/502/503/504 or structured abandoned_before_start reads within its original
   90 seconds. Known UTF-8 serialization failures stop immediately; three
   consecutive HTTP500 scene errors stop rather than consume the whole budget.
   Check late blocking dialogs during save/cell transitions through the common
   executor. Require playerLoaded and exact cell editorId/formId, never matching
   text anywhere in a response. Text encoding diagnostics preserve unavailable
   display fields; they do not waive subject text assertions or cell identity.
   Preserve every error; require stable matching scene data afterward.
   Never repeat coc/load or treat a retried error as readiness. Identity/health
   errors and arbitrary scenario HTTP failures still stop the run.
   For explicit unattended physical VR scenarios, allowBackgroundVR:true may
   permit testing while another application has foreground. Use it only with
   the physical file backend, retain recorded focus denial, and require the
   same hand/grip/hold/release/world assertions. It does not authorize background
   keyboard/UI automation or turn focus/publication into evidence of game input.
   An unknown blocking modal requires a reported blocked/failed result; never
   guess GUI coordinates or accept a prompt by text similarity.
7. Read runtime/runs/<id>/result.json and returned-state evidence. Success needs
   result=passed, restored=true and no restore errors. Record failures, scope,
   exact scenario/mod/build hashes and unavailable domains honestly. Cumulative
   logs support only entries in the owned session interval.
8. If interrupted, execute `recover` against the same runtime. If a runner is
   still alive or a foreign session exists, do not bypass ownership checks.
   Preserve distribution, state and backups until restoration is verified.
9. Queue submission pins a scenario hash. Revised fixtures/tests get new orders.
   Owner acceptance is separate from a passing run; do not invent acceptance.

Commands: `python -m skyrim_autotest --config <external JSON> <command>`.
For portable extraction use `python <absolute distribution>/run.py ...`.
Commands are init, config-check, build-driver, preflight, run, status, recover and
queue. `guide` prints these instructions. Fault injection requires a deliberate
recovery-test task; its expected failed result is not a mod regression.

For Polygon semantic requests read docs/platform.md. Candidate mappings alone
do not qualify a platform. Preserve common bootstrap and absolute step deadlines;
never treat requested fixture values as measurements or sampled held-reference
continuity as proof of unobserved events. Keep subject orders unchanged on tool updates.

Code contributors: use Python standard library only for runtime; preserve
process creation-time/path/ancestry ownership, shared mutex and durable snapshots.
Before committing/pushing verify and name this repository and remote. Third-party
source/programs/SDKs belong outside Git; retain acquisition pins and build recipes.
Run meaningful recovery and portability tests for ownership, configuration or
packaging changes. Do not claim fresh portable live acceptance from historical
support-tool runs; record the independently tested build and session.

Headset-assisted voice sessions use docs/voice-v2.md. Preserve ongoing live
listener ownership; new version preparation does not stop/restart it. Buffered
receipt/dispatch, first actual text reply and completion are distinct. Never
execute provisional or interrupted audio, resend uncertain deliveries, or call
an offline replay a qualified live voice session. Keep audio/models outside Git.

For Polygon-owned runtime use docs/voice-operator.md and voice_operator ensure/poll.
The development chat is not a runtime intermediary. Never message another chat
per utterance or use the historical cross-chat adapter for this owner's sessions.
Consume final speech directly in the operator turn; unchanged pending/quiet
records require no status chatter and never authorize action replay.

Supplementary diagnostics: see docs/boundary-collection.md. Only Polygon's
separately qualified configuration can opt into boundary_collection. It records
raw reads between exact adjacent settled checkpoints without changing mod orders
or subject counts. Never insert it into a motion/race/first-frame interval or
call response_recorded a passed subject gate. Keep all missed reads explicit.
