# Read-only subject state binding

Some tests require effective settings or private assignment counts that a
launcher cannot infer from a configuration file. A configuration write receipt
proves bytes, not that the subject loaded or applied them. Until a native
provider is installed and qualified those observations remain unavailable.

The executor integration uses DevBench's existing inspect extension ABI, with
no additional server, test mode or mutation endpoint. The subject exposes its
ordinary effective state through a read-only extension; a separately qualified
platform configuration binds the subject's stable name to that extension key.
The executor must not dispatch by hardcoded mod names or reconstruct private
state from requested values, file contents or log absence.

A provider snapshot should include schema version, provider identity/version,
process identity, load generation, frame/sample identity, availability and units
alongside effective settings and runtime counts. Copy native state in one
bounded main-thread task with the subject's synchronization; listener threads
must not dereference world pointers. Loading, incomplete initialization or
missing state is explicitly unavailable. Never substitute built-in defaults.

For the current Body Pouches preparation the requested data are effective
language/log level/mayEnableSlots and the loaded pouch slot/mode list, actual
input handedness, and the actual number of runtime assignments. The source file
alone cannot supply these facts. A native provider addition changes the subject
binary, so its origin must supply a new immutable order with actual new pins;
existing order19 and its historical preparation results remain unchanged.

The consumer is implemented in `subject_state.py`. Configure
`subject_state_bindings` with a stable subject name and `inspectKind`. It requires
the exact owned PID/birth, a fresh increasing sample sequence, native lifecycle
epoch, available current-generation callback state and explicit units. A replay,
missing field or unavailable native state fails rather than using defaults.
Actual VRIK suspension must be read for all fourteen valid slots, independently
of configured pouch membership; an empty pouch list does not prove suspension=false.

The Body Pouches origin has prepared native candidate0.1.11, including all-slot
reads, in its own repository. Neither this consumer nor that native candidate
has been qualified together in a game. Installed0.1.10 and order19 stay unchanged.

Optional write binding fields are `settingsDestination` (overwrite-relative
SKSE/Plugins JSON), `handednessProfileIni` (skyrimprefs.ini or skyrimvr.ini),
`bodySlotsDestination` (overwrite-relative INI), and `bodySlotsSource` with an
external immutable `path`/`sha256`. Configuration declares exact overwrite
targets and temporary files for prelaunch snapshots. Slot overrides always derive
from that baseline, including subsequent empty variants. The restart action stops
the owned game/loaders, writes once while they are absent, relaunches once through
the same MO2 and completes common owned-save loading/gameplay readiness. It then
reads actual native settings; successful writes are not proof of application.
Every temporary variant's bytes are manifest-pinned before restoration. A failed
write prevents relaunch, retains intent/backups and cannot replay the transition.

Qualification must verify real native values (including empty pouches/zero
assignments/all-slot suspension), fresh identity after restart, effective
handedness and physical-hand routing, and exact settings/profile/save restoration.
Configuration is operator-owned and frozen separately from the subject order.
