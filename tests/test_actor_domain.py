import copy
import time
import unittest
from skyrim_autotest import actor_domain as domain, platform

ACTOR = {'reference': '0x00000014', 'base': '0x00000007'}


class Session:
    def __init__(self): self.events = []
    def log(self, *args, **kw): self.events.append((args, kw))


class Backend:
    def __init__(self):
        self.s = Session(); self.sex = 0; self.weight = 25.; self.race = '0x00013746'
        self.morph = 0.; self.generation = 1; self.handle = 123; self.base = ACTOR['base']
        self.calls = []; self.pauses = 0; self.pending_weight = None; self.fail = None
    def resolve(self, spec): return '0x01000801'
    def call(self, tool, req):
        self.calls.append((tool, req))
        if tool == 'console':
            self.sex = 1 - self.sex
            return {'queued': False, 'completed': True}
        return {'ok': True, 'sessionId': 's', 'loadGeneration': self.generation, 'refs': [
            {'status': 'available', 'deleted': False, 'disabled': False, 'loaded3D': True,
             'identity': {'form': ACTOR['reference'], 'loadGeneration': self.generation, 'runtimeHandle': self.handle}}]}
    def pap(self, script, function, values=None, target=None):
        self.calls.append((function, values))
        if self.fail == function: raise TimeoutError('started call timed out')
        if function == 'GetActorBase': return {'formId': self.base}
        if function == 'GetSex': return self.sex
        if function == 'GetRace': return {'formId': self.race}
        if function == 'GetWeight': return self.weight
        if function == 'GetBodyMorph': return self.morph
        if function == 'SetWeight': self.pending_weight = values[0]
        if function == 'SetRace': self.race = values[0]['form']
        if function == 'SetBodyMorph': self.morph = values[3]
    def pause(self, seconds):
        self.pauses += 1
        if self.pauses > 2: raise TimeoutError('deadline')
        self.weight = self.pending_weight


class ActorDomainTests(unittest.TestCase):
    def test_weight_one_mutation_actual_eventual_readback(self):
        b = Backend()
        result = domain.perform(b, {'action': 'set-weight', 'actor': ACTOR, 'weight': 100})
        self.assertEqual(result['actor']['weight'], 100)
        self.assertTrue(result['action']['completed'])
        self.assertEqual([c for c in b.calls if c[0] == 'SetWeight'], [('SetWeight', [100.])])
        self.assertEqual(b.pauses, 1)

    def test_timed_out_mutation_never_replayed(self):
        b = Backend(); b.fail = 'SetWeight'
        with self.assertRaises(TimeoutError): domain.perform(b, {'action': 'set-weight', 'actor': ACTOR, 'weight': 100})
        self.assertEqual(len([c for c in b.calls if c[0] == 'SetWeight']), 1)
        self.assertEqual(b.pauses, 0)

    def test_sex_observed_toggle_once_and_noop_when_already_equal(self):
        b = Backend(); req = {'action': 'set-sex', 'actor': ACTOR, 'sex': 'female'}
        self.assertEqual(domain.perform(b, req)['actor']['sex'], 'female')
        self.assertEqual(domain.perform(b, req)['actor']['sex'], 'female')
        self.assertEqual(len([c for c in b.calls if c[0] == 'console']), 1)

    def test_bad_execution_fence_does_not_claim_completion(self):
        b = Backend(); original = b.call
        b.call = lambda tool, req: {'queued': True} if tool == 'console' else original(tool, req)
        with self.assertRaisesRegex(ValueError, 'fence'): domain.perform(b, {'action': 'set-sex', 'actor': ACTOR, 'sex': 'female'})

    def test_actor_base_mismatch_before_mutation(self):
        b = Backend(); b.base = '0x8'
        with self.assertRaisesRegex(ValueError, 'base differs'): domain.perform(b, {'action': 'set-weight', 'actor': ACTOR, 'weight': 100})
        self.assertFalse(any(c[0] == 'SetWeight' for c in b.calls))

    def test_actual_morph_float_and_native_roundtrip(self):
        b = Backend(); req = {'action': 'set-body-morph', 'actor': ACTOR, 'morph': 'Example', 'key': 'Autotest', 'value': 1}
        self.assertEqual(domain.perform(b, req)['morph']['value'], 1.)
        self.assertIs(type(next(c for c in b.calls if c[0] == 'SetBodyMorph')[1][3]), float)
        self.assertEqual(domain.observe(b, {'quantity': 'body-morph-storage', 'actor': ACTOR, 'morph': 'Example', 'key': 'Autotest'})['morph']['value'], 1.)

    def test_generation_change_invalidates_even_equal_refid(self):
        b = Backend(); original = b.pap
        def pap(script, fn, values=None, target=None):
            result = original(script, fn, values, target)
            if fn == 'GetWeight': b.generation += 1
            return result
        b.pap = pap
        with self.assertRaisesRegex(ValueError, 'incarnation changed'): domain.observe_actor(b, ACTOR)

    def test_no_numeric_or_boolean_defaults_for_missing_native_values(self):
        for bad in (None, True, float('nan')):
            b = Backend(); b.weight = bad
            with self.assertRaises(ValueError): domain.observe_actor(b, ACTOR)
        b = Backend(); b.sex = True
        with self.assertRaisesRegex(ValueError, 'sex unavailable'): domain.observe_actor(b, ACTOR)

    def test_validate_exact_units_fields_and_safe_identity(self):
        req = {'action': 'set-weight', 'actor': ACTOR, 'weight': 100, 'units': 'Skyrim actor-base weight 0..100'}
        platform.validate({'operation': 'object.perform', 'request': req})
        for key, bad in [('units', 'metres'), ('weight', 101), ('actor', {'reference': 'player;quit', 'base': '0x7'})]:
            copy_req = copy.deepcopy(req); copy_req[key] = bad
            with self.assertRaises(ValueError): platform.validate({'operation': 'object.perform', 'request': copy_req})
        with self.assertRaises(ValueError): domain.validate('controller.perform', req)
        with self.assertRaises(ValueError): domain.validate('object.perform', {'action': 'set-sex', 'actor': {'reference': '0x15', 'base': '0x7'}, 'sex': 'male'})


if __name__ == '__main__': unittest.main()
