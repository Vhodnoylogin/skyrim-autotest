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
