"""Review declared behavior coverage without pretending to measure a whole mod."""
import argparse
import json
import math
from pathlib import Path
import re


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', value):
        raise ValueError('Case/scenario identifiers must be stable, safe and unique')
    return value


def _number(value, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError('Weights, budget and estimated minutes must be finite and positive')
    return value


def review(plan):
    if not isinstance(plan, dict) or plan.get('schemaVersion') != 1:
        raise ValueError('Test plan needs schemaVersion1')
    budget = _number(plan.get('budgetMinutes'), 1440)
    rows, scenarios = plan.get('cases'), plan.get('scenarios')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise ValueError('Declare1..256 behavior cases')
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 256:
        raise ValueError('Declare1..256 scenarios')
    cases, tests = {}, {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Case must be an object')
        key = _identifier(row.get('id'))
        if key in cases:
            raise ValueError('Duplicate case: ' + key)
        _number(row.get('weight'), 100)
        if any(type(row.get(k)) is not bool for k in ('core', 'critical')):
            raise ValueError('Case core/critical flags must be explicit booleans')
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in ('behavior', 'rationale')):
            raise ValueError('Case needs behavior and relevance/weight rationale')
        cases[key] = row
    for row in scenarios:
        if not isinstance(row, dict):
            raise ValueError('Scenario must be an object')
        key = _identifier(row.get('id'))
        if key in tests:
            raise ValueError('Duplicate scenario: ' + key)
        _number(row.get('estimatedMinutes'), 1440)
        covers = row.get('covers')
        if (not isinstance(covers, list) or any(not isinstance(c, str) or c not in cases for c in covers)
                or len(set(covers)) != len(covers)):
            raise ValueError('Scenario covers must reference distinct declared cases')
        if row.get('role') not in ('subject', 'tooling') or type(row.get('available')) is not bool:
            raise ValueError('Scenario needs subject/tooling role and explicit availability')
        if row['role'] == 'tooling' and covers:
            raise ValueError('Tool health does not cover mod behavior')
        if row['role'] == 'subject' and (not covers or not isinstance(row.get('oracle'), str) or not row['oracle'].strip()):
            raise ValueError('Subject scenario needs covered behavior and an observed-result oracle')
        tests[key] = row
    selected = plan.get('selected')
    if (not isinstance(selected, list) or any(not isinstance(k, str) or k not in tests for k in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError('selected must contain distinct declared scenario IDs')
    eligible = [tests[k] for k in selected if tests[k]['available']]
    covered = set().union(*(set(t['covers']) for t in eligible))
    total_weight = sum(c['weight'] for c in cases.values())
    weighted = sum(cases[k]['weight'] for k in covered)
    missing_core = [k for k, c in cases.items() if c['core'] and k not in covered]
    missing_critical = [k for k, c in cases.items() if c['critical'] and k not in covered]
    minutes = sum(t['estimatedMinutes'] for t in eligible)
    warnings = []
    if not covered:
        warnings.append('No available subject behavior is selected')
    if missing_core:
        warnings.append('Core user behavior remains uncovered')
    if missing_critical:
        warnings.append('Critical risks remain uncovered even if rare')
    if minutes > budget:
        warnings.append('Selected estimated duration exceeds the declared budget')
    unavailable = [k for k in selected if not tests[k]['available']]
    if unavailable:
        warnings.append('Unavailable scenarios contribute no planned coverage')
    seen, redundant = set(), []
    for t in eligible:
        if t['role'] == 'subject' and set(t['covers']) <= seen:
            redundant.append(t['id'])
        seen.update(t['covers'])
    if redundant:
        warnings.append('Some selected scenarios add no declared behavior; justify independent variants or remove them')
    # Recommend marginal behavior coverage per minute, prioritizing explicit
    # core and catastrophic-risk cases. This is advice, never a launch decision.
    remaining = [t for t in tests.values() if t['role'] == 'subject' and t['available']]
    tooling = [t for t in eligible if t['role'] == 'tooling']
    recommended = [t['id'] for t in tooling]
    recommendation_covered = set()
    spent = sum(t['estimatedMinutes'] for t in tooling)
    while remaining:
        feasible = [t for t in remaining if spent + t['estimatedMinutes'] <= budget
                    and set(t['covers']) - recommendation_covered]
        if not feasible:
            break
        def score(t):
            new = set(t['covers']) - recommendation_covered
            required = sum(bool(cases[k]['core'] or cases[k]['critical']) for k in new)
            return (bool(required), required / t['estimatedMinutes'],
                    sum(cases[k]['weight'] for k in new) / t['estimatedMinutes'])
        best = max(feasible, key=score)
        recommended.append(best['id'])
        recommendation_covered.update(best['covers'])
        spent += best['estimatedMinutes']
        remaining.remove(best)
    return {
        'schemaVersion': 1, 'kind': 'test-plan-review',
        'coverageBasis': 'declared behavior cases; author-estimated relevance weights',
        'wholeModCoveragePercent': None, 'executedCoveragePercent': None,
        'declaredCaseCount': len(cases), 'plannedCoveredCaseCount': len(covered),
        'plannedCaseCoveragePercent': round(100 * len(covered) / len(cases), 2),
        'plannedWeightedCoveragePercent': round(100 * weighted / total_weight, 2),
        'missingCases': sorted(set(cases) - covered), 'missingCore': missing_core,
        'missingCritical': missing_critical, 'unavailableSelected': unavailable,
        'redundantSelected': redundant, 'estimatedMinutes': minutes,
        'budgetMinutes': budget, 'warnings': warnings,
        'recommendedScenarioIds': recommended,
        'recommendationLimit': 'Greedy planning advice, not an optimality proof or permission to run',
        'needsRevision': bool(not covered or missing_core or missing_critical or unavailable or minutes > budget),
        'testingPerformed': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        result = review(json.loads(args.plan.read_text(encoding='utf-8-sig')))
        text = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
        if args.output:
            path = args.output.resolve()
            if any((p / '.git').exists() for p in [path.parent, *path.parents]):
                raise ValueError('Review output belongs outside Git')
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as stream:
                stream.write(text)
        print(text, end='')
        return 2 if result['needsRevision'] else 0
    except (ValueError, OSError) as error:
        print(json.dumps({'result': 'invalid-plan', 'reason': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
