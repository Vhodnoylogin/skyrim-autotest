# Optional SE crash evidence

`crash_capture` is an explicit diagnostic option for one owned SE run. It does
not launch another game, replay a failed action, qualify a subject, change the
Windows registry or install a crash handler. A previous crash without a dump
has an unavailable cause; another run requires its own Polygon admission.

Before considering another game run, inspect existing `%LOCALAPPDATA%/CrashDumps`
and Windows Error Reporting records. Match the exact Application Error/WER event
and record IDs, PID, full process birth and executable path to the owned run.
Validate the dump's `MDMP` signature, MiscInfo PID and process-create time
(at its recorded seconds precision), header UTC timestamp and loaded module
identity against that evidence. A filename containing a PID alone never permits
adoption. Copy the matched dump outside Git and verify stable source/copy SHA-256
hashes before offline analysis or another launch; retain the original evidence.
Inspecting existing dumps requires no registry or crash-handler changes.

The operator acquires Microsoft's Windows Debugger (WinDbg) from its official
distribution and independently records the exact local `amd64/cdb.exe` and
support DLL SHA-256 values. These external Microsoft binaries are never bundled
in this repository. See [Microsoft's acquisition instructions](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/).

An explicit top-level configuration has this shape (replace every path/hash):

```json
{
  "crash_capture": {
    "provider": "cdb",
    "executable": "D:/External/WinDbg/amd64/cdb.exe",
    "sha256": "64 hexadecimal characters",
    "supportFiles": [
      {"path": "D:/External/WinDbg/amd64/dbgeng.dll", "sha256": "64 hexadecimal characters"},
      {"path": "D:/External/WinDbg/amd64/dbghelp.dll", "sha256": "64 hexadecimal characters"}
    ],
    "maximumAttachSeconds": 15
  }
}
```

Pin `dbgcore.dll` and `symsrv.dll` as additional support files when present.
Only those four known DLL names beside `cdb.exe` are admitted. No caller-supplied
debugger arguments, scripts, process names or exception-handling commands are
accepted. The tool remains external and exact pins are checked before spawn.

The runner calls `crash_capture.start(session)` after its ordinary owned launch
and before preparing gameplay or selecting NEW. The module writes durable
intent, creates a fresh `RUN/crash-capture` directory and attaches once using
the exact recorded PID, process birth and executable. The hidden subprocess
uses no shell, children, remote debugger, registry installation or network
symbols. `-pd` prevents debugger exit from terminating the target; `-G` ends
the debugger when the target ends. The fixed command file sets second-chance
filters for access violations, C++ exceptions, the wildcard and the named `sbo`
event (`0xC0000409`), prints the effective filters and a readiness marker, then
continues. The debugger's built-in named `sbo` filter takes precedence over the
wildcard; setting only the wildcard does not install its capture commands.
An exact live debugger, unchanged owned game and a fresh DevBench health reply
are required before startup continues. A missing marker, changed identity,
changed tool or expired original deadline stops admission; it never reattaches.

The fixed filters have empty first-chance commands and capture commands only
on second chance. They leave first-chance handling to the application and never
swallow an exception. An unhandled second chance records the exception, registers,
stack and one full-memory minidump, then uses `gn` to pass the exception as
unhandled. It does not convert a crash into a normal exit. Full dump creation
can pause the failed process and use substantial disk space; the ordinary run
and cleanup deadlines remain in force. Perform symbol/source analysis offline.
Microsoft documents [second-chance filters](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/sx--sxd--sxe--sxi--sxn--sxr--sx---set-exceptions-),
[CDB lifetime options](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/cdb-command-line-options),
and [unhandled continuation](https://learn.microsoft.com/en-us/windows-hardware/drivers/debuggercmds/gn--gn--go-with-exception-not-handled-).

The capture sequence retains `.exr -1`, attempts `.ecxr`, then prints registers
and the current stack before writing the dump. Some fast-fail events do not
support `.ecxr`; the actual conformance run reported exception-context retrieval
failure while still recording the raw exception, registers, current stack and
full dump. Preserve that diagnostic and every remaining artifact. Do not label
the printed current context as a successfully restored exception context.

After the owned game has ended, the runner calls `crash_capture.stop(session)`
before ordinary collection. It gives `-G` a bounded opportunity to exit and may
then close only the exact owned debugger, never a target or reused PID. An
unknown debugger identity blocks that process action. The serializable
`state.crashCapture` retains intent, identities, fixed script/tool pins, readiness,
actual exit information and hashes of all retained logs/dumps. A transient Popen
object is not written to state. Logs are retained even when no crash occurs;
`dumpObserved` means a dump file exists, not that its cause has been analyzed.

The authored [native probe](../tests/native/crash_capture_probe.cpp) supports
real debugger conformance without a game. In an x64 MSVC developer command
prompt, compile it in a fresh external output directory:

```text
cl /nologo /Od /Zi /EHsc /W4 ABSOLUTE_SOURCE_PATH /Fe:capture-fixture.exe /Fo:capture-fixture.obj /link /DEBUG /PDB:capture-fixture.pdb
```

Launch that fixture in its own fresh directory, attach the fixed capture once,
wait for the actual ready marker and live debugger, then create `go.flag`.
The fixture handles one first-chance access violation (`handled.flag`), then
raises an unhandled access violation. Require one actual second-chance record,
a parseable dump and actual `0xC0000005` target exit.

For a separate fast-fail case, use another fresh fixture directory and create
`fastfail.flag` before `go.flag`. After the handled first-chance access violation,
the fixture writes `fastfail-entered.flag` and invokes
`__fastfail(FAST_FAIL_FATAL_APP_EXIT)` (subcode 7). Require `handled.flag`, the
fast-fail entry marker, one actual second-chance capture marker, an exception
record with code `0xC0000409` and parameter 0 equal to 7, a parseable dump and the
actual `0xC0000409` target exit. Verify the effective named `sbo` filter rather
than assuming wildcard commands cover it.

For the detach counterproof, use a third fresh directory and create
`survive.flag` before launch; after debugger readiness terminate only the
exact owned debugger, require the target still alive, then create `go.flag`.
Require `handled.flag` and `still-alive.flag`, create `exit.flag`, and require
target exit0. The fixture's waits are bounded20seconds. Health in such an offline
probe must be labeled fake; it establishes debugger behavior, not DevBench or
game qualification. Retain the source, compiler recipe, tool/input hashes,
actual logs/dump and receipt externally. The ordinary Python suite uses fake
processes and never silently acquires or attaches a debugger.

The retained external conformance receipt from 28 October 2026 passed all three
authored-process cases: unhandled access violation, deliberate fast-fail and
debugger detach with target survival. It records zero game launches. This proves
the tested debugger/fixture behavior only; neither `0xC0000409` nor a matching
fast-fail subcode identifies the cause of an actual game failure.

The runner integrates this option before gameplay preparation and collects it
after confirmed game end. Exact distribution and owned-game qualification
remain separate from the offline debugger conformance. Merely reading this
page grants no launch or attach authority.
