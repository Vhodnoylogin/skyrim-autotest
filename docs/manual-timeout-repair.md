# Manual timeout repair and direct operator handoff

This is a source/offline-tested repair, not a live gameplay qualification. It
does not start a game, listener or automatic mod test. Polygon owns preparation,
current human authority, one new native start, the existing microphone and all
commands. Keep old failed attempts, profiles, claims and reports immutable.

The 29 October manual3 failure occurred after a returned native `Actor.SetRace`:
the later `Actor.GetActorBase` VM read timed out. The old executor treated this
as a fatal interactive failure and sent WM_CLOSE. That is an executor-initiated
close, not evidence of a CLAW access violation or a proven failed transformation.
The original transformation must not be repeated in that old session.

## New bounded manual start

1. Independently collect/review the old ended/restored run and actual launch
   accounting. Clear only its exact hold through the existing reviewed protocol.
   Current owner manual-start authority must be recorded by Polygon; this repair
   supplies neither clearance nor launch authorization.
2. Extract the supplied portable archive to a fresh external folder and verify
   every delivery/manifest pin. Keep the executor frozen through collection.
   Retain the actual installed subject/native DLL pins and exact six-actor scene
   inputs. No native mod replacement is part of this repair.
3. Prepare a new external runner config from the existing manual SE config.
   Set `interactive_session.timeoutPolicy` to `preserve-manual` and retain the
   frozen nativeBindings/morphSession, endpoint policy and native startup/anchor
   preparation. Select a fresh runtime/channel/database and finite original
   maximumSeconds plus enough startup/restoration reserve; never reuse/reopen the
   old runtime or reset historical unknown launch accounting.
4. Use Dashboard's supported `qualification-register`, `qualification-check`,
   `qualification-run` admission for a dedicated one-start tool/manual platform
   attempt. This direct-operator request **omits `companion`**. Its ordinary
   generic scenario contains the existing common bootstrap and a native
   observation-capability check. No isolated sequencer/client is started. Keep
   manual subject observations distinct from the scenario's technical checks.
5. Wait for native common world/anchor readiness and `state.interactiveSession`.
   Use its exact new sessionId/binding, original game+runner PID/birth/path and
   native deadline. Do not move the player during the prepared-anchor gate.
6. Submit catalog/config validation and the six original create/name/unequip/hold
   requests from the pinned scene inputs through the documented `operator.actions`
   channel. Preserve native same-run creation witnesses and original human OBody
   sources/targets. Await actual completion for each operation, then ask the owner
   to confirm the scene. The separate voice operator keeps the selected LG mic;
   development chat is not a command relay.

The direct command envelope/CLI is documented in `interactive-session.md`. Stable
sourceEventId, expectedBinding and immutable request files are mandatory. Re-read
the same receipt/events on a lost reply; never invent another ID to replay it.
The source `tools/prepare_manual_scene.py` still prepares an isolated companion
program: do not attach its sequencer to this direct-manual request. Its previously
observed `No module named skyrim_autotest` loader failure remains unresolved and
is not relabeled as successful companion qualification.

## Timeout and collection

Read `state.interactiveSession.lastUncertainObservation` plus the matching
`interactive-manual-action-uncertain`/`interactive-manual-result-observation`
entries in steps.jsonl. Original and late provider receipts remain raw evidence.
Use only validated same-channel native reads while `mutationsPaused` is true.
Report unknown/observed-state facts to the owner; no automatic retry, new client,
game restart or session extension is introduced. The original owner window and
dead-runner/heartbeat protections still apply.

On explicit owner finish, send exactly one `operation:finish` envelope. Await
native done/restored, copied-profile archival, worker exit and collection; never
manufacture a missing companion report. Use the same Dashboard
`qualification-collect` path without companion assertions. Retain the direct
manual requests, completions, provider logs and voice evidence separately.
Uncertain actions yield technical `blocked`, even if an observed target state
was later present. Manual gameplay findings are raw owner observations, not
proof of completed automatic CLAW coverage or a repaired isolated loader.
