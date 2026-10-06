"""Reacquire and build the pinned 1.26 VR-readiness fork outside the installation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

from build_devbench_compat import sha, XMAKE_URL, XMAKE_SHA

SOURCE = 'https://github.com/Vhodnoylogin/devbench.git'
COMMIT = '0d8caaec64ff4cfc904c1ff5914533c295003119'
COMMONLIB = '9106d402cfc7dcbc5bf7458be6748af19d7fc914'
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, required=True)
    output = parser.parse_args().build_dir.resolve()
    if output.is_relative_to(ROOT) or any((p / '.git').exists() for p in [output, *output.parents]):
        raise ValueError('Build directory must be new and outside Git')
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    for key in ('SkyrimPluginTargets', 'COMMONLIB_PREBUILT', 'GITHUB_ACTIONS'):
        env.pop(key, None)
    manifest = {'sourceRepository': SOURCE, 'sourceCommit': COMMIT, 'commonlibCommit': COMMONLIB,
                'completed': False, 'liveQualification': 'pending', 'installationChanged': False,
                'xmake': {'url': XMAKE_URL, 'sha256': XMAKE_SHA}}
    def save():
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    save()
    with (output / 'build.log').open('w', encoding='utf-8') as log:
        def run(command, cwd=None):
            log.write(json.dumps(command) + '\n'); log.flush()
            subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        archive = output / 'xmake.zip'
        with urllib.request.urlopen(XMAKE_URL, timeout=60) as response:
            archive.write_bytes(response.read(128 * 1024 * 1024 + 1))
        if sha(archive) != XMAKE_SHA:
            raise ValueError('Xmake digest mismatch')
        tools = output / 'tools'
        with zipfile.ZipFile(archive) as zipped:
            for entry in zipped.infolist():
                if not (tools / entry.filename).resolve().is_relative_to(tools.resolve()):
                    raise ValueError('Archive path escape')
            zipped.extractall(tools)
        matches = list(tools.rglob('xmake.exe'))
        if len(matches) != 1:
            raise ValueError('Ambiguous Xmake executable')
        xmake = str(matches[0])
        source = output / 'source'
        run(['git', 'clone', '--no-checkout', SOURCE, str(source)])
        run(['git', 'checkout', COMMIT], source)
        run(['git', 'submodule', 'update', '--init', '--recursive'], source)
        actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source / 'lib/commonlibsse-ng', text=True).strip()
        if actual != COMMONLIB:
            raise ValueError('Corrected CommonLib pin mismatch')
        run([xmake, 'f', '-y', '-m', 'releasedbg', '-a', 'x64'], source)
        for target in ('devbench-typeinfo-regression', 'devbench-tests', 'devbench'):
            run([xmake, 'build', '-y', '-j', '6', target], source)
            if target != 'devbench':
                run([xmake, 'run', target], source)
        manifest['artifacts'] = {name: {'path': str(source / 'build/windows/x64/releasedbg' / name),
                                       'sha256': sha(source / 'build/windows/x64/releasedbg' / name)}
                                 for name in ('devbench.dll', 'devbench.pdb')}
        manifest['completed'] = True
        save()
    print(json.dumps({'manifest': str(output / 'manifest.json'), 'completed': True}))


if __name__ == '__main__':
    main()
