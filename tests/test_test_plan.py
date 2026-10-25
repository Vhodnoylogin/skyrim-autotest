import copy
import unittest
from skyrim_autotest.test_plan import review


def plan():
    return {'schemaVersion': 1, 'budgetMinutes': 10,
            'cases': [dict(id='common', behavior='normal interaction', weight=90, core=True, critical=False, rationale='main user flow'),
                      dict(id='rare', behavior='data survives reload', weight=10, core=False, critical=True, rationale='rare but saved-data loss is severe')],
            'scenarios': [dict(id='normal', role='subject', available=True, estimatedMinutes=2, covers=['common'], oracle='actual inventory and object readback'),
                          dict(id='reload', role='subject', available=True, estimatedMinutes=3, covers=['common', 'rare'], oracle='reload and inspect exact saved values'),
                          dict(id='startup', role='tooling', available=True, estimatedMinutes=1, covers=[])],
            'selected': ['normal']}


class TestPlanTests(unittest.TestCase):
    def test_count_weight_and_unknown_whole_mod_coverage_are_distinct(self):
        report = review(plan())
        self.assertEqual(report['plannedCaseCoveragePercent'], 50)
        self.assertEqual(report['plannedWeightedCoveragePercent'], 90)
        self.assertIsNone(report['wholeModCoveragePercent'])
        self.assertIsNone(report['executedCoveragePercent'])
        self.assertFalse(report['testingPerformed'])

    def test_rare_catastrophic_risk_still_requires_coverage(self):
        report = review(plan())
        self.assertEqual(report['missingCritical'], ['rare'])
        self.assertTrue(report['needsRevision'])

    def test_tooling_success_has_zero_subject_coverage(self):
        p = plan(); p['selected'] = ['startup']
        self.assertEqual(review(p)['plannedWeightedCoveragePercent'], 0)
        p['scenarios'][2]['covers'] = ['common']
        with self.assertRaises(ValueError): review(p)

    def test_unavailable_and_overlapping_cases_cannot_inflate_coverage(self):
        p = plan(); p['selected'] = ['normal', 'reload']
        self.assertEqual(review(p)['plannedCaseCoveragePercent'], 100)
        p['scenarios'][1]['available'] = False
        self.assertEqual(review(p)['plannedCaseCoveragePercent'], 50)
        self.assertEqual(review(p)['unavailableSelected'], ['reload'])

    def test_bounded_recommendation_prefers_core_and_critical_and_counts_marginal_gain(self):
        report = review(plan())
        self.assertEqual(report['recommendedScenarioIds'], ['reload'])
        p = plan(); p['budgetMinutes'] = 2
        self.assertEqual(review(p)['recommendedScenarioIds'], ['normal'])

    def test_duplicate_ids_unknown_cases_nonfinite_weights_and_missing_oracle_are_rejected(self):
        changes = [lambda p: p['cases'].append(copy.deepcopy(p['cases'][0])),
                   lambda p: p['scenarios'][0].update(covers=['unknown']),
                   lambda p: p['cases'][0].update(weight=float('nan')),
                   lambda p: p['cases'][0].update(weight=True),
                   lambda p: p['scenarios'][0].update(oracle=''),
                   lambda p: p.update(selected=['normal', 'normal'])]
        for change in changes:
            p = plan(); change(p)
            with self.subTest(p=p), self.assertRaises(ValueError): review(p)

    def test_budget_and_redundancy_are_visible_without_turning_planning_into_execution(self):
        p = plan(); p['selected'] = ['reload', 'normal']; p['budgetMinutes'] = 3
        report = review(p)
        self.assertEqual(report['redundantSelected'], ['normal'])
        self.assertTrue(report['needsRevision'])

    def test_empty_selection_cannot_pass_even_if_author_marks_no_case_as_core(self):
        p = plan(); p['selected'] = []
        for case in p['cases']: case.update(core=False, critical=False)
        self.assertTrue(review(p)['needsRevision'])

    def test_recommendation_reserves_selected_tool_preparation_cost(self):
        p = plan(); p['budgetMinutes'] = 9; p['selected'] = ['startup']
        p['scenarios'][2]['estimatedMinutes'] = 7
        result = review(p)
        self.assertEqual(result['recommendedScenarioIds'], ['startup', 'normal'])
        self.assertTrue(result['needsRevision'])
