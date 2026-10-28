# Owned launch followed by manual inspection

`tools/prepare_manual_scene.py` freezes a separate owner-controlled scene from
an existing SE platform configuration and six-actor scene inputs. It does not
launch or install anything. Polygon admits the frozen candidate under current
human authority, reviews exact installed inputs and retains the single native
executor through setup and manual play. Use its supported qualification route
for unqualified candidate components; no direct-run workaround bypasses the board.

The legacy declaration prepares six fresh named references, holds locomotion with
SetDontMove, removes worn gear and assigns the declared contrasting human presets.
Animation/collision remain enabled. It writes `manual-observations/scene-ready.json`
only after actual identity/name/gear/hold/position/preset readbacks. This is scene
readiness, not rendered-body correctness or whole-mod acceptance. There are no
automatic transformations, save/load or physics tests after setup.

The six-person layout explicitly uses `prepared-qasmoke-anchor-v1`: its origin
and heading come from the completed common QA anchor, and each NPC moves once
relative to the actual persistent marker. Player movement or camera rotation
during setup cannot shift this layout. Current player/cell/world and marker
identity/position remain guarded, with unchanged NPC placement tolerances and
no retry after an unknown mutation. Generic player-relative creation is unchanged.

Polygon keeps its active operator turn and external microphone listener. Human
speech/text is interpreted by that operator, never directly by the sequencer.
Resolve an unambiguous current fixture name to its exact tag before publishing
one immutable JSON command into `operator-commands/000001.json`, then000002etc:

```json
{"sequence":1,"sourceRef":"actual-current-owner-command","action":"to-beast","actor":"actualFixtureTag"}
```

Legacy actions are inspect, to-beast, to-human and finish. Finish contains
only sequence/sourceRef/action. Publish complete UTF8 bytes by writing a sibling
temporary file, flushing it, then renaming to the absent final name. Never edit
published files, mint a fresh event for an uncertain action or reuse an old
scene directory. The existing companion retains exact bus delivery/completion
and guards current game/worker/world identities. A failed unknown mutation stops
without retry; completed native race and source storage reads do not prove
animation, scripted gameplay transformation or visible morph completion.

The sequence remains in the same bounded owner until explicit finish or its
original deadline. The prepared default is6900seconds held with7200seconds outer
authority; startup/restoration reserve300seconds. Announce remaining time well
before expiry; do not renew deadlines or shut down merely because setup finished.
Audio is separate: use `voice_operator` with the actual selected microphone and
current Polygon binding, keep polling, and verify fresh recognized speech. A
live audio queue cannot answer while the AI host is idle; keep Polygon active.

For isolated movement/observation in the initial Realm of Lorkhan, pass
`--initial-world-only`. That scene explicitly reports no prepared NPCs and stays
open for short move/inspect commands. Its finite game owner must not be replaced
or its frozen program edited during the session.

For a new QASmoke scene, `--native-fixture-transfer` explicitly selects the
typed native player MoveTo route to the pinned persistent Dragonborn marker.
The common executor resolves and validates the actual unloaded marker, records
one transition intent and invokes MoveTo once. Actual destination/menu/world
readiness and the west-room anchor are still mandatory afterward. A native
callback is not arrival proof. Unknown outcomes never retry or fall back to COC.
This is an alternative to the failing unpaused COC route; it is not an engine
null-light patch or an assertion that the original graphics defect is diagnosed.

## Automatic distribution and retained groups candidate

