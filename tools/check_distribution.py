"""Check fresh portable extraction and wheel installation outside Git, no game launch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def call(args, cwd, env=None):
    result = subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,timeout=60)
    if result.returncode:
        raise RuntimeError(str(args) + '\n' + result.stdout + result.stderr)
    return result.stdout

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    args = parser.parse_args()
    dist = args.distribution.resolve()
    work = args.work.resolve()
    if work.exists():
        raise ValueError('Use a new empty external work directory')
    if any((p/'.git').exists() for p in [work,*work.parents]):
        raise ValueError('Check output must be outside Git')
    work.mkdir(parents=True)
    manifest = json.loads((dist/'manifest.json').read_text())
    for entry in manifest['artifacts']:
        if hashlib.sha256((dist/entry['name']).read_bytes()).hexdigest() != entry['sha256']:
            raise RuntimeError('Artifact hash mismatch: '+entry['name'])
    portable = work/'portable'
    portable.mkdir()
    with zipfile.ZipFile(next(dist.glob('*-portable.zip'))) as archive:
        archive.extractall(portable)
    empty = work/'empty'
    empty.mkdir()
    env = dict(os.environ)
    env.pop('PYTHONPATH',None)
    env['PYTHONUTF8']='1'
    checks = []
    def verify(label,command):
        call(command,empty,env)
        checks.append(label)
    for name in ('RuntimeFixtures.cpp','RuntimeFixtures.h'):
        relative='native/devbench/'+name
        if hashlib.sha256((portable/relative).read_bytes()).hexdigest()!=manifest['sourceFiles'][relative]:
            raise RuntimeError('Native integration input missing or changed: '+relative)
    checks.append('portable-owned-native-integration-inputs')
    adapter = 'integrations/codex-voice-bridge.js'
    if hashlib.sha256((portable/adapter).read_bytes()).hexdigest() != manifest['sourceFiles'][adapter]:
        raise RuntimeError('Portable voice host adapter missing or changed')
    checks.append('portable-buffered-voice-host-adapter')
    verify('portable-native-recipe-unrelated-cwd',[sys.executable,str(portable/'tools/apply_devbench_fixture_provider.py'),'--help'])
    verify('portable-version-unrelated-cwd',[sys.executable,str(portable/'run.py'),'--version'])
    verify('portable-agent-guide',[sys.executable,str(portable/'run.py'),'guide'])
    verify('portable-init-unrelated-cwd',[sys.executable,str(portable/'run.py'),'init','--directory',str(work/'config')])
    config = work/'config/config.json'
    value=json.loads(config.read_text())
    for key in ('runtime','mo2','game','mods','profiles','overwrite','bridge_token','openvr_paths','skse_logs'):
        value[key]=str(work/'environment'/key)
    value['fixture_dir']=str(work/'environment/fixture')
    config.write_text(json.dumps(value),encoding='utf-8')
    verify('portable-config-check',[sys.executable,str(portable/'run.py'),'--config',str(config),'config-check'])
    verify('portable-empty-status',[sys.executable,str(portable/'run.py'),'--config',str(config),'status'])
    child=subprocess.run([sys.executable,str(portable/'run.py'),'init','--directory',str(work/'config')],cwd=empty,env=env,capture_output=True,text=True,timeout=10)
    if child.returncode != 2:
        raise RuntimeError('Init must refuse overwriting existing config')
    checks.append('init-refuses-overwrite')
    installed=work/'installed'
    call([sys.executable,'-m','pip','install','--no-index','--no-deps','--target',str(installed),str(next(dist.glob('*.whl')))],empty,env)
    bootstrap='import sys; sys.path.insert(0,sys.argv[1]); from skyrim_autotest.cli import main; raise SystemExit(main(sys.argv[2:]))'
    verify('wheel-isolated-version',[sys.executable,'-I','-c',bootstrap,str(installed),'--version'])
    verify('wheel-isolated-guide',[sys.executable,'-I','-c',bootstrap,str(installed),'guide'])
    verify('wheel-isolated-init',[sys.executable,'-I','-c',bootstrap,str(installed),'init','--directory',str(work/'wheelconfig')])
    verify('wheel-isolated-config',[sys.executable,'-I','-c',bootstrap,str(installed),'--config',str(config),'config-check'])
    verify('wheel-isolated-status',[sys.executable,'-I','-c',bootstrap,str(installed),'--config',str(config),'status'])
    if hashlib.sha256((installed/'skyrim_autotest'/adapter).read_bytes()).hexdigest() != manifest['sourceFiles'][adapter]:
        raise RuntimeError('Wheel voice host adapter missing or changed')
    for module in ('voice_listener', 'voice_inbox'):
        companion='import sys;sys.path.insert(0,sys.argv[1]);from skyrim_autotest.'+module+' import main;raise SystemExit(main(["--help"]))'
        verify('wheel-isolated-'+module,[sys.executable,'-I','-c',companion,str(installed)])
    # Execute tests from the freshly extracted source, never the checkout.
    test='import sys,unittest;sys.path.insert(0,sys.argv[1]);suite=unittest.defaultTestLoader.discover(sys.argv[1]+"/tests");r=unittest.TextTestRunner(verbosity=1).run(suite);raise SystemExit(not r.wasSuccessful())'
    verify('fresh-portable-regression-suite',[sys.executable,'-I','-c',test,str(portable)])
    result={'schemaVersion':1,'result':'passed','checks':checks,'artifacts':manifest['artifacts'],'work':str(work)}
    (work/'checks.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    main()
