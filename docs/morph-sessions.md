# Owned SE morph sessions and NPC persistence

This source candidate adds semantic domains for real human presets, independent
source-to-target measurements and one owned six-NPC save/load. It uses the same
executor, command channel, guardian, common startup/world readiness and restored
temporary MO2 profile. Physics and rendered geometry remain outside this contract.
Build/offline checks alone do not establish a qualified installed platform.

The manual group source candidate can explicitly set `morphSession.maximumFixtures`
to12; absent retains six. Creation requests cannot exceed that frozen choice.
The owned save/load contract still requires exactly six and rejects twelve.
`actor-fixture-visibility` exposes read/show/hide of actual witnessed persistent
references, including disabled references, through a typed native operation.
It pins the VM/runtime identity, provider/world and current cell, then requires
fresh disabled/loaded-state readback. An unknown action is not replayed. Native
runtime-handle stability through hide/show still needs live qualification.

Distribution configuration reads compare the whole installed `npcFormID` map
with the declared complete six- or twelve-base map. Each base can have a bounded
nonempty pool, including a singleton; twelve requires the explicit opt-in. A
six-base subset does not verify an installed twelve-base configuration.

Human state retains raw native generation events and tester mutation intents.
Internal stock generation and natural subject-host calls are distinct: a caller
event is not reclassified as stock or proof of natural host invocation. The
optional `manualTesterMutationsBeforeThisObservation:0` on a full morph read
rejects any earlier tester provider/family/race/test-morph intent, even uncertain
ones. Clear and refresh count as manual family interventions as well as configure.
Use that field only on the initial untouched observation, not owner-mutated A/B.

The three layers remain separate: DevBench supplies registered native tools;
World Observer supplies independent read-only measurements; this external executor
performs bounded actions, preserves evidence and maps semantic results. No mutation
was added to World Observer. The prompt/setup/recipes ship in this distribution.
External audio adapters remain separate and no microphone is opened here.

## Frozen platform opt-in

The SE configuration must opt in to `allow_owned_save_load:true`, an
`interactive_session` with `npcPersistence:true`, and explicit `nativeBindings`.
`morphSession` contains logical binding IDs (`status`, `error`, `assigned`,
`humanWeight`, `beastWeight`, `clear`, `refresh`, `configure`, `race`), the exact
three `testKeys`, optional independently pinned `providerOwnKeys` and
`providerKeyEvidence:{sourceCommit,providerSha256}`, the actual staged
`providerConfigSha256`, and complete `sourceMorphsBySex:{male,female}` catalogs.
No subject-name lookup selects runtime code. Bindings use exact native metadata
and guarded actual actors, never arbitrary scripts or raw engine memory.

Additional Actor.UnequipAll and Actor.SetDontMove bindings support reference-only
fixture inspection. The actual held bus command ID is attached by the executor;
requests cannot supply it. Every mutation records an intent before invocation.
A repeated/uncertain command cannot mint a new mutation or replay its native call.

The platform route accepts these documented domains: actor-fixture,
actor-fixture-identity, actor-fixture-inspection, human-preset-catalog,
human-provider-config, human-preset, human-preset-state, actor-race, morph-link,
actor-morph-fixture, actor-morph-link-evaluation and save-state. The full bounded
request validation is `morph_session.validate`; domain data never contain tool
addresses, native selectors or provider hashes in the subject order.

Human presets come from OBody's actual paginated catalog and assignment API.
The fixed configuration file is read through the running game's VFS, hashed and
compared with the frozen prelaunch pin. This is file evidence, not a claim that
an internal configuration object was inspected. Genuine automatic generation
also requires a matching native OBody event after creation intent, no event loss,
correct provider/world continuity and no prior manual generation/assignment.
Direct GenActor cannot satisfy it and is never invoked by this adapter.

The stock-origin request may omit `expectedStockEventResponsibleInterface` or
explicitly set it to `null`. Both require the real event's copied responsible
owner to be null. The automatic-origin flags, allowed preset pool and integer
zero manual-call count remain mandatory; a non-null expected owner is refused.
No missing selector is taken as evidence of a generation event.

Native catalog pages must match the exact owned PID, provider epoch, world
generation, category, offset, limit and all four counts. Pages retain their raw
native stamps. Missing, duplicate, stale or incomplete entries fail the read.
Fixed-file configuration parsing rejects duplicate JSON keys, colliding normalized
plugin/local IDs, malformed preset pools and a path outside the owned game's
fixed VFS target. It compares every declared base mapping, including twelve-entry
singleton maps, rather than accepting a subset.