For ordinary installed body mods, keep their original preset XML files and list
their additional native category/name identities in
`configurationRequest.allowedAdditionalLoadedPresets`; see
[the exact installed-catalog contract](morph-sessions.md#ordinary-installed-body-preset-catalogs).
`catalogRequest.presets` still declares exactly the six required diagnostic
targets with their actual sexes, matching the union of the full six/twelve-base
map. Spec validation cross-checks this before any exchange. If
`wildConfigurationRequest` is present, it must include the same complete extra
identity set as the initial configuration request. Missing declared stock extras,
missing targets and undeclared catalog identities stop preparation before NPC
creation. The change does not relax per-sex morph templates, singleton mappings,
untouched automatic-origin evidence or born-beast restrictions.

The opt-in `presetMode:"automatic-stock"` observes natural assignment before
fixture name/gear inspection and never calls AssignPreset, GenActor, Clear,
Refresh or family configuration as an initialization fallback. Human actors
declare `allowedHumanPresets`. Read-only polling uses one monotonic
`automaticObservationSeconds` budget (1..30, default10) per actor, at most eight
read attempts with no deadline renewal. It requires
the real stock-internal generated event after the saved pre-creation cursor,
current provider epoch, current assignment and complete independent source reads.
Missing events/assignment remain `status:"unavailable"` in an immutable
`automatic-origin` notice, with no forced generation. It is possible to have a
mechanically usable scene and an unproven subject outcome.

Optional `wildActors` declares exactly six unique born-beast references, each
with `initialRace` equal to `beastRace`. It requires automatic-stock and
`wildOriginPolicy:"observe-natural-host"`. None is created during initialization.
Only the first actual owner `add-group/wild` creates them; no race setter is used
to manufacture a human history. The initial real assignment, complete source
reads and raw generation/caller events are preserved. Natural subject-host
adoption is explicitly `automaticOriginVerified:false` and
`naturalHostOrigin:"unverified-raw-evidence"` until an independently pinned native
caller contract establishes that attribution. A named preset or event alone
does not establish it. This does not weaken the human stock-origin witness.

Additional exact owner commands:

```json
{"sequence":1,"sourceRef":"current-owner-request","action":"remove-group","group":"humans"}
{"sequence":2,"sourceRef":"current-owner-request-2","action":"add-group","group":"wild"}
{"sequence":3,"sourceRef":"current-owner-request-3","action":"assign-preset","actor":"Human1","presetName":"Actual declared preset"}
```

`group` is exactly `humans` or a declared `wild`. Removing an uncreated wild
group is a no-op. Further add/remove operations hide/show the same witnessed
references through the typed native visibility tool; they do not create,
delete, reroll, reset presets or implicitly hide the other group. Showing
requires actual enabled/loaded readback. A failed or unknown native mutation
stops without another attempt. Hidden actors cannot be transformed, measured
through loaded-model interfaces or assigned a preset until their group is shown.
Wild actors may be inspected but never transformed into humans by this route.
An explicit assign-preset is a separate owner diagnostic using that actor's
declared pool, on the same existing reference. It retains the initial automatic
evidence and cannot retroactively prove natural assignment.

Optional complete morph measurements use `morphObservationRequestsBySex` with
exactly `male` and `female` templates. The declared sex is checked against the
actual actor. Each template contains the full actor-morph-link-evaluation
domain request, including the real family, complete mapping rows, public targets
and own key, omitting actor/captureSnapshot/stage. These three fields are filled
from the exact created reference, a unique snapshot label and the observed race.
The existing independent SKEE collector retains signed/zero/presence/per-key
source and target data. Only pristine initial snapshots assert zero prior tester
mutations; later owner diagnostics do not reuse that assertion. One legacy
`morphObservationRequest` is allowed only for a single-sex scene and cannot
coexist with the sex-specific map. No guessed common family mapping is applied.
Stored values never establish visible deformation; this route adds no camera,
renderer proof or automatic image capture.

See [complete example](manual-scene-spec.example.json), which uses deliberately
uninstalled Example fixture/preset/mapping placeholders. Replace and pin the
actual assets and native allowlist before qualification. Root spec keys are
actors, wildActors, beastRace, catalogRequest, configurationRequest,
wildConfigurationRequest, presetMode, automaticObservationSeconds,
wildOriginPolicy and either morphObservationRequest or
morphObservationRequestsBySex. Actor keys are tag, displayName, sex, base,
placement, humanRace, humanPreset, allowedHumanPresets and initialRace.
Unknown or malformed fields fail before the first game call; provenance such as
metadataProfiles belongs in a separate sidecar. A human-only legacy declaration
without presetMode preserves explicit-assignment behavior and does not prove
automatic distribution. The preparation component explicitly selects a12fixture
capacity for a declared wild group; it never expands the frozen allowed bases.
Tags are at most64ASCII identifier characters. Reference display names are at
most64characters/128UTF8bytes, contain no controls or surrounding whitespace and
are unique without case differences. Race identities must be nonzero. Placement
must satisfy the existing50..1000game-unit radius before any reference is created.
The initial configurationRequest describes the ENTIRE actual npcFormID map:
six or twelve mappings, with no subset matching. If wildConfigurationRequest is
supplied it also describes that entire same map; it can be omitted as redundant.
Twelve mappings require the frozen maximumFixtures12 opt-in. The example's
initial request contains all twelve hypothetical human/wild mappings. This does
not modify the actual distribution file or infer assignments from configuration.

These new paths are source/offline candidates. Existing successful six-human
sessions do not qualify the new native visibility,12reference capacity,
automatic-origin or owner preset interfaces. Exact installed Polygon
qualification is required, with no launch or installation implied by this guide.
