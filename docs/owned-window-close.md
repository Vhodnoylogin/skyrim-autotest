# One owned primary game-window close

The SE `window-close-v1` route uses `native.close_game_window`, selecting one
current window of the exact original PID/birth/path. Generic `native.close`
remains unchanged for MO2 and other owned helper processes. This change does not
request foreground focus, issue console input or terminate a process.

The retained manual5 startup observation identifies the actual primary window
class as `Skyrim Special Edition`, HWND788974. The old exit receipt posted
WM_CLOSE to that window and two additional same-process top-level windows.
The additional windows have no retained title/class identity. This was a proven
overbroad close selection. A later independently identity-matched manual5 dump
locates its actual access violation in `skee64.dll+0x2EE3BA`: the string-table
lookup in `DeleteStringEntry` during `BodyMorphInterface`/CRT static teardown
reads through a null bucket base. This matches the earlier RaceMenu NG B6
string-table lifetime failure. The multiwindow receipt does not establish that
the extra close messages caused that defect; narrowing selection is independent
hardening, not the RaceMenu lifetime repair.

Selection now requires exactly one visible, ownerless, non-WS_EX_TOOLWINDOW
top-level window with the explicit SE class. Window title is not used because it
can change. All owned observations and the selection policy are retained in the
receipt. Zero matches, ambiguity, incomplete enumeration or failed class/owner/
style queries refuse without posting to helpers or guessing a replacement.
The selected HWND's PID, thread, class, visibility, owner and extended styles,
plus original process identity, are checked again immediately before one
PostMessageW. The final check narrows the HWND-reuse race; Win32 does not provide
an atomic process-identity-and-post transaction, so it cannot eliminate it.

The logical quit intent remains durably recorded before the call. An accepted
post only means enqueueing; the retained process handle must independently prove
actual exit. Errors or unknown delivery never authorize another post or broad
fallback within this route. The existing original exit grace, cleanup ownership
barriers and truthful nonzero-exit classification remain. In particular,
0xC0000005 is still abnormal and cannot become success because a post succeeded.

Win32 contracts: [EnumWindows](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumwindows)
enumerates top-level windows; [GetWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindow)
with GW_OWNER obtains the owner; [GetWindowLongPtrW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowlongptrw)
reads GWL_EXSTYLE using pointer-sized LONG_PTR, with zero distinguished from a
query failure using GetLastError; [PostMessageW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-postmessagew)
queues to the thread that created the target window and returns before handling.
No cross-thread SendMessage, thread attachment or helper-window close is needed.

Mock-only checks cover multiple owned/helper/foreign windows, ambiguity, hidden
and tool windows, process/HWND identity changes, query and post failures,
once-only grace/recovery and abnormal-exit classification. A future separately
authorized live run must validate actual primary-window selection and normal
native teardown. No game launch, live window API call or installation is part of
the offline repair.
