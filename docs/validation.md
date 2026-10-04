# Validation and scope

The extracted independent source passes 27 regression checks: original recovery,
PID reuse, ancestry and delayed-modal checks, plus explicit configuration,
external runtime policy, staging confinement, durable config recovery, portable
guardian imports, fixture validation before mutation, queue independence, bounded
physical publication, numeric assertions and typed post-step reference contracts.
No test in that suite launches Skyrim or SteamVR.

Fresh ZIP extraction and standard wheel installation passed 12 smoke checks
from an unrelated working directory and an isolated Python process, including
the full 27-test extracted suite. The native C++ lease harness also passed: a
complete frame survives a partial read and original expiry releases input.
Regression mutex tests use their own real Windows mutex namespace, so they
cannot contend with an independently running game test.

A clean external driver rebuild fetches 15 exact-commit SHA-256-pinned files and
the pinned OpenVR SDK header, with source/compiler/binary metadata. The known
incomplete full-history Git cache is retained; it is not needed by the builder.

`tools/build_distribution.py` emits ZIP/wheel/manifest outside Git. Use
`tools/check_distribution.py --distribution <output> --work <new external dir>`
to verify fresh extraction from an unrelated working directory, init overwrite
refusal, standard pip --no-index --no-deps wheel installation, isolated Python
imports/commands and the extracted regression suite. Installed/extracted copies
do not reference the original project path provider or journal ledger.

The predecessor support executor was qualified in a combined physical grip plus
reference/node observer session with 20 passed checks and 739 verified restoration
paths. That evidence establishes the inherited workflow, not fresh acceptance of
this packaged source. Record each independent live qualification separately,
including the exact distribution manifest, scenario, external fixture hashes,
driver build manifest, session result and restoration checks. Physics/contact
coverage depends on the separately installed data provider.

Known limits: no universal filesystem sandbox; additional mod writes require
extra_files declarations. Ordinary-radius and arbitrary controller controls are
not qualified by the enlarged-radius firewood probe. Direct DevBench input and
background OpenVR observations are not proof of physical scene input. Reliable
visual goldens require a registered capture provider. A frame command publication
has no driver ACK; tests must assert the actual game outcome. Runtime dependencies
are separately installed licensed third-party programs/mods, not bundled files.

Independent live recovery acceptance (2026-10-04): session
20261004-221841-eb9c93 deliberately exited after-ready with code99. The independent
guardian completed recovery; all738 snapshot paths were independently compared
with their pre-run state, with no restoration errors. Original fixture save
hashes were unchanged. Expected run result is failed, not a passing mod test.
This run stages no observer plugin; physics acceptance is separately qualified.

Upstream scope update: Devkit's author does not plan the full automation API.
The maintained adapter is now treated as our owned automation-backend candidate;
its qualification and prototype limitations remain unchanged by that decision.
See ownership.md for the credited provenance and exact author reply.
