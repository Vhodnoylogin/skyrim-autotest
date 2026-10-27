# Owned NPC save/load

This opt-in implementation preserves six newly created NPC identities through one
save and one load in the held interactive game's existing process. It uses the
normal disposable MO2 profile, common save/load lifecycle and gameplay readiness
implementation. It does not qualify an installed provider by its presence in source.
Polygon must qualify the exact composed binaries and configuration before selection.

Enable `allow_owned_save_load:true` and the frozen
`interactive_session.npcPersistence:true` alongside the reviewed `nativeBindings`
policy. The installed DevBench must provide `npc_persistence` protocol
`npc-persistence/1` and its registered SKSE co-save serialization callbacks.
The held action transport must explicitly expose the narrow persistence operation;
raw `game` calls and arbitrary save directories remain outside that interface.

Create each of the six NPCs with the existing fixture creation request plus
`persistentForOwnedSave:true`. This supplies `true` as `PlaceAtMe`'s force-persist
argument and records it in the durable creation witness. Ordinary creation keeps
its existing default. Persistence cannot be retroactively asserted for an earlier
nonpersistent or uncertain creation.

Persistent creation additionally calls the native `identity` read after actual
loaded-3D observation and again after placement. Both reads must prove the actual
persistent flag, current reference/base, exact VM handle, observer runtime handle
and unchanged native process/provider session. Only then does creation return
`actor.persistentSaveWitnessAvailable:true` and store `nativePersistentIdentity`.
The native save binding must retain that same VM and provider identity.

The Python interface accepts these exact requests through the already owned
session, its frozen policy and one absolute deadline:

```python
npc_persistence.perform(session, {
    "action": "save", "saveTag": "CLAW-SE-subject",
    "fixtureTags": ["MThin", "MMuscular", "MHeavy", "FThin", "FMuscular", "FHeavy"]
}, deadline, policy)
npc_persistence.perform(session, {
    "action": "load", "saveTag": "CLAW-SE-subject"
}, deadline, policy)
npc_persistence.observe(session, {"saveTag": "CLAW-SE-subject"}, deadline, policy)
```

Save/read bounds are thirty seconds; load permits up to ninety seconds within the
already held session's original bound. A tag covers exactly all six attempted
fixture actors. One save bundle and one load attempt are permitted. Neither a
timeout nor an uncertain callback authorizes another bind/save/load. Durable
intent precedes each mutation; failed loads invalidate all six fixture bindings.

Before saving, each fixture must pass the actual owned creation, base, sex,
loaded-3D, process and observer-generation guards. A native bundle binds its
run ID, save tag, random binding UUID, creation IDs, reference IDs and actual
Papyrus VM handles. Native inspection verifies the persistent flag and VM-handle
object correspondence. The save must have both the ordered native save event and
one quiescent, exclusive-readable ESS/SKSE pair in the proven owned save namespace.
The ordinary file headers, pair hashes, MO2 mapping checks and size bounds remain
mandatory. A separate native serialization receipt must advance exactly once.

Before requesting load, every old actor binding becomes unavailable. The existing
owned-load implementation verifies the exact unchanged pair, native ordered
pre/post-load events, unchanged owned game identity and common gameplay readiness.
SKSE deserialization resolves both the saved FormID and saved VM handle. A fresh
native read must show that the two remaps identify the same persistent actor,
base and current VM handle. VM handles use exact decimal uint64 strings; a JSON
number is refused. A current observer read must independently show a later load
generation, the same observer session, loaded 3D and the actual current runtime
handle. A runtime handle's numerical value may legitimately remain the same.

Only after all six checks succeed does the executor publish the six replacement
bindings together. The original creation reference/witness stays immutable; each
replacement carries the corresponding complete native restoration witness. The
ordinary fixture guard subsequently checks that witness against the completed
same-run bundle and current world generation. A former FF ID, matching base,
cached actor, same-looking NPC or successful API response cannot replace this proof.

The result retains raw native receipts and pair hashes. Saved observations expose
`save.completed`, `save.ownedPairCount` and `save.actorWitnessCount`. After load,
they also expose `save.loadedOwnedPairCount`, `save.actorRemapWitnessCount`,
`save.worldReady`, current actors/incarnations and restoration witnesses. These
prove save/load identity and readiness. Subject morphs, suppression, linked state,
weights and rendered appearance require their independent post-load observations.

The unit suite uses the real owned-save hashing/lifecycle path with a simulated
game/provider. It exercises lost bind/save/load acknowledgments, changed co-saves,
missing serialization despite valid save files/events, stale observer generations,
incorrect VM remaps, process replacement, duplicate identities, old-reference
refusal, request bounds and atomic six-actor rebinding. It is not live acceptance.
