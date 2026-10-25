# Owned native14 reads and controlled qualification

The optional executor-local `native14` step combines typed observations with the
existing owned game session. It is a candidate for controlled qualification, not
evidence that a particular DevBench/VRIK/Body Slots combination has run in game.
The offline file validator remains independent; see [native14](native14.md).

## Operator policy and expected modules

Add `native14_live` to an external VR executor configuration:

```json
{
  "native14_live": {
    "maxAgeMicros": 2000000,
    "pollIntervalMs": 50,
    "modules": [
      {"path": "C:/ActualDeployment/devbench.dll", "sha256": "REPLACE_WITH_EXACT_SHA256"},
      {"path": "C:/ActualDeployment/VRIK.dll", "sha256": "REPLACE_WITH_EXACT_SHA256"},
      {"path": "C:/ActualDeployment/BodySlots.dll", "sha256": "REPLACE_WITH_EXACT_SHA256"}
    ],
    "absentModules": []
  }
}
```

These are illustrative paths, not an installation recipe. Replace them with the
exact expected loaded module paths and hashes from the separately frozen actual
deployment. Configuration can be checked before staged targets exist. Runtime
checks require actual module inventory and readable files at those paths; they
never hash an unrelated source archive/build as a fallback. To qualify legacy
absence, omit the BodySlots pin and explicitly declare `absentModules:["BodySlots.dll"]`.
Do not change installation or policy during a run.

From the exact candidate's source directory, an optional offline combined check is:

```text
python -B -m skyrim_autotest --config EXTERNAL_CONFIG.json config-check --scenario EXTERNAL_SCENARIO.json
```

It checks syntax, VR target, required observation policy and reserved restarts
without recovery/setup/launch. Native14 steps/postSteps without a valid VR policy
are also refused by the runner before recovery or setup. This check does not
inspect a live module and does not replace Polygon's admission/qualification-check.

The reader brackets native module inventory and stable on-disk file hashing with
the exact owned process identity. This establishes inventory and disk-image
evidence, not a hash of executable memory or proof that no runtime hook exists.
Missing/duplicate/unreadable modules, wrong paths/hashes or an expected-absent
module invalidate the read. File and endpoint checks can take time: use settled
boundaries, never insert them into a time-sensitive stroke or callback race.

## Scenario reads

The request contains measurement aliases, with optional immutable evidence tags
and a named baseline. For example, these generic sequential technical checks can
run after the mandatory common gameplay bootstrap:

```json
{
  "schemaVersion": 1,
  "steps": [
    {
      "name": "Read the qualified owned producer",
      "tool": "native14",
      "args": {
        "tag": "before",
        "select": {"placementSource": "frame.placementRead.source", "enabled": "frame.holstersEnabled"}
      },
      "assert": [{"path": "available", "equals": true}]
    },
    {
      "name": "Require another complete native frame",
      "tool": "native14",
      "args": {
        "tag": "after",
        "baseline": "before",
        "transition": "same-context",
        "haptics": true,
        "select": {"placementSource": "frame.placementRead.source"}
      },
      "assert": [{"path": "available", "equals": true}]
    }
  ]
}
```

This example checks the observation path, not mod correctness or a positive
haptic request. Declare fixture/cell, factual testing boundary, collection and
expected subject observations separately in the actual operator/origin plan.
Game startup and world loading belong to the common executor, never these steps.

`transition` is `same-context` by default. An explicit `new-load` requires a named
baseline, a new load generation and advancing frame serial. `new-body` requires
the same load and a new body generation; its frame serial may stay equal according
to the producer contract. Both compare with the stream cursor as well as the
named baseline; a historical tag cannot manufacture another transition.
Native generations are the producer's identity proxies, not proof of every
model/subnode lifetime. Controlled fixtures remain necessary.

Only known pending responses or otherwise valid duplicate frames are sampled
again within the original deadline. Errors, malformed data, unknown/unavailable
outcomes, identity failures or unexpected context changes are not replayed.
Every response remains logged; no tag/cursor is committed before all guards and
selected measurements succeed. The age bound includes a conservative host-time
allowance for the read and subsequent checks, not only producer age at copy time.

Polling a plain selector read is allowed. Polling cannot create tags, request a
named transition or consume a haptic interval. Complete raw responses remain in
the normal logs; the returned `observations` contain only mask-checked values.
The owner/game bootstrap, native endpoint/process and world epoch are checked
before/after. There is no command to attach this reader to another runner's game.

## Project admission, restoration and actual readiness

In the Skyrim-Polygon project use the existing shared root and its independently
reviewed candidate qualification path. The operator prepares a NEW bounded plan;
never edit an already frozen packet or copy an old launch allowance:

```text
python PATH_TO_DASHBOARD/polygon.py --root SAME_SESSION_ROOT qualification-register NEW_REQUEST.json
python PATH_TO_DASHBOARD/polygon.py --root SAME_SESSION_ROOT qualification-check NEW_ID
python PATH_TO_DASHBOARD/polygon.py --root SAME_SESSION_ROOT qualification-run NEW_ID
python PATH_TO_DASHBOARD/polygon.py --root SAME_SESSION_ROOT qualification-collect NEW_ID
```

These are future operator commands, not authorization. Admission needs actual
human scope, independently reviewed launch accounting, an exact frozen candidate,
profile/fixture/inputs and the same shared session/installation barriers. Existing
holds require their established clearance path. A second root or direct standalone
`run` command must not bypass that admission. Standard subject tests remain the
origin's scenarios/analysis, operated through the agreed session owner.

On interruption the operator uses `qualification-recover NEW_ID` after proving
its worker dead, then collects. Review successful result, actual launch count,
native completion, `restored:true`, restore errors, archived/removed copied
profile, source selection, inputs and original saves/settings before an explicit
`qualification-release NEW_ID TECHNICAL_REVIEW.json`. The Dashboard's current
docs/tool-qualification.md is authoritative for exact request/review fields.
Do not invoke ordinary queue dispatch, release old batches or clear uncertainty
automatically. Outside that project the executor's documented bounded run/recover
owns its session; that standalone path is not a project workaround.

Source/offline tests support readiness to attempt controlled qualification. Live
qualification must still show exact modules/endpoint, complete advancing frames,
owned load/body invalidation, intended physical input/readback and restoration.
Scene-graph state and native haptic requests do not prove pixels, hardware pulse
delivery or equipment transactions. This reader creates no order, installs no
subject DLL and leaves all prior platform pins untouched.
