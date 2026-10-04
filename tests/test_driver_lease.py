"""Compile/run our C++ lease test outside Git with an isolated PROGRAMDATA."""
import os
import argparse
from pathlib import Path
import subprocess
import tempfile
from skyrim_autotest import runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    from skyrim_autotest.config import load
    runner.configure(load(args.config))
    build = runner.ROOT / 'dependencies/driver-build'
    manifest = runner.read_json(build / 'manifest.json')
    with tempfile.TemporaryDirectory(prefix='driver-lease-', dir=runner.ROOT) as name:
        directory = Path(name)
        source = Path(__file__).with_suffix('.cpp').resolve()
        exe = directory / 'lease-test.exe'
        command = ['cl.exe', '/nologo', '/std:c++17', '/EHsc', '/I' + str(build),
                   str(source), '/Fe:' + str(exe)]
        batch = directory / 'test.cmd'
        batch.write_text('@echo off\ncall "' + manifest['visualStudio'] + '\\Common7\\Tools\\VsDevCmd.bat" -arch=amd64 -host_arch=amd64 >nul\nif errorlevel 1 exit /b 1\n' + subprocess.list2cmdline(command) + '\n', encoding='utf-8')
        subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=directory, check=True)
        subprocess.run([str(exe)], cwd=directory, env={**os.environ, 'PROGRAMDATA': str(directory)}, check=True)


if __name__ == '__main__':
    main()
