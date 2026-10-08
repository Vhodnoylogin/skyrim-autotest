# Candidate boundary collection

Optional `boundary_collection` is an executor configuration value, never a mod
order property. It does not launch, authorize, retry or reopen a subject order.
Disabled by default. Source tests are not live qualification. Keep an already
qualified platform unchanged until Polygon reviews and qualifies this candidate.

The plan contains `schemaVersion:1`, the exact executor `scenarioSha256`,
`boundaryBudgetSeconds` in `(0,30]`, and1..128`requests`. Each request has:

- `id`: unique safe ASCII letters/digits/underscore/hyphen, maximum64characters.
- `after` and `before`: adjacent zero-based main-step `index`, exact `name`, and
  `stepSha256`. The hash is SHA-256 of UTF-8 JSON with sorted keys, separators
  `(',',':')`, `allow_nan=False` (see `boundary_collection.digest`).
- `review: {"settled":true,"reason":"..."}`: operator's actual review of this
  boundary. All reads at the same boundary must share its anchors/review.
- `args`: an existing semantic `player.read` or `world.read` request, without
  interpolation or executable code. Allowed world domains: subject.settings,
  hand.held_item, inventory.quantity/alchemy, body_slot.settings/display,
  reference.state/physics. Held reads require continuityWindowSeconds0.
- `timeout`: finite seconds in `(0,20]`, also bounded by the shared boundary
  deadline. No polls, retries, setters, startup handling or race scheduling.

The scenario bytes are captured once and validated before recovery/preflight.
Every anchor is checked against the complete scenario, including arguments and
assertions, before setup and again before boundary dispatch. No main step is
inserted, skipped, renamed or counted as additional subject coverage.

Reads execute serially only after the declared main checkpoint succeeds and
before its immediate successor. **Additional latency changes wall-clock timing.**
Only separately reviewed settled boundaries are eligible. Never insert reads
inside a physical stroke, narrow native task/callback race, first-render-frame
interval, or any time-sensitive assertion. Successful structural validation is
not a safety review. The fixture/scenario author owns semantic placement; Polygon
owns qualified tool configuration and launch authorization.

`boundary-collection-plan.json` and `boundary-collection.json` persist the exact
plan and every request from the beginning, including never-reached requests.
Each issued request produces `boundary-<id>.json` with the request/anchors, host
monotonic timestamps, executor game PID/birth/world epoch, known reference tags,
lifecycle/native subject cursors and the **unchanged actual response/error**.
These files are copied and hash-verified into the ordinary final evidence
manifest; restart segments do not finalize pending reads. A final interrupted
started read remains unavailable, retaining any uncommitted raw envelope.

Accounting statuses are `not_run`, `started`, `response_recorded`, `unavailable`.
`response_recorded` means a timely identity-bracketed response was retained; it
does **not** assert provider availability or subject correctness. A raw unavailable
domain remains unavailable. If a shared deadline expires before dispatch, the
request stays not_run with a reason and is never replayed later. A read error,
identity/generation change, stale lifecycle or late response records unavailable
and stops technical execution; no arbitrary error is silently swallowed.

Host sequence/clock and executor epoch are labeled as such. They do not supply
missing native timestamps, complete ownership transitions, controller-consumer
acknowledgements, native engine/render/physics frames or an atomic snapshot.
Returned provider phase/availability/identity are preserved without inventing
missing fields. Body's native callbackFrame is not an engine/render frame.

An origin separately maps requested-data clauses to their precise raw evidence,
partial coverage and missing subclauses. This collector never promotes observed
steps, whole collect clauses, release gates or deferred headset checks to passed.
Old results are immutable: no historical response can be manufactured by adding
a plan now. New coverage needs an origin-authored targeted scenario with valid
authority; do not repeat a successful complete regression solely for collection.

Minimum live qualification: a small settled fixture, at least two safe boundaries,
two reads at one boundary, actual provider fields/availability, same-tag incarnation,
native identity and lifecycle cursors, timed raw envelopes, unchanged main checks,
final manifest digests and full restoration. Error/expiry/interruption/mismatched
anchors are covered offline; intentional native fault injection is a separate
authorized test. Never borrow subject acceptance from that tooling qualification.
