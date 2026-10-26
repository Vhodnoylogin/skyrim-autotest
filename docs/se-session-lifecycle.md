# SE initialization and process-exit boundary candidate

Version0.3.10 uses the direct `devbench-startup-ui/1` native menu contract for
explicit SE startup. It replaces the0.3.9 Papyrus UI path, which actually timed
out on the main menu before VM initialization. The native contract is provided
by the separately pinned owner DevBench compatibility fork; there is no silent
Papyrus fallback. Snapshot, one checked NEW selection and one checked confirmation
are distinct. Unknown contract/typed state and uncertain mutations stop; no replay.
Use the [direct startup provider acquisition recipe](devbench-native-startup.md).

Version0.3.9 addressed two different operational prerequisites. Neither a source
test nor27passed ABI assertions is complete native qualification or mod acceptance.
The frozen0.3.8 package, existing subject orders and old failed evidence stay unchanged.

## Read-only settlement during shutdown

A complete Windows Toolhelp snapshot can still list an owned game whose later
creation-time/path query returns unavailable during exit. Missing identity does
not prove death or ownership. The shutdown guard now performs only fresh complete
inventory/identity reads for up to2seconds/40waits when the unresolved PID belonged
to a previously recorded game/loader. It sends no command, close or termination
while the row is unresolved. It proceeds only when a fresh complete inventory has
no such row or its full current identity exactly matches the recorded identity.

An unknown foreign PID or a known changed identity fails immediately. Persistent
unknown owned rows, empty/partial/unavailable inventories, PID reuse or a foreign
game appearing during the wait retain the shutdown barrier. Both pending and
settled observations are logged; PID membership never grants ownership. Existing
native close/termination handle checks remain unchanged.

Guardian recovery now checks the latest state after acquiring the session mutex:
a session that already completed is left unchanged. A genuine recovery remains
failed, retains the prior concrete reason, and adds a separate guardianRecovery
trigger/prior record in state/result. It never converts recovered failure into a
normal successful shutdown. Historical reports are not rewritten.

## Explicit initialized SE world before subject actions

Cell-only main-menu `coc` can produce a loaded actor/cell without an observed SKSE
newGame/postLoadGame event. Mods that enable their tasks on those events may then
return false for every call despite healthy transport and loaded geometry. A
native Bool result is factual admission data; its type alone does not prove readiness.

Optional platform-config `se_new_game_ui:true` selects the existing identified
stock main-menu NEW/confirmation path for SE cell fixtures. It requires an explicit
SE target and a cell, and refuses a pinned-save fixture. The subject's semantic
order is unchanged. Configuration/attempt pins own this startup choice; no mod name
chooses behavior. Default SE and VR configurations retain their original behavior.

The actual installed1.7.104 stock startmenu movie was inspected offline: its root
MenuHolder.Menu_mc, NEW index1, Main/MainConfirm states and StartNewGame delegate
match the identified UI adapter. At runtime the adapter verifies UI metadata,
unique enabled NEW entry, selected-entry identity and confirmation before invoking
the UI. No desktop coordinates, guessed key sequence, raw engine call or synthetic
SKSE message is used. After character creation/startup menus settle, SE additionally
requires the unique actual contiguous native newGame event. Menu/cell transitions
alone cannot pass this gate. Only then may the executor enter the declared cell,
complete common readiness and start subject checks. State records startMode and
startupSelection separately from the original scenario.

## Required qualification

Polygon must independently select/pin the effective game/UI assets, enabled mod
composition, provider DLLs/configuration and exact fresh portable executor. The
offline movie inspection covers this stock layout only; a replacement movie must
meet the runtime identity contract and its own reviewed pins. Extracted game
assets and external inspection programs stay outside Git. The existing menu
recovery rules for unknown dialogs and late character creation remain in force.

One separately authorized bounded tool run must prove actual NEW selection,
native newGame initialization, settled declared world/actor and usable API admission
before the original subject is dispatched. Require true admissions where the probe
needs initialized task handling; true still is not async completion or rendered
geometry. Then prove normal owned shutdown, stopped healthy heartbeat, no guardian
takeover/forced-stop if claiming graceful exit, complete restoration, archived and
removed test profile, collected evidence and cumulative physical start accounting.
An ended/restored run with passed action checks but teardown failure remains failed.

Use a new immutable tool order/lease and frozen executor for any prospective
qualification. Preserve previous failed packets, pending subject identity and
unconsumed one-shot release. This candidate does not clear a hold, extend a lease,
grant a launch or restart old cycles. SE fresh startup and the shutdown change
have source/fresh-package coverage only until that actual qualification succeeds.
