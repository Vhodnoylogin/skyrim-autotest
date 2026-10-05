# DevBench VR type metadata compatibility candidate

DevBench 1.25.0 crashed during `papyrus describe ObjectReference` in a minimal
Realm New Game run on 2026-10-06. The collected crash stack passes through
`TypeInfo::TypeAsString` while describing `CreateEnchantment`'s object-array
parameter. Other attempts returned an empty HTTP500 or valid metadata; the
crash log does not establish the cause of every previous HTTP failure.

The pinned CommonLib dependency decodes an object-array class pointer by
clearing the literal enum11. Arrays encode the class pointer with bit0 set;
clearing11 also destroys address bits1 and3. A class allocated at an address
ending in8 therefore decodes eight bytes earlier. Our candidate clears only
bit0 and retains the rest of the host and public API unchanged.

Build outside Git with Git and the Visual Studio C++ tools:

```powershell
python tools/build_devbench_compat.py --build-dir C:/TestBuilds/devbench-v125-typeinfo-fix
```

The builder requires a new external directory, downloads digest-pinned portable
Xmake, checks out DevBench and its exact dependency revisions, verifies the
original source digest, applies the single expression correction, and tests the
actual compiled decoder at four alignments for both object and object-array
types. The unpatched control must fail; the patched library must pass. It also
runs DevBench's existing native tests and records external DLL/PDB hashes.
Source, SDK, programs, logs and resulting binaries are never copied into this
repository or the Python runtime distribution. Preserve upstream GPL licensing
and credits if distributing a derived DevBench binary.

This candidate passed the bounded Papyrus metadata checks in eight isolated
minimal New Game launches on 2026-10-06 (v10 through v17), with restoration.
The earlier TypeAsString crash was not observed in those attempts. This does
not establish acceptance for every metadata function or a combined mod scenario.
Stage the matching
DLL and PDB as ordinary pinned `staged_plugins` in an authorized isolated run;
keep the installed original intact and verify restoration. Require actual
metadata signatures and subsequent gameplay observations. Do not retry a
connection reset, suppress a crash, substitute unavailable metadata, or count
source/build tests as a passing game run.


## Published maintenance forks

The corrected source is available in a GitHub fork of DevBench, branch
[fix/vr-typeinfo-array-v125](https://github.com/Vhodnoylogin/devbench/tree/fix/vr-typeinfo-array-v125),
commit ba6104319b93ca147d7f94e94149402c015954a7. It pins the corrected
CommonLib dependency in the existing fork, branch
[fix/typeinfo-array-pointer-v125](https://github.com/Vhodnoylogin/CommonLibSSE-NG/tree/fix/typeinfo-array-pointer-v125),
commit 9106d402cfc7dcbc5bf7458be6748af19d7fc914.
DevBench retains its upstream license/credits; the fork is not an upstream
release. The source correction and native regression are published there;
generated host dependency locks and test binaries remain external.
