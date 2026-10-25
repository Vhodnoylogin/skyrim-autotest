# Morph-preset semantic candidate

This 0.3.8 candidate is integrated into the semantic backend but not live-qualified.
The working 0.3.7 SE baseline and its frozen package remain unchanged. It selects operations by
semantic quantity/action, never by a subject mod name or caller-supplied Papyrus
script/function. The backend binds the exact declared CLAWDistributionNative API;
its actual global/native parameter and return metadata is checked before a call.

Reads: world.read quantity morph-preset-catalog with sex male/female; quantity
morph-preset-state with actor {reference,base}. Results are catalog.presetNames
and preset.{name,status,statusName,lastError}. An empty catalog has ambiguous
availability and is not certified as a valid empty catalogue.

Actions: assign-morph-preset(actor,presetName), clear-morph-preset(actor),
configure-morph-link(actor,profile,rows), disable-morph-link(actor),
refresh-morph-preset(actor). Each row has
sourceMorph,targetMorph,gain,cap;1..32 rows become equal-length string/string/
float/float arrays. Caps are in(0,1], gains finite native floats. No raw VM fields
are accepted. Native subject validation still owns supported target morphs.

Every mutation executes once and returns action.admitted only. A true Boolean
is queue admission, not completion. Read preset state separately; status2 means
coefficients read back and model update requested, not rendered geometry. Pending,
error, unloaded, unknown and provider-unavailable states remain factual values.
Actor identity/session/generation checks bracket requests; state reads are
sequential, not atomic. An uncertain mutation is never automatically retried.

Independent coefficient assertions use existing body-morph-storage reads via
NiOverride.GetBodyMorph(actor,morph,key), not the subject cached GetOwnMorph.
The actual SKEE composition and float-array argument ABI require their first
real probe. No float-array return is used by ConfigureMorphLink (it returns Bool).
Neither source tests nor added selectors certify provider behavior, geometry,
save/load, platform activation or a game launch. Polygon must separately freeze
and qualify the exact composition before using new semantic mappings.
