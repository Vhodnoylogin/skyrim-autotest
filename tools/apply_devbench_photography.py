"""Stage owned read-only measurements in a separately acquired exact DevBench fork.

Never installs to MO2 or launches the game. External source remains external.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

BASE='d6630ddd672bef22bf2121944fb2c7b8ffec4f1c'
COMMONLIB='9106d402cfc7dcbc5bf7458be6748af19d7fc914'
ROOT=Path(__file__).resolve().parents[1]


def apply(source):
    source=Path(source).resolve()
    if source.is_relative_to(ROOT):raise ValueError('Dependency source must remain outside executor Git')
    def git(*args,cwd=source):return subprocess.check_output(['git',*args],cwd=cwd)
    if git('rev-parse','HEAD').decode().strip()!=BASE:raise ValueError('Exact DevBench fixture base required')
    if git('rev-parse','HEAD',cwd=source/'lib/commonlibsse-ng').decode().strip()!=COMMONLIB:raise ValueError('Exact corrected CommonLib required')
    tools=source/'src/Tools.cpp';original=tools.read_bytes()
    pinned=git('show',BASE+':src/Tools.cpp')
    if original.replace(b'\r\n',b'\n')!=pinned.replace(b'\r\n',b'\n'):raise ValueError('Tools.cpp differs; do not overwrite')
    contents=original.decode('utf-8-sig');eol='\r\n' if '\r\n' in contents else '\n'
    seam='\t\tRuntimeFixtures::Register(a_registry);'
    if contents.count(seam)!=1 or contents.count('#include "RuntimeFixtures.h"')!=1:raise ValueError('Unique provider registration seam missing')
    changes={source/'src'/n:(ROOT/'native/devbench'/n).read_bytes() for n in ('PhotographyReadback.h','PhotographyReadback.cpp')}
    if any(p.exists() for p in changes):raise ValueError('Photography provider already present; never silently overwrite')
    contents=contents.replace('#include "RuntimeFixtures.h"','#include "RuntimeFixtures.h"'+eol+'#include "PhotographyReadback.h"')
    contents=contents.replace(seam,seam+eol+'\t\tPhotographyReadback::Register(a_registry);')
    for p,data in changes.items():p.write_bytes(data)
    tools.write_bytes(contents.encode('utf-8'))
    return {'baseCommit':BASE,'commonlibCommit':COMMONLIB,'installationChanged':False,'files':{
        str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [tools,*changes]}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    print(json.dumps(apply(parser.parse_args().source)))
