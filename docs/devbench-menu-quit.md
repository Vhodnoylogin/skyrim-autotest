# Reproduce the native main-menu QUIT composition

CLAW requires normal exit through the game's Main Menu. Its explicit platform
policy remains `se_shutdown: "main-menu-v1"`. This provider candidate adds the
missing native menu operations; source compilation and pure logic checks do not
qualify actual menu behavior or authorize installation or a game launch.

The retained fc2 provider uses DevBench base
`5068162637dc2b5621b7224b8eded76a0c9e3d4f` plus the authored provider overlays from
Autotest `1285e1492a65de6a6eff0815770f9fbac3da0a69`. Its original menu interface
advertises only snapshot/select-new/confirm-new. Keep that complete source and
dependency composition, including NPC persistence, controller CFilter and morph
provider code. Do not substitute a different development branch or SDK binary.

Apply the existing public DevBench commit
[`52f0c4ca92231226a99032b0e305f9cf6c3030a9`](https://github.com/Vhodnoylogin/devbench/commit/52f0c4ca92231226a99032b0e305f9cf6c3030a9)
from [Vhodnoylogin/devbench](https://github.com/Vhodnoylogin/devbench). It changes
exactly these four files:

- `src/StartupMenu.cpp`
- `src/StartupMenuLogic.h`
- `src/Tools.cpp`
- `tests/StartupMenuLogic_test.cpp`

The patch retains the fenced SKSE UI queue and exact stock NEW admission, adds
the unique enabled `$QUIT` entry/index9, checks the actual Main/MainConfirm state
and selected entry, and advertises both select-quit and confirm-quit. The
`devbench-startup-ui/1` string is shared with the older provider; only the actual
descriptor establishes which operations are advertised. An invocation receipt
does not establish that the game process exited normally.

## Stage and apply the exact existing patch

Use a new directory under the configured external build root. Copy the retained
fc2 source/dependency closure and its separately pinned public API headers after
verifying their retained manifest hashes. Exclude `.git`, `.xmake`, `build`,
`native-build`, `target`, `__pycache__` and `.vs` directories. Copy no generated
build cache or prebuilt CommonLib library. Verify the copied inventory equals
the retained final source inventory before applying the patch.

Use an existing verified local checkout of the public DevBench repository as the
Git object source. The following commands do not switch or edit that checkout;
`$fork`, `$stage` and `$patch` must be explicitly set to the local object source,
the fresh external source directory and a new external patch file respectively.
Require the commit output and the changed-file list to match the identities above.
Git writes the patch itself, avoiding shell text-encoding transformations.

```powershell
$quitCommit = '52f0c4ca92231226a99032b0e305f9cf6c3030a9'
git -C $fork rev-parse "$quitCommit^{commit}"
git -C $fork diff-tree --no-commit-id --name-only -r $quitCommit
git -C $fork show --format= --binary --no-ext-diff "--output=$patch" $quitCommit
git -C $stage apply --check $patch
git -C $stage apply $patch
```

Verify the only source differences from fc2 are those four patched files. All
authored `MorphProvider`, `NPCPersistence` and `FixtureConfig` sources, dependency
sources, host integration and public API headers must retain their original
hashes. Record patch, complete source inventories and dependency identities in
the new external build manifest. Keep the old fc2 tree and evidence unchanged.

## Configure and build outside the installation

Use the pinned Xmake3.1.1 executable and flags from the retained fc2 manifest;
see [modern SE build details](devbench-modern-se.md). Remove deployment and
prebuilt-SDK environment variables only from the build process environment:
`SkyrimPluginTargets`, `COMMONLIB_PREBUILT`, `COMMONLIB_PREBUILT_DIR`,
`COMMONLIBSSE_DIR`, `CMAKE_PREFIX_PATH`, `GITHUB_ACTIONS` and `VCPKG_ROOT`.
Do not edit the user's persistent environment. Point
`AUTOTEST_PROVIDER_API_DIR` at the separately staged, hash-verified API headers.
Use the retained package cache and lock, configure afresh, and build CommonLib
from the copied pinned source rather than a previous build's library.

From the fresh staged source directory:

```powershell
xmake f -y -m releasedbg -a x64 -o ../b --skyrim_se=y --skyrim_ae=y --skyrim_vr=y --skse_patch_safety=y --rex_ini=y --skse_xbyak=y --rex_json=n --rex_toml=n --tests=n
xmake build -y -j 6 devbench
```

Retain compiler, configuration, commands, exits, logs and actual linked DLL/PDB
hashes. Recheck the source inventory after building and rehash both artifacts.
The new pair has its own identity; reproducibility does not imply identical PDB
or DLL bytes across different compiler paths/builds. Keep all foreign source,
SDKs, programs, headers and generated binaries outside the Autotest repository.

For bounded offline unit verification, compile only the existing patched
`tests/StartupMenuLogic_test.cpp` with `tests/test_main.cpp`, the staged `src`
headers and pinned cached nlohmann_json3.12.0 headers using MSVC C++23, `/EHsc`,
`/MD` and `/utf-8`. Run that standalone executable: it contains exactly four
existing NEW/QUIT logic cases. This avoids running the broad native suite or
loading the plugin. Check that the descriptor enum and handler admission both
contain snapshot/select-new/confirm-new/select-quit/confirm-quit; retain the
static check and compile/unit logs separately from any future runtime evidence.

The runner requires the current unique menu descriptor to advertise startup and
snapshot/select-quit/confirm-quit at readiness and again before teardown
mutations. No alternate shutdown route is selected for CLAW. Qualification must
use the actual new provider and main-menu-v1 together, observe the real menu
transitions and owned normal process exit, and verify restoration. Until that
separate authorized qualification occurs, this composition remains unqualified.
