"""Prepare a standalone held bridge without changing the original semantic order.

No installation, launch, admission, qualification or owner authority is created.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from skyrim_autotest import scenarios, semantic_companion


def _read(path):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value: raise ValueError('Duplicate JSON key')
            value[key] = item
        return value
    def invalid(value): raise ValueError('Nonfinite JSON value: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=pairs, parse_constant=invalid)


def pin(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def compile_scenario(order, manifest):
    """Faithful data-only polygon-actions/1 operation/field substitution.

    Dashboard independently repeats its authoritative compile_plan; this check
    ensures preparation never silently substitutes an unreviewed compiled file.
    """
    if type(order) is not dict or order.get('schemaVersion') != 2:
        raise ValueError('The unchanged schema2 semantic order is required')
    plan = order.get('subjectPlan', {})
    if type(plan) is not dict or plan.get('interface') != 'polygon-actions/1' or set(plan) != {'interface', 'fixture', 'steps'}:
        raise ValueError('Original polygon-actions/1 subject plan required')
    operations = manifest.get('operations', {})
    result = {'schemaVersion': 1, 'steps': []}
    fixture = plan['fixture']
    for key in ('cell', 'startMode'):
        if key in fixture: result[key] = copy.deepcopy(fixture[key])
    if 'save' in fixture: result['fixture'] = copy.deepcopy(fixture['save'])
    for step in plan['steps']:
        adapter = operations.get(step['operation'])
        if type(adapter) is not dict or set(adapter) != {'tool', 'args', 'fields'} or type(adapter['fields']) is not dict:
            raise ValueError('Complete reviewed native operation mapping required')
        def bind(value):
            if isinstance(value, dict):
                if '$parameter' in value:
                    if set(value) != {'$parameter'} or value['$parameter'] not in step.get('parameters', {}):
                        raise ValueError('Invalid exact platform parameter binding')
                    return copy.deepcopy(step['parameters'][value['$parameter']])
                return {key: bind(item) for key, item in value.items()}
            if isinstance(value, list): return [bind(item) for item in value]
            return value
        compiled = {'name': step['name'], 'tool': adapter['tool'], 'args': bind(adapter['args'])}
        for key in ('timeout', 'poll', 'observe'):
            if key in step: compiled[key] = copy.deepcopy(step[key])
        compiled['assert'] = []
        for rule in step.get('assert', []):
            path = adapter['fields'].get(rule['field'])
            if not isinstance(path, str): raise ValueError('Unmapped semantic observation: ' + rule['field'])
            compiled['assert'].append({'path': path, **{key: copy.deepcopy(value) for key, value in rule.items() if key != 'field'}})
        result['steps'].append(compiled)
    return result


def prepare(order_path, manifest_path, compiled_path, output, maximum_seconds, maximum_commands=2048):
    order_path, manifest_path, compiled_path = map(lambda value: Path(value).resolve(), (order_path, manifest_path, compiled_path))
    before = {str(path): pin(path) for path in (order_path, manifest_path, compiled_path)}
    order, mapping, compiled = map(_read, (order_path, manifest_path, compiled_path))
    expected = compile_scenario(order, mapping)
    if compiled != expected: raise ValueError('Compiled native scenario differs from the unchanged order and selected mapping')
    scenarios.validate(compiled)
    if type(maximum_commands) is not int or maximum_commands < len(compiled['steps']) + 1:
        raise ValueError('Command bound must cover every original step plus exactly one finish')
    spec = {'schemaVersion': 1, 'interface': semantic_companion.INTERFACE,
        'subjectOrderSha256': semantic_companion.canonical_hash(order), 'originalTesting': copy.deepcopy(order['testing']),
        'scenario': compiled, 'bounds': {'maximumSeconds': maximum_seconds, 'maximumCommands': maximum_commands},
        'provenance': {'order': before[str(order_path)], 'mappingManifest': before[str(manifest_path)],
                       'compiledScenario': before[str(compiled_path)],
                       'sourcePlanSha256': semantic_companion.canonical_hash(order['subjectPlan'])}}
    spec = semantic_companion.validate_spec(spec)
    output = Path(output).resolve()
    if any((parent / '.git').exists() for parent in (output, *output.parents)):
        raise ValueError('Generated bridge artifacts must stay outside Git')
    if output.exists(): raise ValueError('A new external output folder is required; never overwrite a frozen bridge')
    output.mkdir(parents=True)
    def write(name, value):
        with (output / name).open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    write('semantic-spec.json', spec)
    execution = {'schemaVersion': 1, 'kind': 'held-semantic-plan',
        'checks': [{'name': step['name'], 'role': 'subject'} for step in compiled['steps']],
        'fixture': {'cell': compiled.get('cell')}, 'bounds': spec['bounds'], 'semantic': spec,
        'protocolBoundaryMeaning': 'Transport preparation boundary only; Dashboard independently projects originalTesting.start'}
    write('execution-plan.json', execution)
    with (output / 'sequencer.py').open('x', encoding='utf-8', newline='\n') as stream: stream.write(semantic_companion.render(spec))
    for path, old in before.items():
        if pin(path) != old: raise ValueError('A source input changed during preparation; do not use generated artifacts')
    receipt = {'schemaVersion': 1, 'kind': 'held-semantic-preparation-only', 'inputs': list(before.values()),
        'interpreterSource': pin(Path(semantic_companion.__file__)), 'preparationSource': pin(__file__),
        'files': [pin(output / name) for name in ('semantic-spec.json', 'execution-plan.json', 'sequencer.py')],
        'subjectOrderSha256': spec['subjectOrderSha256'], 'originalOrderRewritten': False,
        'nativeStarts': 0, 'qualified': False, 'admitted': False, 'subjectAccepted': False}
    write('preparation-manifest.json', receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--order', required=True, type=Path)
    parser.add_argument('--mapping-manifest', required=True, type=Path)
    parser.add_argument('--compiled-scenario', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--maximum-seconds', required=True, type=int)
    parser.add_argument('--maximum-commands', type=int, default=2048)
    args = parser.parse_args(argv)
    result = prepare(args.order, args.mapping_manifest, args.compiled_scenario, args.output, args.maximum_seconds, args.maximum_commands)
    print(json.dumps({'output': str(args.output), 'subjectOrderSha256': result['subjectOrderSha256'], 'admitted': False, 'launched': False}))


if __name__ == '__main__': main()
