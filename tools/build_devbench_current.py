"""Reacquire and compile the narrow DevBench 1.32 compatibility candidate externally.

Build success is not in-game qualification. No installation, game launch or push.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
import zipfile

from apply_devbench_current import (COMMONLIB_COMMIT, ROOT, SOURCE_COMMIT, acquire_payloads,
                                   apply, digest)
from build_devbench_compat import XMAKE_SHA, XMAKE_URL, sha

SOURCE_REPOSITORY = 'https://github.com/alandtse/devbench.git'


def build_environment():
    env = os.environ.copy()
    # CommonLib's optional auto-deployment must never inherit an owner target.
    for key in ('SkyrimPluginTargets', 'COMMONLIB_PREBUILT', 'GITHUB_ACTIONS'):
        env.pop(key, None)
    return env


def new_output(path):
    output = Path(path).resolve()
    if output == ROOT or ROOT in output.parents or any((p / '.git').exists() for p in [output, *output.parents]):
        raise ValueError('Build directory must be new and outside Git')
    output.mkdir(parents=True, exist_ok=False)
    return output


def extract_xmake(archive, destination):
    archive, destination = Path(archive), Path(destination).resolve()
    if sha(archive) != XMAKE_SHA:
        raise ValueError('Pinned Xmake archive digest mismatch')
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            # Reject Windows separators and symlink entries as well as ../ paths.
            if '\\' in member.filename or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe Xmake archive member')
            if not (destination / member.filename).resolve().is_relative_to(destination):
                raise ValueError('Xmake archive path escape')
        zipped.extractall(destination)
    matches = list(destination.rglob('xmake.exe'))
    if len(matches) != 1:
        raise ValueError('Ambiguous Xmake executable')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--xmake-archive', type=Path, help='Optional local archive, still checked against the exact published digest')
    parser.add_argument('--prepare-only', action='store_true', help='Acquire/patch sources without compiling; never marks completed true')
    parser.add_argument('--jobs', type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        raise ValueError('jobs must be in 1..32')
    output = new_output(args.build_dir)
    manifest = {'schemaVersion': 1, 'sourceRepository': SOURCE_REPOSITORY,
                'sourceCommit': SOURCE_COMMIT, 'commonlibCommit': COMMONLIB_COMMIT,
                'upstreamVersion': '1.32.0', 'completed': False, 'prepared': False,
                'liveQualification': 'pending', 'installationChanged': False,
                'xmake': {'url': XMAKE_URL, 'sha256': XMAKE_SHA}, 'commands': [],
                'recipeFiles': {name: sha(ROOT / 'tools' / name) for name in
                                ('build_devbench_current.py', 'apply_devbench_current.py')}}

    def save():
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

    save()
    env = build_environment()
    try:
        with (output / 'build.log').open('w', encoding='utf-8') as log:
            def run(command, cwd=None, expected=0, timeout=1800):
                command = [str(value) for value in command]
                row = {'command': command, 'cwd': str(cwd) if cwd else None, 'expectedExit': expected}
                manifest['commands'].append(row)
                save()
                log.write(json.dumps(command) + '\n'); log.flush()
                start = time.monotonic()
                result = subprocess.run(command, cwd=cwd, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=timeout)
                row.update(exitCode=result.returncode, elapsedSeconds=round(time.monotonic() - start, 3))
                save()
                if result.returncode != expected:
                    raise RuntimeError('Build command failed; see retained external build.log')

            source = output / 'source'
            run(['git', '-c', 'core.autocrlf=false', 'clone', '--no-checkout', SOURCE_REPOSITORY, source])
            run(['git', '-c', 'core.autocrlf=false', 'checkout', SOURCE_COMMIT], source)
            run(['git', '-c', 'core.autocrlf=false', 'submodule', 'update', '--init', '--recursive'], source)
            actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
            commonlib = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                                cwd=source / 'lib/commonlibsse-ng', text=True).strip()
            if actual != SOURCE_COMMIT or commonlib != COMMONLIB_COMMIT:
                raise ValueError('Acquired source/submodule commit mismatch')
            manifest['submodules'] = subprocess.check_output(
                ['git', 'submodule', 'status', '--recursive'], cwd=source, text=True).splitlines()
            manifest['patch'] = apply(source, acquire_payloads(output / 'acquisitions'))
            manifest['prepared'] = True
            save()
            if args.prepare_only:
                print(json.dumps({'manifest': str(output / 'manifest.json'), 'prepared': True, 'completed': False}))
                return
            archive = args.xmake_archive
            if archive is None:
                archive = output / 'xmake.zip'
                with urllib.request.urlopen(XMAKE_URL, timeout=60) as response:
                    data = response.read(128 * 1024 * 1024 + 1)
                if digest(data) != XMAKE_SHA:
                    raise ValueError('Downloaded Xmake archive digest mismatch')
                archive.write_bytes(data)
            xmake = extract_xmake(archive, output / 'tools/xmake')
            manifest['xmake']['executableSha256'] = sha(xmake)
            run([xmake, '--version'], source, timeout=60)
            run([xmake, 'f', '-y', '-m', 'releasedbg', '-a', 'x64'], source)
            run([xmake, 'build', '-y', '-j', args.jobs, 'devbench-typeinfo-regression'], source)
            run([xmake, 'run', 'devbench-typeinfo-regression'], source, timeout=180)
            decoder = source / 'lib/commonlibsse-ng/src/RE/T/TypeInfo.cpp'
            patched = decoder.read_bytes()
            # There are two kObject expressions after correction. Revert the array
            # branch only, so the control is the exact pinned original source.
            expected_original = next(row['originalSha256'] for row in manifest['patch']['changes']
                                     if row['path'].endswith('/TypeInfo.cpp'))
            original = patched.rsplit(b'~std::to_underlying(RawType::kObject)', 1)
            original = b'~std::to_underlying(RawType::kObjectArray)'.join(original)
            if digest(original) != expected_original:
                raise ValueError('Negative-control decoder differs from pinned original')
            try:
                decoder.write_bytes(original)
                run([xmake, 'build', '-y', '-j', args.jobs, 'devbench-typeinfo-regression'], source)
                run([source / 'build/windows/x64/releasedbg/devbench-typeinfo-regression.exe'], source,
                    expected=1, timeout=180)
                manifest['unpatchedDecoderControlFailedAsExpected'] = True
            finally:
                decoder.write_bytes(patched)
            run([xmake, 'build', '-y', '-j', args.jobs, 'devbench-typeinfo-regression'], source)
            run([xmake, 'run', 'devbench-typeinfo-regression'], source, timeout=180)
            manifest['patchedDecoderAlignmentCasesPassed'] = 8
            for target in ('devbench-tests', 'devbench'):
                run([xmake, 'build', '-y', '-j', args.jobs, target], source)
                if target == 'devbench-tests':
                    run([xmake, 'run', target], source, timeout=180)
                    manifest['nativeUnitSuitePassed'] = True
            manifest['artifacts'] = {name: {'path': str(source / 'build/windows/x64/releasedbg' / name),
                                                  'sha256': sha(source / 'build/windows/x64/releasedbg' / name)}
                                     for name in ('devbench.dll', 'devbench.pdb')}
            manifest['dependencyLocks'] = {str(path.relative_to(source)): sha(path)
                                           for path in source.glob('*lock*') if path.is_file()}
            manifest['completed'] = True
            save()
    except BaseException as error:
        manifest['error'] = {'type': type(error).__name__, 'message': str(error)}
        save()
        raise
    print(json.dumps({'manifest': str(output / 'manifest.json'), 'completed': True, 'liveQualification': 'pending'}))


if __name__ == '__main__':
    main()
