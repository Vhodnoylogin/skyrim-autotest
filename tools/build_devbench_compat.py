"""Build pinned external DevBench with its object-array pointer decoder corrected.

No game installation or deployment. All third-party tools, source and build
output remain in a new external directory. Requires Git and Visual Studio C++.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMMIT = '91590a9d3c81208c7efa5614e18a20d4f1caf9d1'
COMMONLIB = 'abe9ca7b7318dbc04bccfcd59fc3fb670244c2d7'
SDK_SOURCE_SHA = 'cb964717b17c73266a4118d02d3fcbf7beb6136d2d26c812425171dadd26da49'
XMAKE_URL = 'https://github.com/xmake-io/xmake/releases/download/v3.1.1/xmake-v3.1.1.win64.zip'
XMAKE_SHA = '33fdf2f34a0e45fa731c000d59590d27b13dec7011f69cbf575004ed9279b4a2'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.build_dir.resolve()
    if output.is_relative_to(ROOT) or any((p / '.git').exists() for p in [output, *output.parents]):
        raise ValueError('Build directory must be outside Git and this repository')
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    for name in ('SkyrimPluginTargets', 'COMMONLIB_PREBUILT', 'GITHUB_ACTIONS'):
        env.pop(name, None)
    manifest = {'schemaVersion': 1, 'sourceRepository': 'https://github.com/alandtse/devbench',
                'sourceCommit': COMMIT, 'commonlibCommit': COMMONLIB,
                'xmake': {'url': XMAKE_URL, 'sha256': XMAKE_SHA},
                'installedOriginalUnchanged': True, 'liveQualification': 'pending', 'completed': False}

    def write_manifest():
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')

    write_manifest()
    with (output / 'build.log').open('w', encoding='utf-8') as log:
        def run(command, cwd=None, expected=0):
            log.write(json.dumps(command)+'\n'); log.flush()
            result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode != expected:
                raise RuntimeError('Build command failed; retained external build.log and manifest.json')

        archive = output / 'xmake-v3.1.1.win64.zip'
        archive.write_bytes(urllib.request.urlopen(XMAKE_URL, timeout=60).read())
        if sha(archive) != XMAKE_SHA:
            raise RuntimeError('Pinned xmake archive digest mismatch')
        tool_dir = output / 'tools/xmake'
        with zipfile.ZipFile(archive) as zipped:
            for entry in zipped.infolist():
                target = (tool_dir / entry.filename).resolve()
                if not target.is_relative_to(tool_dir.resolve()):
                    raise ValueError('Archive path escapes external tool directory')
            zipped.extractall(tool_dir)
        matches = list(tool_dir.rglob('xmake.exe'))
        if len(matches) != 1:
            raise RuntimeError('Ambiguous xmake executable')
        tool = str(matches[0])
        source = output / 'source'
        run(['git', 'clone', '--no-checkout', manifest['sourceRepository'], str(source)])
        run(['git', '-C', str(source), 'checkout', COMMIT])
        run(['git', '-C', str(source), 'submodule', 'update', '--init', '--recursive'])
        sdk = source / 'lib/commonlibsse-ng'
        actual = subprocess.check_output(['git', '-C', str(sdk), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != COMMONLIB:
            raise RuntimeError('CommonLib submodule identity mismatch')
        manifest['submodules'] = subprocess.check_output(
            ['git', '-C', str(source), 'submodule', 'status', '--recursive'], text=True).splitlines()
        file = sdk / 'src/RE/T/TypeInfo.cpp'
        original = file.read_bytes()
        if sha(file) != SDK_SOURCE_SHA:
            raise RuntimeError('Original TypeInfo source digest mismatch')
        old = b'~std::to_underlying(RawType::kObjectArray)'
        new = b'~std::to_underlying(RawType::kObject)'
        if original.count(old) != 1:
            raise RuntimeError('Array decoder patch target mismatch')
        patched = original.replace(old, new)
        file.write_bytes(patched)
        manifest['patch'] = {'file': str(file.relative_to(source)), 'originalSha256': SDK_SOURCE_SHA,
                             'patchedSha256': sha(file), 'before': old.decode(), 'after': new.decode()}
        probe = ROOT / 'tools/native/typeinfo_array_probe.cpp'
        shutil.copyfile(probe, source / 'typeinfo-regression.cpp')
        manifest['probeSha256'] = sha(probe)
        with (source / 'xmake.lua').open('a', encoding='utf-8') as stream:
            stream.write('\ntarget("devbench-typeinfo-regression")\nset_kind("binary")\n'
                         'set_default(false)\nadd_deps("commonlibsse-ng")\n'
                         'add_files("typeinfo-regression.cpp")\nadd_defines("_WINSOCKAPI_")\ntarget_end()\n')
        write_manifest()
        run([tool, 'f', '-y', '-m', 'releasedbg', '-a', 'x64'], source)
        run([tool, 'build', '-y', '-j', '6', 'devbench-typeinfo-regression'], source)
        run([tool, 'run', 'devbench-typeinfo-regression'], source)
        # Prove the original decoder fails the same real-library alignment test.
        try:
            file.write_bytes(original)
            run([tool, 'build', '-y', '-j', '6', 'devbench-typeinfo-regression'], source)
            executable = source / 'build/windows/x64/releasedbg/devbench-typeinfo-regression.exe'
            run([str(executable)], source, expected=1)
            manifest['unpatchedRegressionFailedAsExpected'] = True
        finally:
            file.write_bytes(patched)
        run([tool, 'build', '-y', '-j', '6', 'devbench-typeinfo-regression'], source)
        run([tool, 'run', 'devbench-typeinfo-regression'], source)
        manifest['patchedAlignmentCasesPassed'] = 8
        for target in ('devbench-tests', 'devbench'):
            run([tool, 'build', '-y', '-j', '6', target], source)
            if target == 'devbench-tests':
                run([tool, 'run', target], source)
        manifest['artifacts'] = {name: {'path': str(source / 'build/windows/x64/releasedbg' / name),
                                         'sha256': sha(source / 'build/windows/x64/releasedbg' / name)}
                                 for name in ('devbench.dll', 'devbench.pdb')}
        manifest['requiresInGameQualification'] = True
        manifest['completed'] = True
        write_manifest()
    print(json.dumps({'manifest': str(output / 'manifest.json'), 'completed': True}))


if __name__ == '__main__':
    main()
