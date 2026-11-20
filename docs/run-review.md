# Per-run executor review

Autotest logs phase transitions, Bridge launch acknowledgements and tool
results as an owned session runs. Its terminal report writes `run-review.json`
alongside the original `result.json` and `steps.jsonl`. The review separates
scenario checks, the exact native exit when available, collection and restoration.
The original logs remain the evidence for mod behavior and thread ownership.

To review a run made with an earlier or frozen executor, point the current
source at the retained run directory. This only reads the files.

```text
python -m skyrim_autotest.run_review <run-directory>
```

The review summarizes error counts by phase, tool and HTTP status. It leaves
request bodies and full responses in the original ledger. Observed failures can
produce improvement candidates for launch, transport, shutdown or evidence
collection. These candidates describe what the executor could expose or verify
better. A clean run can have no candidates. A missing log or unavailable exit
code appears explicitly in the review.

Queue waits, readiness and recovery come from the corresponding executor
events. A recovery requires a ready observation in the same phase as the wait.
Explicitly abandoned startup reads appear by tool and phase. An HTTP status
alone gives no evidence that the request started or was abandoned.
New requests carry a local identifier in the step ledger. The review can
link a gateway error to the recorded abandonment decision for that same
request. Older unlinked errors stay unresolved even if the same phase
contains a later success or an abandonment for a different request.

For a retained nonzero exit on Windows the terminal report also reads a bounded
Application Error Event 1000 window around the first observed exit. A match
requires the same executable path, PID, process creation time and exception
code. The review keeps the event record number, timestamp, module basename and
fault offset. The event describes where Windows observed the exception. The mod
or engine component that caused it requires separate evidence. An unavailable or
missing event does not change the scenario result, native exit or restoration.

The default replay uses the saved correlation. Add `--query-windows-fault`
to inspect a retained run with the current machine's event log. This performs
one read and leaves the original run directory unchanged.

`collectedGameFaults` summarizes a fresh CrashLogger artifact when the final
collection manifest and copied log hashes agree, the recorded PID matches
the owned process, and the log modification time falls within its lifetime
and near exit. The report keeps the exception, fault location and up to eight
probable stack positions. It leaves raw stack and system data in the collected
log. CrashLogger and Windows Application Error are independent sources. The
summary can preserve diagnostic evidence even when the process exit code is 1
and Windows reports no matching Event 1000.