OBody 5.2.2 can merge `OBody/obody_includes` files. This reader observes the
fixed main file only: `configObservationScope` is `fixed_main_game_vfs_file_only`,
`inMemoryConfigObserved:false` and `includeConfigurationObserved:false`.
Actual assignment/generation events and an independently reviewed VFS/include
inventory remain necessary; a matching main-file hash does not certify the
effective merged distribution policy.

### Untouched component qualification preparation

`tools/prepare_morph_read_probe.py` accepts an unchanged schema2 semantic source
order and writes a separate tool-only probe, never the original order or a queue
entry. It retains all six creation/identity/automatic-generation routes, eighteen
complete human/beast/return vector reads and twelve same-reference race changes.
Two representative references also exercise reference naming, unequipping and
position holds, keeping the ordinary companion's 64-case bound. All sources,
public targets and signed mapping rows are retained. It refuses preset assignment,
generation, family configuration, test-morph setters and unknown domains.

The probe asserts independent read coverage, identities and availability. Actual
subject statuses, coefficients, numerical errors and preservation differences are
retained as measurements; their desired values are not tool acceptance assertions.
This does not accept the subject mod, physics, rendering, audio or save/load.
Prepare its ordinary semantic companion through `prepare_semantic_companion.py`,
then let Polygon independently review a separate schema1 tool qualification with
the exact frozen executor/configuration/provider pins. Source preparation and
offline tests are not live qualification and never activate a platform.

