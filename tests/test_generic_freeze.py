"""Exact generic member preparation may precede completion of its save roster."""
import copy
import json
import time
import unittest

from skyrim_autotest import interactive, platform, visual_freeze
from tests import test_visual_freeze as base


class GenericFreezeTests(unittest.TestCase):
    def setUp(self):
        base.VisualFreezeTests.setUp(self)
        self.s.state['configuration']['game_edition'] = 'se'
        self.settings = self.s.state['configuration']['interactive_session']
        self.settings.pop('morphSession')
        self.settings['npcPersistenceRoster'] = {'mode': 'generic-two-actor-v1',
            'fixtures': {'MThin': base.BASE, 'Second': base.BASE}}
        self.settings['allowedTools'] = ['platform', 'papyrus']
        self.s.state['interactiveActorFixtures']['MThin']['actor']['race'] = '0x000CDD84'
        self.s.raw['dontMove'] = True

    def args(self, mutate=False):
        return {'operation': 'object.perform' if mutate else 'world.read', 'request': base.request(mutate)}

    def execute(self, mutate=False):
        return platform.execute(self.s, self.args(mutate), time.monotonic()+3)

    def test_partial_born_beast_cohort_accepts_exact_frontend_read_and_freeze(self):
        for mutate in (False, True):
            envelope = {'schemaVersion': 1, 'operation': 'tool', 'tool': 'platform',
                        'args': self.args(mutate), 'timeoutSeconds': 3}
            self.assertEqual(interactive._request(json.dumps(envelope), self.settings, self.s), envelope)
        self.assertEqual(len(self.s.state['interactiveActorFixtures']), 1)
        self.assertFalse(self.execute()['fixture']['visualFrozen'])
        self.assertTrue(self.execute(True)['fixture']['visualFrozen'])
        self.assertEqual(len(self.s.mutations), 1)
        self.assertTrue(visual_freeze.require_frozen(self.s, 'MThin', time.monotonic()+3, base.POLICY)['fixture']['dontMove'])
        self.assertNotIn('morphSession', self.s.state)

    def test_foreign_wrong_base_partial_or_uncertain_member_cannot_freeze(self):
        original = copy.deepcopy(self.s.state)
        changes = [lambda f: f.update(Foreign={}), lambda f: f['MThin'].update(base='0x00000007'),
            lambda f: f['MThin'].update(status='intent'), lambda f: f['MThin'].update(runId='other'),
            lambda f: f['MThin'].update(worldGeneration=2), lambda f: f['MThin'].update(tag='Second'),
            lambda f: f.update(Second=dict(copy.deepcopy(f['MThin']), tag='Second'))]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.s.state = copy.deepcopy(original); change(self.s.state['interactiveActorFixtures'])
                with self.assertRaises(ValueError): self.execute(True)
                self.assertEqual(self.s.mutations, [])

    def test_direct_platform_partial_freeze_uses_existing_strict_native_adapter(self):
        self.assertTrue(self.execute(True)['fixture']['visualFrozen'])
        self.assertEqual(len(self.s.mutations), 1)
        self.assertEqual(self.s.mutations[0]['action'], 'freeze_visual')

    def test_missing_member_is_never_adopted_even_with_valid_roster(self):
        args = self.args(True); args['request']['actor']['fixtureTag'] = 'Second'
        with self.assertRaises(ValueError): platform.execute(self.s, args, time.monotonic()+3)
        self.assertEqual(self.s.mutations, [])

    def test_dont_move_does_not_substitute_for_ai_and_both_collision_flags(self):
        self.assertTrue(self.s.raw['dontMove'])
        with self.assertRaisesRegex(ValueError, 'AI/collision off'):
            visual_freeze.require_frozen(self.s, 'MThin', time.monotonic()+3, base.POLICY)
        self.assertEqual(self.s.mutations, [])
        self.s.unavailable = True
        with self.assertRaises(ValueError): self.execute(True)
        self.assertEqual(self.s.mutations, [])

    def test_existing_uncertain_freeze_remains_non_replayable(self):
        self.s.fail_ack = True
        with self.assertRaises(TimeoutError): self.execute(True)
        self.s.fail_ack = False
        with self.assertRaises(ValueError): self.execute(True)
        self.assertEqual(len(self.s.mutations), 1)

    def test_vr_and_unopted_generic_freeze_refuse_without_mutation(self):
        self.s.state['configuration']['game_edition'] = 'vr'
        with self.assertRaises(ValueError): self.execute(True)
        self.s.state['configuration']['game_edition'] = 'se'
        del self.settings['npcPersistenceRoster']
        with self.assertRaises(ValueError): self.execute(True)
        self.assertEqual(self.s.mutations, [])
