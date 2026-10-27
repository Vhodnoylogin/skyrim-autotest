# Native morph provider candidate

`native/devbench/MorphProvider.cpp` is an authored extension to the separately
acquired DevBench host. Register `dvb::MorphProvider::Register(registry)` once and
forward every SKSE message type to `dvb::MorphProvider::OnSKSEMessage(type)`.
The existing ToolRegistry exposes `morph_provider` through its ordinary MCP/REST
route. There is no additional HTTP server and no World Observer mutation.

Build with the official externally acquired `IPluginInterface.h` and
`OBodyAPI.h` in the include search path. Do not bundle either header in this
repository. The acquired API versions are OBody plugin API v1 and SKEE
BodyMorph v5; another interface version remains unavailable. The lifetime of
the borrowed interfaces and readiness listener is the game process. Acquisition
occurs once at SKSE PostPostLoad. OBody readiness invalidation and all OBody API
use share a gate, including the becoming-unready boundary before storage changes.

## Reads

All actions use a bounded existing main-thread task, with `timeoutMs` in1..5000.
Unknown fields are refused. `capabilities` reports real interface acquisition,
current readiness epoch, world generation, and limits. It does not attest the
contents of a staged distribution configuration. Effective configuration must
be established separately from exact staged-file and actual deployment evidence.

`catalog` takes `category` equal to `female`, `female_blacklisted`, `male`, or
`male_blacklisted`, an optional `offset` in0..65535, and a `limit` in1..256.
It independently invokes GetPresetCounts and GetPresetNames, copies the returned
views while readiness is protected, and returns all four sex/blacklist counts.
Names are limited to512UTF-8 bytes and are never inferred from actor assignments.
Empty pages are valid; missing interfaces and invalid text are explicit errors.

`actor_status` takes exact hexadecimal `actorFormId`. Its `identity` contains
actor/base/race FormIDs, runtime handle, loaded model identity, process ID and
provider world generation. Its assignment read uses GetPresetAssignedToActor,
ActorIsProcessed and ActorIsBlacklisted. No assignment, generation or model
update runs in this read. These are sampled provider fields, not automatic-origin,
applied-morph or rendered-completion evidence. Independent World Observer events
and SKEE key/aggregate reads remain required for those claims.

Model identity is an opaque process-local sampled token, not an exported root
address. A bounded cache retains only the hidden address value, handle and world
for change detection; it does not retain the root object. Unobserved destruction
and reuse at the same address/handle cannot be detected by this sampled token.

`action_status` takes `owner` and `command` and returns the retained raw receipt.
It is safe to poll; it never retries the underlying mutation. An old receipt
keeps its original world identity after a load, while the enclosing status stamp
describes the current provider world.

## Mutations

Every mutation takes `actorFormId`, `guard` equal to the entire last observed
identity object, and separate32-character lowercase hexadecimal `owner` and
`command` tokens. The exact actor must be loaded, non-deleted, dynamically
created with an FF reference ID, and distinct from the player. The implementation
retains both actor and loaded root during its checks/call and validates the
actor/base/race/handle/model/process/world guard immediately before provider use.
At most six references may be mutated per world. The caller must separately
establish its actual disposable-fixture creation/ownership witnesses: an FF ID
and this provider's identity checks alone do not prove creation by the caller.

The actions are:

| Action | Parameters | Actual provider call |
| --- | --- | --- |
| `assign_preset` | exact `presetName` | AssignPresetToActor with ForceImmediateApplicationOfMorphs |
| `unassign_preset` | none | AssignPresetToActor with an empty name and the same flag |
| `reset_provider_morphs` | none | RemoveOBodyMorphsFromActor |
| `set_test_morphs` | `values`:1..3 morph/key/value objects | SetMorph for the explicit tuples, then UpdateModelWeight(false) |
| `remove_test_keys` | `keys`:1..3 test keys | ClearBodyMorphKeys for only the submitted keys, then UpdateModelWeight(false) |

Reset preserves the provider's assignment and per-actor configuration according
to the documented API. It never substitutes ClearMorphs, ClearBodyMorphNames,
Revert, arbitrary key deletion, direct memory writes or Papyrus generation.
If installed OBody itself affects a foreign key, independent before/after
observations must report that real behavior; this adapter performs no hidden repair.
It never invokes EnsureActorIsProcessed or ApplyOBodyMorphsToActor to manufacture
an automatic-generation witness.

Fixture keys are printable ASCII names of at most128bytes containing `.Test.`.
Morph names are printable ASCII of at most128bytes, values are finite -2..2,
duplicate keys are refused, and at most three distinct test keys are admitted
per world. A domain adapter must additionally admit only its exact frozen
scenario keys. Generic namespace admission is not proof of ownership of an
existing key. The native extension contains no subject-specific morph names.
Zero coefficients are passed unchanged; actual zero-key presence must be read
back independently, since the installed SKEE implementation controls retention.

The provider reserves the owner/command token before queueing and retains it
across all loads for the process lifetime, including failed validation and
abandonment before task start. Reusing a token is always refused. At most512
receipts are retained; the limit never evicts an old token to permit replay.
Receipts distinguish queued, rejected-before-call, abandoned-before-start,
provider-call-started, call-returned and call-outcome-unknown. A started task
can finish after an HTTP deadline; action_status retains that later result.
`providerAccepted` is only the real OBody preset-found return or acknowledgment
that a void call returned. Every returned mutation remains `completion:unobserved`.
No transport success or receipt can establish morph linkage, automatic origin,
foreign-key preservation or rendering.

## Offline verification and qualification

`tests/morph-provider-behavior.cpp` includes the production implementation and
compiles against the actual acquired API headers and DevBench declarations with
a fake engine/provider. It exercises real dispatcher/validator paths: exact
guards, readiness, catalog bounds, non-replay across loads and queue timeouts,
assign/unassign/reset method selection, supplementary key bounds, signed/zero
values, foreign-key preservation by the adapter, and actor-count admission.
Build it with a C++20 compiler, DevBench `src`, the external `provider-api`, and
the pinned nlohmann include directory. Output belongs in an external build folder.

The fake provider proves adapter behavior only. A successful host build and
these tests do not establish installed provider source equivalence or in-game
qualification. Polygon must qualify the exact staged DLL composition, observe
the actual same-reference effects through independent raw Observer reads, and
retain rejected/unavailable results honestly. Configuration, generation events,
save remaps and rendered state require their own real evidence.