The OBody 5.2.2 API header is available from official commit
`27515bb44d1b6e973035ae3218877eac5ff09239`,
[include/API/API.h](https://github.com/Aietos/OBody-NG/blob/27515bb44d1b6e973035ae3218877eac5ff09239/include/API/API.h).
Its SHA256 is `f04945202d9daa6408d7555e46eb2a553a1041ab5d84a8f4efc288168563ea18`.
It matches the existing API header bytes; no OBody source or binary modification
is required to observe stock `OnActorGenerated` events. API compatibility does
not establish the provenance or runtime behavior of an installed DLL.

### Ordinary installed body preset catalogs

The six diagnostic targets are not the whole catalog of an ordinary CBBE/HIMBO
installation. `human-provider-config` optionally accepts
`allowedAdditionalLoadedPresets`, an exact list of native-observable identities:

```json
"allowedAdditionalLoadedPresets": [
  {"name": "Exact stock preset name from the native catalog", "category": "female"},
  {"name": "Another exact installed name", "category": "male_blacklisted"}
]
```

Categories are exactly `male`, `female`, `male_blacklisted`, and
`female_blacklisted`; names are case sensitive. Declare every additional identity
including blacklisted ones (0..4096 entries); no glob, ignored unknown name, or
target-name overlap is accepted. Source archive/XML hashes belong in preparation
pins: the native API exposes names/categories, not the originating XML path.
Leave official body/preset files intact. This opt-in does not make stock extras
eligible for assignment to the diagnostic actors.

When the field is present, even if empty, first call `human-preset-catalog` with
exactly six unique target names and their actual sexes. Those names must exactly
equal the union of the complete base-selection policy. The stored request is
only a declaration; each configuration check reads a fresh native catalog.
Every target must exist in its declared active sex category. A wrong-sex or
blacklisted target cannot satisfy availability. Every declared additional
identity must exist in its exact category, and every observed identity must be
a target or explicitly declared extra. Inspect `missingExpectedPresetCount`,
`missingAllowedAdditionalPresetCount`, and `unexpectedLoadedPresetCount` (all
must be zero), their detailed lists and `catalogObservation`.

With the field absent, the existing strict six-name policy remains; blacklisted
targets alone no longer count as available. The exact full `npcFormID` dictionary,
frozen VFS configuration SHA256, singleton selections and twelve-fixture opt-in
are unchanged. There is no subset or alternative-preset fallback.

SKEE aggregates, name presence and complete per-key records come from the
independent Observer, in batches of at most32 names. Preserve zero, negative and
available-absent values separately. A missing/truncated/stale read never becomes
zero. Mapping uses signed sum(source*gain), clamps once, then multiplies its cap;
weights are not multiplied twice. Subject diagnostic getters are separately
recorded and never replace those raw source/own-key measurements. Unknown weight
`-1` is unavailable. Peer comparisons make fresh reads, retain both baselines and
actual changed entries; they are sampled, not atomic actor-wide snapshots.

Full provider, peer and interval evidence remains in the normal result artifacts
and step log. The durable working state retains a compact numeric/presence baseline
with source command/label/full-result hash. A retained baseline is never labelled
as a fresh observation. This avoids recursively copying large raw envelopes into
the mutable state file while keeping all comparison inputs and full evidence.

## Persistent references and inspection

The default QASmoke arrival faces furniture; relative NPC offsets can land in
its collision geometry even after SetDontMove. For the native SE New Game route,
the explicit top-level `se_fixture_anchor:"qasmoke-west-navmesh-v1"` prepares a
west-room player anchor during common initialization, before gameplay readiness
is published. The executor resolves Dragonborn's actual marker through the
loaded plugin, checks its identity/pose and performs one recorded relocation and
orientation. Bounded stable readbacks must pass; unknown mutations are never
replayed. No subject order implements this startup transition. The unchanged
fixture offsets still need actual placement and drift checks; navigation data
alone do not prove the absence of contacts. Live qualification remains required.

`persistentForOwnedSave:true` is allowed only with the explicit opt-in. PlaceAtMe
uses forcePersist, then two independent native reads verify actual persistence
and exact VM/reference identity. Names change only the created reference; no NPC
base or base outfit is edited. Gear is unequipped through a frozen native binding;
inventory is not deleted. Hold uses SetDontMove and reads the typed movement flag
plus actual position samples. Slots30..61 and equipped weapon types are read
directly. No collision-disable command is issued; this is not physical-contact
qualification. Spoken alias files are data for the operator; raw speech is not
executed as a machine action and this feature starts no audio process.

One save/load bundle covers exactly six witnessed persistent actors. Before the
game starts a random32-byte probe is put only in the disposable saves directory;
the native tool must read that nonce through the actual default MO2 save alias.
No fake ESS or personal save is needed to prove that mapping. Existing legacy
pinned-ESS probe behavior is preserved for other configurations.

Save completion requires native lifecycle evidence and an exclusive-readable
stable ESS/SKSE pair. The authored native SKSE serialization record saves actual
reference and VM identities. Loading invokes ResolveFormID and ResolveHandle;
fresh VM object/reference/base and Observer world identities must agree for all
six actors before one atomic registry rebind. Old handles are invalidated first.
No old FF ID or matching base alone can authorize adoption.

The held client admits one explicit same-process load for this exact saved tag,
command ID, frozen configuration, pair, binding and original interactive window.
Its special load deadline is at most90seconds and does not extend the session.
The temporary bootstrap/phase exception is allowed only while that delivered
load is outstanding. One completed six-actor native remap and actual common
gameplay readiness allow one audited bootstrap update. Other world changes,
restart, wrong identity, late/uncertain completion and a second load fail closed.

## Build and qualification

`tools/apply_devbench_morph_provider.py` stages authored providers into the exact
compatible external DevBench fork. Acquire the official SKEE/OBody headers outside
Git using the URLs/hashes recorded in the dependency recipe. Set
`AUTOTEST_PROVIDER_API_DIR` to that verified folder for xmake. The script never
installs or launches. Existing observer SE build instructions remain separate.
The combined DevBench/OBody API dependency keeps its upstream license notices.

`tools/prepare_morph_qualification.py --help` freezes a dedicated tool-component
plan from supplied fixture/catalog/registry files. It creates a self-contained
pinned sequencer for the existing subject companion, nine finite cases, explicit
platform policy and source/input hashes. It changes no profile, order or hold.
Only Polygon reviews current human authority, exact installation/ownership,
recovery closure and finite launch accounting, then runs that package. The cases
exercise catalog/real automatic events, six persistent references, names/gear/hold,
assignment, independent signed/zero keys, typed subject/race routes, owned save/load,
postload identity and exact cleanup. A pass qualifies these component routes;
it is not acceptance of the subject mod, physics or every future scenario.

The optional `--include-held-bridge-check` adds `held-semantic-world-read` as a
tenth tool case. Both real interpreters run as stages without an intermediate
finish, retaining one global measurement sequence. The generic interpreter
performs actual `platform.state.read` and asserts `world.ready:true`; this is
transport/composition qualification, with no subject behavior assertion. Only
after both stages pass does their caller send one final owner finish. An unknown
stage outcome stops without another stage, finish or replay. The default nine
case recipe remains available. New outputs explicitly select
`manageCommandEndpoint:true`, retain both authored source snapshots, and pin the
generated generic order, mapping, compiled scenario and semantic spec. The
default600second/256command bounds are unchanged; Polygon's900second outer limit
still includes common startup/restoration. Existing frozen packages are untouched.
# Finite scenarios and manual holds

The native morph/persistence capabilities may be frozen in top-level
`native_session` for ordinary finite scenarios, with required `nativeBindings`
and optional `npcPersistence`/`morphSession`. The runner finishes after the declared
steps and cleanup. These settings no longer require creating a manual hold.

Legacy `interactive_session` remains the manual option. Declare exactly one of
the two; ambiguity is refused. Both routes use the same frozen binding validators,
owned fixture/world guards and durable once-only semantic mutation identities.
