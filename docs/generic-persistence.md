# Explicit generic two-actor SE persistence

This offline candidate exposes existing native owned save/load independently of
MorphSession, matrix evaluation and OBody. It is not a qualified installed platform.
It reuses the authoritative `interactiveActorFixtures` creation registry and the
same SKSE form/VM remap protocol, with no second actor ledger or raw-save route.

Under either `interactive_session` or `native_session`, declare `nativeBindings`,
`npcPersistence:true` and this exact additional policy:

```json
"npcPersistenceRoster": {
  "mode": "generic-two-actor-v1",
  "fixtures": {
    "Born": "0xFE006805",
    "Human": "0x000A2C90"
  }
}
```

These are examples, not portable resolved bases. Pin the intended runtime base
identities in the actual admitted configuration and `nativeBindings.fixtureActorBases`.
Exactly two distinct bounded tags are required; both may deliberately use the same
approved base. Unknown fields, other counts/modes, ambiguous morph/matrix declarations
and VR refuse. Keep `allow_owned_save_load:true` and the existing owned temporary
profile/save-directory rules. Absence preserves legacy six or explicit matrix two.

Create each actor through the existing held `fixture-create` operation with its
declared tag/base and `persistentForOwnedSave:true`. Creation still verifies actual
base/race/sex, same-run ownership, loaded incarnation, native persistence and placement.
A born beast is not recast as a human baseline. This policy does not enable morph
domains or change their matrix/sex/provider preconditions.

The existing `actor-visual-freeze` read/once-only prepare operation is admitted for
an actually created declared member, including a partial creation cohort. Every
present registry entry must be a declared correctly based owned creation. Unknown,
uncertain or duplicated entries refuse. Actual target AI, reference collision and
character-controller collision readback, loaded identity/world and DontMove remain
mandatory; DontMove alone is not a freeze. No automatic hook, global toggle, contact
absence or solver-result claim is introduced. Uncertain commands remain non-replayable.

Use the unchanged platform `save-state` operations: `save-disposable-once` with both
tags in `actors`, `maximumSaves:1`, `scope:current-temporary-profile`, then optionally
`load-owned-disposable-once` with `maximumLoads:1`, `processRestart:false`. Both use
the same `saveLabel`; `world.read` with domain/saveLabel observes the bundle. See
[the existing semantic request shapes](morph-sessions.md). The standard interactive
bus and finite platform executor support this candidate. The optional
`tools/subject_companion.py` still restricts its separate owned-load adoption to
legacy six; this candidate does not qualify or bypass that transport. A separately
reviewed caller must preserve native command/window/bootstrap and result evidence.

Save/load requires all and only the exact declared pair in the authoritative registry,
with matching dictionary key/tag/base, complete creation and native witnesses.
The saved bundle pins the exact roster policy; policy loss/change or replacement
of saved creation identities refuses. Intent-before-mutation, one owned save/load,
same process, original absolute deadlines (primitive30/read/save, load90), ordered
native load events and common gameplay readiness are unchanged. Both actual native
remaps and fresh Observer incarnations must pass before publishing replacements
together. Missing current members/rebindings and stale native remaps cannot pass
a subsequent read or ordinary actor guard. Partial rosters are allowed for explicit
per-member freeze preparation, never save/load or post-load roster restoration.

Provider changes/rebuilds are unnecessary for this adapter addition when using the
exact qualified native bundle that already supports two witnessed actors. Pin the
actual provider and separately qualify the changed executor/composition in game.
Offline synthetic transport tests do not prove live born-beast behavior, rendered
quality, material application or physical contact behavior. Prior packets stay immutable.
