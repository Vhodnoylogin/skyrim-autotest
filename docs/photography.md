# Disposable NPC photography (0.2.3 candidate)

The executor now supports generic tagged NPC creation, stationary configuration,
keyed NiOverride storage/model updates, measured camera framing, original PNG
capture and restoration. There is no subject-name routing. All64requests and
assertion fields in the current photography order translate without modifying
that order. **This is source/offline support, not live qualification.** Do not
select a passed Polygon platform manifest until its exact native/code/config
and capture-source semantics have independently passed in the actual game.

Operator configuration, outside Git:

```json
{
  "fixture_actor_base_allowlist": [
    {"plugin": "fixture.esp", "localId": "000801"},
    {"plugin": "Skyrim.esm", "localId": "023ABC"}
  ],
  "photography": {
    "captureProvider": "ACTUAL_REGISTERED_PROVIDER",
    "distanceGameUnits": 1600,
    "maximumPhotos": 16
  }
}
```

Replace the capture key with an actually registered provider discovered using
`capture {"kind":"extensions"}`. Pin its installed DLL/configuration separately
in the operator's qualification evidence. An example string is not provider
discovery. `auto` and `native` are refused. The existing vanilla fallback is not
qualified for this contract: recorded manual captures were1376x1472 with UI
included. No enlargement, pixel synthesis or degradation waiver is performed.
Provider absence, insufficient native resolution or unsupported PNG encoding
must remain a blocked tool finding. Never install another graphics framework
into the owner's profile merely to make a capture pass.

`distanceGameUnits` is an operator-selected camera distance, not a measured actor
size, FOV or an acceptance tolerance. The native bound/projection must actually
fit with the requested margin. If it does not, the attempt stops; prepare and
qualify a different tool configuration before another authorized run. Once a
comparison group has a successful baseline, its camera command/projection is
retained unchanged for the altered variant. Changed actor position/orientation,
camera/projection or image dimensions reject the pair; no automatic reframing.

## Providers and measured data

Build the separately acquired DevBench fork with our read-only
`PhotographyReadback.cpp/h` integration. The pinned CommonLib correction is
required. `tools/apply_devbench_photography.py` stages only these owned source
files and one registration seam on exact fork base
`d6630ddd672bef22bf2121944fb2c7b8ffec4f1c`; dependencies stay outside Git.
The prepared compiled DLL/PDB are not installed automatically.

Reacquire/build the published exact candidate outside Git:

```powershell
python tools/build_devbench_fork.py --photography --build-dir C:/TestBuilds/photography
```

Fork commit `5ff3d711fcc6f35ef5427443551fae5c512c153d` adds only read-only
measurements/registration to the existing runtime-fixture fork. This recipe
runs native regressions but cannot establish live renderer equivalence.

`photography_readback` runs in a bounded main-thread task and returns actual
actor restraint, AI process flag, native CFilter no-collision flag (only with
a loaded character controller), pose and scene-root bound; normal UI/modal/pause
and freeze state; camera-root and primary NiCamera world transforms, projection,
frustum, both eye frustums and viewport. It projects the enclosing bound's8cube
corners through the actual primary matrix. A wholly projected bound inside the
requested margin is geometric `inFrame`, not occlusion, ears/tail recognition,
or pixel visibility. Collision enabled is a native flag, not a contact assertion.

Primary camera projection is **not assumed** to be equivalent to a capture
provider's eye/crop. Live qualification must prove that correspondence with
visible nearby geometry and stereo/source inspection. Readback is a main-thread
sample, not a renderer fence. Before/after agreement brackets capture; it does
not attest every intervening rendered frame. `photo.camera.matchesReadback`
means measured bracket agreement. Pixel/view qualification remains separate.

Morphs come from actual keyed `NiOverride.GetBodyMorph`; expected coefficients
are compared with them, never substituted. Model update means native function
completion and loaded-incarnation continuity, not proof of TRI deformation or
the renderer consuming the latest mesh. The source chat must inspect photographs.

## Custody and restoration

`create_fixture_actor` allows at most16 unique tags/bases from the operator's
allowlist. It resolves a real NPC base, records intent before one PlaceAtMe,
retains the actual newly returned dynamic reference, positions it relative to
the observed player and records Observer session/generation/handle/base.
Uncertain completion never spawns a duplicate. Later reads/mutations retain
this exact incarnation and common gameplay/lifecycle guards.

`configure_fixture_actor` restrains voluntary movement, sets aggression0 and
stops combat while requiring actual AI and collision flags to remain enabled.
No AI/collision/time disabling, `tai`, `tcl`, `tfc`, input/focus or player mutation
is used. Other actors/physics may still move a restrained NPC. Morph changes use
the order's own key; clear/update/readback are explicit scenario actions. Do not
reuse a key belonging to an existing mod or owner save. Disposable profile/save
restoration remains the ultimate cleanup after uncertain in-memory operations.

Framing uses DevBench's owned `vr-state` free camera. Original state/UI are
recorded before entry. Exit verifies restoration to the original camera state
and unchanged UI; HUD is excluded by the pixel provider rather than toggling
menus. Common cleanup attempts safe owned-camera restoration before game exit
after failed photography. Failure cannot prevent process/file restoration.
An uncertain restore is not automatically replayed or reported successful.

Each photo has durable intent before a single capture call. A lost response,
partial setter, existing output path or previously attempted photo stops rather
than replaying. PNG bytes/CRC/complete encoded pixel stream, size, original
resolution, provider receipt/UI exclusion, actor pose, keyed values and camera
are checked. Raw receipts and partial originals remain external. Non-default
scene scaling/degradation is rejected by DevBench/provider gates.

Ordinary collection includes hash-pinned originals, measured metadata,
`photography.json`, `photography-index.json` and a derived contact sheet.
The index lists every planned photo, including `not_run`/uncertain entries, and
links groups/pairs; blank preview cells are not successful screenshots. The
contact sheet alone uses thumbnails. Original images are never resized/edited.
Provider/binary/configuration, profile/build pins and the overall attempt's
restoration/coverage remain in the standard Polygon/executor evidence.

## Required live qualification

Polygon owns the qualification session and the subject photography session.
The development chat supplies source/builds/plans and never runs that subject
order or services its microphone. Preserve the immutable mod order and current
selected platform while preparing a new candidate.

1. In a separate authorized disposable tool session, discover the real capture
   provider and original dimensions; verify UI exclusion and no source resize.
2. Verify spawned NPC identities, restraint with enabled AI/collisions, keyed
   zero/nonzero readback and clear/update, while the game keeps advancing.
3. Inspect real images for forward/right/back/left camera motion, whole actor,
   ears/tail margins, no obstructing player/second actor, provider-eye/crop
   correspondence and stable paired FOV/background/lighting/actor pose.
4. Verify paired original resolution>=1920x1080, differing real shape when a
   supplied TRI morph changes, metadata/image hashes and no repeated capture.
5. Exit free camera, verify normal VR rendering/input, no freeze/UI leak, ended
   attempt, complete collection/native restoration and archived temporary profile.

A changing camera state/ACK, successful compile or unit test alone cannot pass
this list. Native source support deliberately does not create a fake passed
qualification manifest. Only afterward may Polygon freeze a new platform and
execute the unchanged subject order under its current owner authorization.
