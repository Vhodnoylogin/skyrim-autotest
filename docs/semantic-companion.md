# Held execution of an unchanged semantic order

`tools/prepare_semantic_companion.py` prepares a separately pinned standalone
program for an original `polygon-actions/1` order. It does not rewrite that order,
change its hashes, qualify a platform, select an owner, launch Skyrim or alter an
installed/frozen executor. The Dashboard owns operator admission and collection.

The inputs are the exact canonical stored order, selected mapping manifest, and
native scenario produced by the Dashboard's `subject_contract.compile_plan`.
Preparation independently repeats its data substitutions and refuses a different
compiled scenario, changed assertion, missing field mapping or reordered step.
The selected executor's normal scenario validator also checks the compiled input.

```powershell
python tools/prepare_semantic_companion.py --order C:/Bench/operator/original-order.json --mapping-manifest C:/Bench/operator/manifest.json --compiled-scenario C:/Bench/operator/compiled.json --output C:/Bench/operator/new-held-bridge --maximum-seconds 600 --maximum-commands 2048
```

Use a new external output folder. The output contains the semantic spec,
transport execution plan, standalone sequencer and preparation manifest. Every
input and generated file has a hash; the manifest separately pins the interpreter
source. It explicitly records no launch, admission, qualification or acceptance.
Changing data requires a new output folder, not an overwrite of frozen evidence.

`semantic_companion.render(spec)` deterministically materializes the standalone
source and canonical JSON data. Dashboard can independently recompute it using
the separately pinned interpreter source, without importing new code into the
qualified executor. Its equivalent read-only preparation entry point is:

```powershell
python C:/Bench/pinned/semantic_companion.py --render-spec C:/Bench/operator/semantic-spec.json --output C:/Bench/operator/new-sequencer.py
```

The runtime entry point is `run_plan(spec, exchange, emit)`. It uses only the
existing companion callbacks to reach the game. Each original step keeps its
name, arguments, assertions, timeout, polling declaration and original testing
role. Assertions use the native scenario JSON semantics: booleans remain distinct
from numbers inside containers, unknown numeric observations do not become zero,
and missing fields do not satisfy a numeric or missing-value assertion. The
interpreter contains no mod names, morph formulas, actor identities or source
catalogs.

Each mutation is sent once. Only declared read steps may poll, within the first
absolute step deadline and the existing session window. Intermediate responses
remain complete raw measurements; final assertions are emitted once. A response
received after its step deadline is unavailable. Unknown transport/action outcomes
stop immediately without replay or another native command. A known assertion
mismatch marks the remaining steps not run and sends one ordinary finish while
the original window remains valid. Native lifetime/restoration stays with the
existing executor and guardian.

The supported bridge surface is generic read/typed object operations over the
existing `platform`, `inspect`, read-only `menu`, and frozen raw-Papyrus read
allowlist. Console/startup, audio, direct physical input, unresolved `$state`
selectors, raw scripted mutations and unowned save/load routes are refused.
Common startup is completed before the companion attaches.

## Original roles and factual subject start

The unchanged companion protocol requires every wrapper case to use
`role:"subject"` and identifies its first actual delivery as `subjectStart`.
Those are technical transport boundaries. They must not be projected as the
original mod's subject boundary when earlier original steps are fixture work.

The pinned spec retains `subjectOrderSha256`, the exact `originalTesting` roles
and start checkpoint, the exact compiled scenario and provenance input pins.
The transport plan keeps every original name in order. Only standard
`check-start`, `measurement`, `assertion` and `check-result` records are emitted.
Check-result metadata includes `semanticRole`, `semanticResult` and `stepIndex`.
An original observation-only step remains `semanticResult:"observed"`; its
wrapper uses only an explicitly labeled `assertionRole:"transport"` receipt.
Actual original assertions have `assertionRole:"semantic"` and retain their exact
native rule, extracted value, availability and expected value.

The Dashboard held-plan collector must independently recompile the unchanged
order/mapping, inspect actual native-delivered measurements and recompute its
assertions. It uses the original testing checkpoint's actual delivery for factual
mod-test start and preserves the original fixture/tooling/subject roles. It must
never trust a wrapper's early `subjectStart`, promote an observation receipt to
passed business coverage, or treat bridge metadata as an independent oracle.
This operator adapter is required; ordinary generic native scenarios run before
the held interactive session and cannot supply its durable command identities.

Preparation tests prove deterministic rendering, unchanged input bytes, exact
compilation and assertion parity. Interpreter tests cover read-only polling,
observation-only steps, unknown values, deadline expiry, known mismatches and
uncertain mutations. A real local durable-bus test exercises the existing
companion protocol with the generated standalone source. These are offline tests,
not evidence that the subject's numerical or rendered behavior passed in a game.
