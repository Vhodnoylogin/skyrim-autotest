# Screenshots through DevBench

Use DevBench's `POST /api/tool/capture` for game images in both SE and VR.
The executor does not capture the desktop, press a screenshot key, change focus,
or launch a game to obtain an image. A screenshot needs the existing session
owner's permission and the already verified game identity/DevBench port.

For a diagnostic image from an already owned game:

```powershell
python -m skyrim_autotest screenshot --identity D:/TestBench/game-identity.json --port 8090 --out D:/TestBench/screenshots --id diagnostic-001
```

Replace these example paths/port with the actual owner-provided values. The
identity JSON contains exact `pid`, `birth`, and `path`; never select an arbitrary
foreground process. This diagnostic command opens no audio. For an owner's
assisted screenshot request retain the spoken announcement/countdown with the
existing `python -m skyrim_autotest.assisted_capture` command documented in
[assisted voice](assisted-voice.md).

The diagnostic API request uses `kind:auto`, `allowNative:true`, `excludeUi:false`,
an explicit external `outDir`, and a unique `checkpointId`. A registered provider
or DevBench's native game screenshot can supply the pixels. Provider/degraded
metadata is retained; native fallback is usable diagnostic evidence but does not
satisfy strict UI-free photography or visual-comparison quality requirements.

Generic scenario steps with `tool:capture` now follow the same checked path.
Their output defaults to the run's `screenshots/<checkpointId>/` directory;
explicit output must remain inside that run. Provider discovery and burst status
queries remain reads. This addition verifies single images, not burst sequences.
Existing strict [NPC photography](photography.md) keeps its explicit provider,
camera, UI, dimension and scene checks.

Success requires `ok:true` and an actual fresh, unlinked PNG/BMP at the requested
output path. The executor checks the file identity/size across its bounded read,
PNG CRC and decoded pixel length or BMP layout, dimensions, byte count and SHA-256.
The receipt records `captureFileVerified:true` only after those checks and a final
game identity check. Missing/empty/corrupt pixels or a different path cannot pass.
The file and receipt are collected with hash rechecks into the run's evidence.

Each ID is attempted once. A timeout or unknown outcome stays uncertain and is
never retried automatically, including after a process restart. Inspect its
`screenshot-receipt.json` and any written file before an operator decides what to
do next. Do not switch to desktop control merely because an API call timed out.
Desktop inspection is a separate diagnostic for an external window or an actual
API failure; it must not be labelled a successful DevBench screenshot.

`captureFileVerified` proves file integrity, not scene/content quality. Open the
returned image before describing what it shows; `visualContentVerified` remains
false. A nonrendering/minimized game or hung main-thread queue can still fail.
No running game means capture unavailable, not permission to start one.

Offline HTTP fixtures create real PNG/BMP files and test failure paths. Their
success is distinct from a screenshot supplied by a running Skyrim renderer.
