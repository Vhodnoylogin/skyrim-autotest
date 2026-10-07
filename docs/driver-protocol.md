# Physical driver protocol v2

This is our adapter interface, built over externally acquired pinned driver
sources. A frozen platform using protocol v1 must keep its matching binary and
client. A source update does not upgrade an installed platform.

The ASCII frame starts with `SKYRIM_AUTOTEST 2`, then owner token, sequence,
Windows boot tick milliseconds, lease milliseconds and command token. Both
tokens are 32 lowercase hex characters. Sequence is positive and below 2^63;
lease is 1..5000 ms. Three poses follow (position XYZ metres and unit quaternion
WXYZ); each controller additionally has unsigned 64-bit pressed/touched masks
and ten axes in [-1,1]. Extra fields and frames over 8192 bytes are rejected.

Publication uses atomic replacement. Repeated sequence, stale/future publication,
and a competing owner during an active lease cannot renew input. Expiry uses a
driver-local steady clock and releases buttons/axes while retaining the last
pose. Prior-owner sequence high-water marks remain for ten seconds, longer than
the maximum frame lease; the bounded owner table fails closed at capacity.
The publisher preserves sequence across guardian recovery by reading the last
atomic frame for the same owner. System date changes cannot extend a lease.

`ack.txt` starts with `SKYRIM_AUTOTEST_ACK 2`, followed by driver PID and creation
FILETIME joined by a hyphen, owner, sequence, command, ACK boot tick, validity-end
boot tick, updated-role mask, error-role mask and expiry flag. HMD/left/right
roles use bits 0/1/2. The client retains raw ACK bytes in the driver step log,
requires the exact owned VR process, matching owner/command and a sequence at
least the selected publication, fresh boot ticks, all three roles and no errors.
Unsupported requested components set an error rather than produce a full ACK.
This adapter supports pressed bits 0..7,32,33, touched bit32 and axes0..2.

ACK means pose submission and successful OpenVR component updates. It proves
neither Skyrim consumption nor a physical grab/contact. `published` and
`acknowledgedByDriver` are separate fields; an immediate publication response
may precede the asynchronous ACK. Poll driver status with the existing bounded
read-only scenario mechanism, then assert the resulting world/subject state.

The native harness covers monotonic expiry, repeat/partial reads, stale/future
frames, owner exclusion/replay, parsing and ACK identity/components. Live-game
qualification of this version remains pending; historical v1 proofs do not
qualify v2.
