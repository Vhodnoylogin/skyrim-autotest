# Owned launch followed by manual inspection

`tools/prepare_manual_scene.py` freezes a separate owner-controlled scene from
an existing SE platform configuration and six-actor scene inputs. It does not
launch or install anything. Polygon admits the frozen candidate under current
human authority, reviews exact installed inputs and retains the single native
executor through setup and manual play. Use its supported qualification route
for unqualified candidate components; no direct-run workaround bypasses the board.

The sequencer prepares six fresh named references, holds locomotion with
SetDontMove, removes worn gear and assigns the declared contrasting human presets.
Animation/collision remain enabled. It writes `manual-observations/scene-ready.json`
only after actual identity/name/gear/hold/position/preset readbacks. This is scene
readiness, not rendered-body correctness or whole-mod acceptance. There are no
automatic transformations, save/load or physics tests after setup.

Polygon keeps its active operator turn and external microphone listener. Human
speech/text is interpreted by that operator, never directly by the sequencer.
Resolve an unambiguous current fixture name to its exact tag before publishing
one immutable JSON command into `operator-commands/000001.json`, then000002etc:

```json
{"sequence":1,"sourceRef":"actual-current-owner-command","action":"to-beast","actor":"actualFixtureTag"}
```

Supported actions are inspect, to-beast, to-human and finish. Finish contains
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
