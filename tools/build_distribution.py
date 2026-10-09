"""Build a portable ZIP and standards-compliant wheel with the Python stdlib."""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.2.0'
INFO = 'skyrim_autotest-' + VERSION + '.dist-info'

def package_files():
    return sorted(p for p in (ROOT / 'skyrim_autotest').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo'))

def write_archive(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT) or any((p / '.git').exists() for p in [output, *output.parents]):
        raise ValueError('Build output must be outside Git and this distribution')
    output.mkdir(parents=True, exist_ok=True)
    entries = {str(p.relative_to(ROOT)).replace('\\','/'): p.read_bytes() for p in package_files()}
    for name in ('README.md', 'AGENTS.md', 'CLAUDE.md', 'LICENSE', 'dependencies.json', 'run.py', 'skyrim-autotest.cmd', 'pyproject.toml'):
        entries[name] = (ROOT / name).read_bytes()
    for folder in ('docs','tests','tools','native','integrations'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:
                entries[str(p.relative_to(ROOT)).replace('\\','/')] = p.read_bytes()
    portable = output / ('skyrim-autotest-' + VERSION + '-portable.zip')
    write_archive(portable, entries)
    wheel_entries = {str(p.relative_to(ROOT)).replace('\\','/'): p.read_bytes() for p in package_files()}
    wheel_entries[INFO+'/METADATA'] = ('Metadata-Version: 2.1\nName: skyrim-autotest\nVersion: '+VERSION+'\nSummary: Bounded Skyrim VR tests with independent recovery\nRequires-Python: >=3.11\nLicense: MIT\n\n').encode()
    wheel_entries[INFO+'/WHEEL'] = b'Wheel-Version: 1.0\nGenerator: skyrim-autotest-stdlib-builder\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
    wheel_entries[INFO+'/entry_points.txt'] = b'[console_scripts]\nskyrim-autotest = skyrim_autotest.cli:main\n'
    wheel_entries[INFO+'/licenses/LICENSE'] = (ROOT/'LICENSE').read_bytes()
    for p in (ROOT/'docs').glob('*.md'):
        wheel_entries['skyrim_autotest/docs/' + p.name] = p.read_bytes()
    for p in (ROOT/'integrations').glob('*.js'):
        wheel_entries['skyrim_autotest/integrations/' + p.name] = p.read_bytes()
    wheel_entries['skyrim_autotest/dependencies.json'] = (ROOT/'dependencies.json').read_bytes()
    record = io.StringIO(newline='')
    writer = csv.writer(record)
    for name, data in sorted(wheel_entries.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow([name,'sha256='+digest,str(len(data))])
    writer.writerow([INFO+'/RECORD','',''])
    wheel_entries[INFO+'/RECORD'] = record.getvalue().encode()
    wheel = output / ('skyrim_autotest-' + VERSION + '-py3-none-any.whl')
    write_archive(wheel, wheel_entries)
    manifest = {'schemaVersion':1,'version':VERSION,'pythonRuntimeDependencies':[], 'artifacts':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size} for p in (portable,wheel)], 'sourceFiles':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(entries.items())}}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(output), 'artifacts':manifest['artifacts']},indent=2))

if __name__ == '__main__':
    main()
