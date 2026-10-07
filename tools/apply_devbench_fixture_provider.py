"""Apply our native fixture provider to an external exact DevBench fork checkout.

This stages source only; it does not build, install or run the game.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

BASE='0d8caaec64ff4cfc904c1ff5914533c295003119'
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,required=True)
    source=parser.parse_args().source.resolve()
    if source.is_relative_to(ROOT):raise ValueError('External dependency cannot be staged inside executor repository')
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
    if actual!=BASE:raise ValueError('Exact DevBench base commit required')
    tools=source/'src/Tools.cpp';old=tools.read_bytes()
    pinned=subprocess.check_output(['git','show',BASE+':src/Tools.cpp'],cwd=source)
    if old.replace(b'\r\n',b'\n')!=pinned.replace(b'\r\n',b'\n'):raise ValueError('Tools.cpp already changed; do not overwrite')
    text=old.decode('utf-8-sig');ending='\r\n' if '\r\n' in text else '\n'
    needle='\tvoid RegisterCoreTools(ToolRegistry& a_registry, EventBus& a_events)'+ending+'\t{'
    if text.count(needle)!=1:raise ValueError('Unique registration seam unavailable')
    text=text.replace('#include "Tools.h"','#include "Tools.h"'+ending+'#include "RuntimeFixtures.h"',1)
    text=text.replace(needle,needle+ending+'\t\tRuntimeFixtures::Register(a_registry);',1)
    for name in ('RuntimeFixtures.cpp','RuntimeFixtures.h'):
        target=source/'src'/name
        if target.exists():raise ValueError('Provider source already exists')
    for name in ('RuntimeFixtures.cpp','RuntimeFixtures.h'):shutil.copy2(ROOT/'native/devbench'/name,source/'src'/name)
    tools.write_bytes(text.encode('utf-8'))
    print(json.dumps({'baseCommit':BASE,'installationChanged':False,'files':
        {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [tools,source/'src/RuntimeFixtures.cpp',source/'src/RuntimeFixtures.h']}}))


if __name__=='__main__':main()
