# Owned game exit observations

Every ordinary owned run captures a read-only Windows process handle after a
fresh DevBench health PID matches the exact observed owned game. The retained
handle is verified by PID, process creation time and image path through that
same handle. A later reused PID cannot become the observed process.

The executor records `game-process-observation` events and
`state.json` / `result.json` `gameProcessObservations` at attachment, before
cleanup, after owned processes end and in cleanup's final block. The Markdown
report includes the final status and hexadecimal code. This is ordinary logging;
a self-test order is not required. Restarted games have distinct observations.

`status` is `running`, `exited` or `unavailable`. A zero-time handle wait decides
whether the process ended; exit value259 is not mistaken for a still-running
process after a signaled wait. Available exit codes are unsigned32-bit values,
with `exitCodeHex`. Missing access/query data stay explicitly unavailable.

An exit code records OS process completion, not its cause. It does not identify
a mod, prove a crash or attribute a user/external close. Compare stage, the
executor's actual action log and any separately available crash evidence.
An API disconnect alone is not a crash classification.

The observer opens only read/query/synchronize rights, never terminates a process,
and closes in `finally`, including failed cleanup. Diagnostic failures cannot
replace an execution/restoration error or authorize another game start. A game
that exits before an exact live identity/handle was captured may have no code;
old runs cannot acquire missing exit evidence retrospectively.
