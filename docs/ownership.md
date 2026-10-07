# Ownership, upstream scope and credits

Our code: standalone executor, independent guardian, scenario/order handling,
physical file-frame client/protocol and driver transformation/build recipe.
MO2 API Bridge and Skyrim World Observer are separate projects by this owner.
MO2, Root Builder, Skyrim VR, SKSEVR, SteamVR/OpenVR, DevBench, VRIK and HIGGS
are independently maintained third-party dependencies/test subjects.

The automation backend is derived at build time from DubiousDuo's Devkit driver
fork of ar-zadeh's original VR Emulator Driver. It is one emulator implementation,
not a second driver called after the original. The Devkit AHK frontend is an
optional external control interface; this executor does not require it.

On 2026-10-04, the Devkit author (DubiousDodo on Nexus; DubiousDuo on GitHub)
explained that a full automation API is outside the project's scope and allowed
maintenance/release of our own credited fork. Therefore this adapter is an owned
automation-backend candidate, not a temporary patch awaiting promised Devkit API
implementation. The historical qualified file protocol is retained in frozen
platforms. Source protocol v2 adds versioned ownership, sequence/command ACKs and
monotonic leases; its native harness passes, with live-game qualification pending.
Current tests assert observed game outcomes; a driver ACK alone cannot prove them.
The author plans installer extraction/version verification changes, rather than
adopting the full requested automation contract. Planned changes are not treated
as available installed behavior.

Source: [author reply](https://www.nexusmods.com/skyrimspecialedition/mods/191452?tab=posts#comment-176787264).

Credits and provenance:
- [DubiousDuo / DubiousDodo](https://github.com/DubiousDuo/VR-Emulator-Driver---SkyrimVR-Devkit): Devkit driver fork and setup/frontend work.
- [ar-zadeh](https://github.com/ar-zadeh/VR-Emulator-Driver): original virtual HMD/controller emulator.
- [Valve](https://github.com/ValveSoftware/openvr): OpenVR SDK/sample ancestry and SteamVR runtime interfaces.
- [alandtse and DevBench contributors](https://github.com/alandtse/devbench): in-game automation transport and tools.

This distribution contains our own code and acquisition metadata, not external
driver binaries/source/SDK headers. Build-time external content remains in the
configured runtime directory. Fork-author permission does not independently
license original ar-zadeh/Valve or other third-party material; preserve their
licenses/notices and check applicable terms before publishing a derived binary.
No Nexus release or separately published full driver fork is included here.
