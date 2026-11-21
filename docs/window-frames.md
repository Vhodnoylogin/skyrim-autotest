# Owned window frame evidence on Windows

`tools/native/window_frames.cpp` is a standalone diagnostic for an exact owned
application window. It uses Windows Graphics Capture with no in-game plugin
or change to the renderer. Build it from an x64 VS 18 developer shell with
Windows SDK 10.0.26100.0. Run the compiler in an external build directory.

```bat
cl /nologo /std:c++20 /EHsc /W4 /O2 /I "%WindowsSdkDir%Include\10.0.26100.0\cppwinrt" "C:\path\to\skyrim-autotest\tools\native\window_frames.cpp" /Fe:window_frames.exe /link d3d11.lib user32.lib windowsapp.lib
```

Run it only against an application instance owned by the test. Pass the exact
PID, absolute process image path, a new directory under the owned run, the
expected full WGC content size and both limits. Supply `--hwnd` as `0x` followed
by hex digits, or remove it to require exactly one visible top-level window for
that PID. `--crop` uses integer `X,Y,WIDTH,HEIGHT` from the top-left of the
captured content. Omit the crop to collect the full frame. The helper requires
a Windows Graphics Capture session with cursor capture disabled. Capture ends
at the frame or duration limit, whichever is reached first.

```text
window_frames.exe --pid PID --image ABSOLUTE_EXE --out NEW_DIRECTORY --size 1920x1080 --duration-ms 3000 --max-frames 120 --hwnd 0xWINDOW --crop 200,100,640,360
```

- `frames.bgra` holds the packed BGRA crop bytes in capture order. Rows have
  `rowStrideBytes` bytes, no padding. `offsetBytes` names the start of a frame.
- `ready.json` is published once, atomically, after the first complete frame
  is flushed. It contains `pid`, `hwnd`, `captureStartQpc`, `qpcFrequency` and
  `firstSystemRelativeTime100ns`.
- `capture.json` describes the exact verified process image and process
  creation FILETIME, source size, crop, clock frequency, the start and end QPC
  bounds, and the frame list. Every frame has `index`, `offsetBytes`, Windows
  Graphics Capture `systemRelativeTime100ns` and host `receiptQpc`. Accept the
  stream only on exit code 0 with `status: "completed"` and a file size equal
  to the complete frame count times crop height times row stride.

If the final GPU readback is still drawing at the duration deadline, the
helper closes the capture and retains the completed frames. The manifest sets
`omittedTrailingGpuFrame` to that last frame's `systemRelativeTime100ns` and
`receiptQpc` instead of `null`. That frame has no bytes or entry in `frames`.
A capture still fails when it has zero complete frames or hits another error.

`systemRelativeTime100ns` retains the system-relative time reported by WGC.
QPC fields retain raw local ticks at the declared frequency. These are
compositor capture observations. Windows can omit intermediate presents.
An exposure can be bracketed by same-host solver observations while their
association with an exact engine frame still needs independent evidence.
[Windows capture timestamp documentation](https://learn.microsoft.com/en-us/uwp/api/windows.graphics.capture.direct3d11captureframe.systemrelativetime)

The confirmed Skyrim SE run collected 176 frames during a stock jump. Its
game preferences stayed at 1920×1080. Windows reported a 175% desktop scale
and the window recorder received a 3360×1890 source. The recorded crop was
1080×950 physical pixels. Match `--size` to the observed compositor surface
and use a fixed crop across a comparison. The capture timestamps bracketed
176 frames against the local FSMP trace with source and solver observations
on the same QPC clock.
