# Exact DevBench 1.36 decoder repair preparation

This separate recipe preserves historical 1.32 builds. It changes only
CommonLib's `TypeInfo::GetTypeInfo`: untyped object placeholders return null;
object-array decoding clears bit0 alone, preserving pointer bit3. It does not
install, launch, publish, or modify the Python executor.

| Input | Official pin |
| --- | --- |
| [DevBench](https://github.com/alandtse/devbench/commit/cb0c0a9898f656e6df9697570026e7ef2705c44f) | `cb0c0a9898f656e6df9697570026e7ef2705c44f` |
| CommonLibVR | `abe9ca7b7318dbc04bccfcd59fc3fb670244c2d7` |
| cpp-mcp | `f1117d5286efe6477ddd14322703f034615b6c0e` |
| OpenVR | `60eb187801956ad277f1cae6680e3a410ee0873b` |

Acquire the official checkout and recursive submodules normally into a **new
external build directory**, outside every parent Git checkout. Verify the above
heads. No SDK, upstream source/blob, archive, program or binary is shipped here.
Keep the original official provider installation unchanged.

```powershell
git clone --no-checkout https://github.com/alandtse/devbench.git '<build>/source'
git -C '<build>/source' checkout --detach cb0c0a9898f656e6df9697570026e7ef2705c44f
git -C '<build>/source' submodule update --init --recursive
python tools/apply_devbench_136_arraydecode.py --source '<build>/source'
python tools/apply_devbench_136_arraydecode.py --source '<build>/source' --apply
```

Review is read-only by default. Apply requires Windows exclusive file handles;
both tracked inputs stay share-denied through journal commit or rollback. It
verifies all inputs and absent outputs before reserving its one-use receipt,
then rechecks leased bytes before each replacement. The original TU is flushed
and readback-verified at external `<build>/TypeInfo-before.cpp` **before** any
tracked mutation. It preserves LF/CRLF, stages our cpp/PCH and appends four
non-default targets. The per-file pending/verified journal retains failures;
rollback restores only exact known written bytes, preserving unrecognized bytes
and independent failures. Staged files/backup remain for inspection. Changed,
mixed-EOL, already-patched or partial preparations fail without automatic replay.
Canonical LF TypeInfo SHA256s are:

- Before: `a3766c4636da466eb416af393a89ea124ffc235c742c904d55fb62eca4d3f74d`.
- After: `28b198b61889d9f8dcd479e4bb9333d8a8073a509df3d4515cbf4fae329d3ab9`.

Receipt hashes also record actual written bytes. The observed external CRLF
pre/post hashes were `cb964717b17c73266a4118d02d3fcbf7beb6136d2d26c812425171dadd26da49`
and `ecec7f729d3996a954ba20a19695dfca59658c376611c7655bb2b605e6db7ce0`.

## Explicit offline build and controls

Use the pinned Xmake/toolchain acquisition in `devbench-modern-se.md`. In a
temporary shell clear inherited deployment/prebuilt settings, including case
variants of `SkyrimPluginTargets`, `COMMONLIB_PREBUILT`, `COMMONLIB_PREBUILT_DIR`,
`GITHUB_ACTIONS`, `CMAKE_PREFIX_PATH`, `COMMONLIBSSE_DIR`, and `VCPKG_ROOT`.
Require no `lib/commonlibsse-ng/lib/commonlibsse-ng.lib`; compile the SDK from the
pinned source. Retain exact compiler, tool, dependency-lock and command hashes.

```powershell
Set-Location '<build>/source'
xmake f -c -y -m releasedbg -a x64 --skyrim_se=y --skyrim_ae=y --skyrim_vr=y --skse_patch_safety=y --rex_ini=y --skse_xbyak=y --rex_json=n --rex_toml=n --tests=n
xmake build -y -j 6 devbench-typeinfo-regressions
```

Execute `devbench-typeinfo-debug.exe` and `devbench-typeinfo-ndebug.exe` from
`build/windows/x64/releasedbg`: both must exit0 with20 checks. Execute the two
`devbench-typeinfo-before-*.exe` controls separately: both must exit1 with the
lowbits8/tag1 decoder mismatch. Never treat arbitrary crashes as an expected
negative. The PCH establishes the assertion mode **after** Windows/SDK headers;
both the test and actual production TU compile in that declared mode. Negative
controls compile the exact captured original TU without swapping SDK source.

Then build/run `devbench-tests` (observed343 cases, zero failures), and build
`devbench`. Preserve the existing lock's dependency versions/repository commits;
do not accept a newly resolved dependency set to make configuration pass. The
retained original build needed only an audited computed-key migration, recorded
externally; that machine-specific fallback is not automated by this recipe.

Record the resulting matching DLL/PDB hashes; rebuilds need not be identical.
The earlier repaired pair was `39a85b56b0b11d286cdbd7020438284b317450ac12018ef696e924be10932573`
and `66ee60735108b593ebf48d88ec1015c7353e5379e070697ca97c686a87bca10f`.
Native decoder/suite success establishes neither game acceptance, VM timing,
CBPC/FSMP behavior, nor AE/VR runtime qualification. Live evidence must identify
the exact installed candidate, configuration, commands, restoration and scope.

The exact repaired DLL above subsequently completed seven native descriptions,
including the formerly crashing ObjectReference query, and three CBPC version
getters in SE case `20261111-214933-366ed7`. Actual main-menu exit was zero;
the official provider and all164 profile preimages were restored. The CBPC
motion case itself failed its timing/response criteria. These separate tool
observations do not qualify stock1.36, CBPC physics, AE or VR behavior.
