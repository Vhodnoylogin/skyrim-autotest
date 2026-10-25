# Modern DevBench candidate for SkyrimSE1.7.104

This is an acquisition/build recipe, not an installation or launch command.
The candidate compiled offline and subsequently completed the bounded0.3.7 SE
smoke described in [qualified SE setup](se-qualified.md). That smoke covers
startup, world readiness, selected typed calls and the stock inventory menu;
SKEE, render, physics and other UI providers remain unqualified. Keep it separate
from the older VR SDK/provider line. No foreign
source, SDK, program or binary is included in this repository or agent kit.

Exact source identities:

| Component | Repository and commit |
|---|---|
| DevBench1.32 compatibility fork | [Vhodnoylogin/devbench](https://github.com/Vhodnoylogin/devbench/commit/3bb1673f95923f9a8185cf3df0337d775548033d), `3bb1673f95923f9a8185cf3df0337d775548033d` |
| Modern CommonLib correction | [Vhodnoylogin/CommonLibSSE-NG](https://github.com/Vhodnoylogin/CommonLibSSE-NG/commit/0c95630c29ff98f64caeea83c29ca373cf93e58b), `0c95630c29ff98f64caeea83c29ca373cf93e58b` |
| Modern CommonLib base | `a898f469851c464d05137bb74b069dd234897643` |
| Public Valve OpenVR headers | `60eb187801956ad277f1cae6680e3a410ee0873b` |

The modern correction clears bit0 of the tagged object-array type pointer.
Numeric enum11 is not that pointer mask; it also clears valid address bits.
The eight-case actual decoder regression includes an8-byte-aligned address whose
bit3 is set. The exact original decoder fails that case. This is pointer decoding
coverage, not an actual VM/actor/menu test.

## Reacquire and build externally

Use Git, Visual Studio C++ x64 and Xmake3.1.1. The observed compiler was
MSVC14.51.36231, Windows SDK10.0.26100. Xmake acquisition is
[the official3.1.1 Windows archive](https://github.com/xmake-io/xmake/releases/download/v3.1.1/xmake-v3.1.1.win64.zip),
SHA256 `33fdf2f34a0e45fa731c000d59590d27b13dec7011f69cbf575004ed9279b4a2`.
Existing external recipes can verify/extract this exact archive. Do not commit it.

Choose a new external build directory; never clone inside this source repository.
Run commands in a temporary shell so clearing deployment/prebuilt environment
does not affect a user's persistent configuration. No old SDK library may be
copied into the new checkout. Record tool versions, all submodules, resolved
dependency locks, command exits and output hashes in an external build manifest.

```powershell
git clone --branch fix/autotest-v132-se17104 https://github.com/Vhodnoylogin/devbench.git C:/TestBuilds/devbench-se17104/source
git -C C:/TestBuilds/devbench-se17104/source checkout 3bb1673f95923f9a8185cf3df0337d775548033d
git -C C:/TestBuilds/devbench-se17104/source submodule update --init --recursive
Set-Location C:/TestBuilds/devbench-se17104/source
git submodule status --recursive
Remove-Item Env:SkyrimPluginTargets, Env:COMMONLIB_PREBUILT, Env:COMMONLIB_PREBUILT_DIR, Env:GITHUB_ACTIONS -ErrorAction SilentlyContinue
xmake f -y -m releasedbg -a x64 --skyrim_se=y --skyrim_ae=y --skyrim_vr=y --skse_patch_safety=y --rex_ini=y --skse_xbyak=y --rex_json=n --rex_toml=n --tests=n
xmake build -y -j 6 devbench-tests
xmake run devbench-tests
xmake build -y -j 6 devbench-typeinfo-regression
xmake run devbench-typeinfo-regression
xmake build -y -j 6 devbench
```

Confirm CommonLib and OpenVR match the table before compiling. Their source
trees and nested dependencies stay external. The parent source keeps exact
gitlinks; a branch name alone is insufficient. Generated host lock changes are
retained/hash-recorded outside source commits, not silently published.

Outputs are under `build/windows/x64/releasedbg`. The observed candidate passed
314 native cases and eight actual SDK decoder cases. An isolated exact-original
TypeInfo translation unit, built with the same SDK flags, failed the expected
negative control without changing/rebuilding the corrected SDK archive.

## SDK and binary custody

This Xmake consumer uses all three runtime headers and requires patch safety,
REX INI and Xbyak enabled, JSON/TOML disabled. A different CMake SDK/prefix with
other feature flags is not automatically equivalent. Its library naming/layout
also differs from Xmake. Do not rename an unrelated `.lib` to make discovery
pass; build the matching SDK or independently verify a deliberate adapter.

The final observed DLL SHA256 is
`665d71e91390aae754cf1296dd8318d58fafee45da92f2d51cc9488a9658c512`;
matching PDB SHA256 is
`609a2adee0b1b0ae66bbe5a935894054affc879450de979b87114f60cdcbe0ff`.
PE inspection found Windows/MSVC CRT dependencies, no OpenVR/plugin import.
Rebuilding can change binary hashes; retain/pin the actual matching DLL/PDB.
No DLL was loaded or installed as part of the offline validation. The later
native smoke used this exact DLL; its configuration and limited scope are
recorded separately in [qualified SE setup](se-qualified.md).

Actual SkyrimSE1.7.104 also needs normally acquired SKSE2.3.1 and AddressLibrary13
for the exact runtime. The provider is frozen in Polygon's separate platform
plan; a mod order never carries these tool hashes. A source build, SDK label or
responding task queue cannot establish gameplay readiness or successful testing.
