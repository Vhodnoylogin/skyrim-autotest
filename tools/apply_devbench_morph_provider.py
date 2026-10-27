"""Stage authored morph/persistence tools into an exact external DevBench fork."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

BASE='5068162637dc2b5621b7224b8eded76a0c9e3d4f'
ROOT=Path(__file__).resolve().parents[1]

def stage(source, api_dir):
    source,api_dir=Path(source).resolve(),Path(api_dir).resolve()
    if source==ROOT or ROOT in source.parents: raise ValueError('External host required')
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()!=BASE:
        raise ValueError('Exact compatible DevBench base required')
    for name,expected in {'IPluginInterface.h':'875410dd22230f76a014a6841004e7d346f5fa1c748cfff695f9f495234da277',
            'OBodyAPI.h':'f04945202d9daa6408d7555e46eb2a553a1041ab5d84a8f4efc288168563ea18'}.items():
        if hashlib.sha256((api_dir/name).read_bytes()).hexdigest()!=expected:raise ValueError('Official external API pin differs: '+name)
    patches={
        'src/Tools.cpp': [('#include "Tools.h"','#include "Tools.h"\n#include "MorphProvider.h"\n#include "NPCPersistence.h"\n#include "FixtureConfig.h"'),
            ('void RegisterCoreTools(ToolRegistry& a_registry, EventBus& a_events)\n\t{',
             'void RegisterCoreTools(ToolRegistry& a_registry, EventBus& a_events)\n\t{\n\t\tMorphProvider::Register(a_registry);\n\t\tNPCPersistence::Register(a_registry);\n\t\tFixtureConfig::Register(a_registry);')],
        'src/main.cpp': [('#include "ActorIdle.h"','#include "ActorIdle.h"\n#include "MorphProvider.h"\n#include "NPCPersistence.h"'),
            ('if (!a_msg)\n\t\t\treturn;','if (!a_msg)\n\t\t\treturn;\n\t\tdvb::MorphProvider::OnSKSEMessage(a_msg->type);\n\t\tdvb::NPCPersistence::OnSKSEMessage(a_msg->type);'),
            ('SKSE::Init(a_skse);','SKSE::Init(a_skse);\n\tdvb::NPCPersistence::Initialize();')],
        'xmake.lua': [('add_includedirs("src")\n-- Public C-ABI',
            'add_includedirs("src")\nadd_includedirs(os.getenv("AUTOTEST_PROVIDER_API_DIR") or "build/external/provider-api")\n-- Public C-ABI')]
    }
    changed=[]
    # Verify all seams and exact original or already-identical staged files first.
    wanted={}
    for relative,replacements in patches.items():
        original=subprocess.check_output(['git','show',BASE+':'+relative],cwd=source).decode('utf-8-sig').replace('\r\n','\n')
        result=original
        for old,new in replacements:
            if result.count(old)!=1:raise ValueError('Ambiguous host seam: '+relative)
            result=result.replace(old,new,1)
        actual=(source/relative).read_text(encoding='utf-8-sig')
        predecessor=result.replace('\n#include "FixtureConfig.h"','').replace('\n\t\tFixtureConfig::Register(a_registry);','')
        if actual not in (original,result,predecessor):raise ValueError('Foreign host edit: '+relative)
        wanted[source/relative]=result.encode('utf-8')
    for name in ('MorphProvider.h','MorphProvider.cpp','NPCPersistence.h','NPCPersistence.cpp','FixtureConfig.h','FixtureConfig.cpp'):
        wanted[source/'src'/name]=(ROOT/'native/devbench'/name).read_bytes()
    for target,raw in wanted.items():
        target.write_bytes(raw);changed.append({'path':str(target),'sha256':hashlib.sha256(raw).hexdigest()})
    return {'schemaVersion':1,'baseCommit':BASE,'stagedFiles':changed,'installed':False,'gameStarted':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--provider-api-dir',type=Path,required=True);args=p.parse_args()
    print(json.dumps(stage(args.source,args.provider_api_dir),indent=2))
if __name__=='__main__':main()
