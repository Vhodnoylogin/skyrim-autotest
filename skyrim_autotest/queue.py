"""Local order queue and the project's ordered -> running -> reported board.

python queue.py add --order order.json
python queue.py next --restart-idle-mo2
python queue.py list
python queue.py reconcile
python queue.py accept <id> --note "Owner accepted the evidence"

accept records an explicit owner decision; automated execution never closes orders.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from . import native
from . import runner

def queue_file():
    return runner.ROOT / 'queue.json'


def read():
    return runner.read_json(queue_file()) if queue_file().exists() else []


def board(item, status, note):
    # Optional external dashboards consume these append-only local events.
    file = runner.ROOT / 'queue-events.jsonl'
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'id': item['id'], 'status': status, 'note': note, 'at': time.time()}) + '\n')



def reconcile(items):
    for item in items:
        if item['status'] != 'running':
            continue
        runs = [runner.read_json(p) for p in runner.RUNS.glob('*/state.json')]
        matching = [s for s in runs if s.get('order', {}).get('id') == item['id']]
        if not matching:
            continue
        state = sorted(matching, key=lambda s: s['id'])[-1]
        if not state.get('done'):
            continue
        item.update(status='reported', result=state.get('result'), run=state['id'])
        runner.atomic_json(queue_file(), items)
        board(item, 'reported', f"{item['result']}; evidence {runner.RUNS / item['run']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    add = subs.add_parser('add')
    add.add_argument('--order', required=True, type=Path)
    nxt = subs.add_parser('next')
    nxt.add_argument('--restart-idle-mo2', action='store_true')
    subs.add_parser('list')
    subs.add_parser('reconcile')
    accept = subs.add_parser('accept')
    accept.add_argument('id')
    accept.add_argument('--note', required=True)
    args = parser.parse_args(argv)
    with native.SessionMutex():
        items = read()
        if args.command == 'add':
            order = runner.read_json(args.order)
            if order.get('schemaVersion') != 1 or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', order.get('id', '')):
                raise ValueError('Order needs schemaVersion 1 and a safe unique id')
            if any(not isinstance(order.get(k), str) or not order[k].strip() for k in ('owner', 'subject', 'profile', 'scenario')):
                raise ValueError('Order needs owner, subject, profile and scenario strings')
            if any(item['id'] == order['id'] for item in items):
                raise ValueError('Duplicate order id')
            scenario = (args.order.resolve().parent / order['scenario']).resolve()
            if not scenario.is_file():
                raise ValueError('Scenario does not exist')
            order.update(status='ordered', scenario=str(scenario), scenarioHash=runner.sha(scenario), submittedAt=time.time())
            items.append(order)
            runner.atomic_json(queue_file(), items)
            board(order, 'ordered', 'Submitted for automated execution; owner authorization is required by the current session')
        elif args.command == 'next':
            runner.recover()
            reconcile(items)
            item = next((item for item in items if item['status'] == 'ordered'), None)
            if not item:
                print('No ordered tests')
                return 0
            if runner.sha(item['scenario']) != item['scenarioHash']:
                raise ValueError('Submitted scenario changed; submit a new order instead')
            item['status'] = 'running'
            runner.atomic_json(queue_file(), items)
            board(item, 'running', 'Own game session; independent guardian and evidence journal active')
            try:
                code = runner.run(item['profile'], Path(item['scenario']), restart_idle_mo2=args.restart_idle_mo2,
                                  order={'id': item['id'], 'owner': item['owner']})
                reconcile(items)
                return code
            except Exception as e:
                item.update(status='reported', result='blocked', reason=str(e))
                runner.atomic_json(queue_file(), items)
                board(item, 'reported', 'Blocked before run: ' + str(e))
                raise
        elif args.command == 'accept':
            item = next(item for item in items if item['id'] == args.id)
            if item['status'] != 'reported':
                raise ValueError('Only a reported order can be accepted')
            item.update(status='closed', acceptance=args.note)
            runner.atomic_json(queue_file(), items)
            board(item, 'closed', args.note)
        elif args.command == 'reconcile':
            reconcile(items)
        else:
            for item in items:
                print(json.dumps(item, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
