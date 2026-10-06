import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from skyrim_autotest import platform, scenarios
from skyrim_autotest.platform_math import solve3
from skyrim_autotest.platform_mapping import operations


class Session:
    def __init__(self):
        self.state = {'gameplayBootstrap': {'completed': True}, 'probeObject': '0xFF001234',
                      'probeObjectLive': True, 'platformReferences': {'seed-potion': {'id': '0xFF001234'}}}
        self.calls = []
        self.deadlines = []
        self.validations = 0
        self.responses = {}
    def validate_probe_reference(self, timeout=3):
        self.validations += 1
        if not self.state['probeObjectLive']: raise ValueError('generation changed')
    def tool(self, tool, args, timeout=12, deadline=None):
        self.calls.append((tool, args))
        self.deadlines.append(deadline)
        return self.responses.get(tool, {})


class PlatformTests(unittest.TestCase):
    def backend(self, session):
        return platform.Backend(session, platform.time.monotonic()+30)

    def test_native_stack_quantity_not_requested_or_default_one(self):
        session = Session()
        session.responses['inspect'] = {'refs': [{'formId': '0xFF001234', 'quantityItems': 17}]}
        backend = self.backend(session)
        backend.pap = lambda *a, **k: True
        backend.item = lambda ref: {'plugin': 'Actual.esp', 'localId': '002345'}
        observed = backend.observe({'observation': 'reference.state', 'referenceTag': 'seed-potion'})
        self.assertEqual(observed['reference']['quantity']['items'], 17)
        self.assertEqual(observed['reference']['item']['plugin'], 'Actual.esp')
        self.assertTrue(session.validations)
        del session.responses['inspect']['refs'][0]['quantityItems']
        with self.assertRaisesRegex(ValueError, 'stack-count'): backend.observe({'observation': 'reference.state', 'referenceTag': 'seed-potion'})

    def test_wrong_ref_cannot_supply_native_quantity(self):
        session = Session()
        session.responses['inspect'] = {'refs': [{'formId': '0xFF009999', 'quantityItems': 1}]}
        with self.assertRaises(ValueError): self.backend(session).observe({'observation': 'reference.state', 'referenceTag': 'seed-potion'})

    def test_invalidated_generation_never_reuses_tag_or_held_pointer(self):
        session = Session()
        session.state['probeObjectLive'] = False
        with self.assertRaisesRegex(ValueError, 'generation'): self.backend(session).tagged({'referenceTag': 'seed-potion'})
        with self.assertRaisesRegex(ValueError, 'generation'): self.backend(session).held({'hand': 'right', 'continuityWindowSeconds': 0})
        self.assertEqual(session.calls, [])

    def test_missing_hand_identity_is_not_an_empty_hand(self):
        backend = self.backend(Session())
        backend.pap = lambda *a, **k: {}
        with self.assertRaisesRegex(ValueError, 'identity'): backend.held({'hand': 'right', 'continuityWindowSeconds': 0})
        backend.pap = lambda *a, **k: None
        self.assertFalse(backend.held({'hand': 'right', 'continuityWindowSeconds': 0})['hand']['occupied'])

    def test_form_type_uses_inspect_code_not_numeric_papyrus_type(self):
        session = Session()
        session.responses['inspect'] = {'refs': [{'formId': '0x0003EADD', 'formType': 'ALCH'}]}
        backend = self.backend(session)
        backend.pap = lambda *a: {'formId': '0x0003EADD', 'formType': '46'}
        self.assertEqual(backend.resolve({'plugin': 'Skyrim.esm', 'localId': '03EADD', 'type': 'ALCH'}), '0x0003EADD')
        session.responses['inspect']['refs'][0]['formType'] = 'WEAP'
        with self.assertRaises(ValueError): backend.resolve({'plugin': 'Skyrim.esm', 'localId': '03EADD', 'type': 'ALCH'})

    def test_inventory_mutation_delta_once_then_verified(self):
        backend = self.backend(Session())
        backend.resolve = lambda *a: '0x0003EADD'
        counts = iter([7, 2])
        mutations = []
        def pap(script, function, values, target):
            if function == 'GetItemCount': return next(counts)
            mutations.append((function, values))
        backend.pap = pap
        req = {'action': 'set_fixture_inventory_quantity', 'owner': 'player',
               'item': {'plugin': 'Skyrim.esm', 'localId': '03EADD'}, 'quantityItems': 2}
        self.assertEqual(backend.mutate(req)['inventory']['quantity']['items'], 2)
        self.assertEqual(mutations, [('RemoveItem', [{'form': '0x0003EADD'}, 5, True, None])])

    def test_bootstrap_and_deadline_are_required_before_mutation(self):
        session = Session()
        session.state['gameplayBootstrap']['completed'] = False
        with self.assertRaisesRegex(ValueError, 'bootstrap'):
            platform.execute(session, {'operation': 'controller.perform', 'request': {'action': 'release_all'}}, platform.time.monotonic()+10)
        self.assertEqual(session.calls, [])
        session.state['gameplayBootstrap']['completed'] = True
        with self.assertRaises(TimeoutError):
            platform.execute(session, {'operation': 'controller.perform', 'request': {'action': 'release_all'}}, platform.time.monotonic()-1)
        self.assertEqual(session.calls, [])

    def test_only_read_operations_may_poll_and_fields_are_explicit(self):
        step = {'name': 'x', 'tool': 'platform', 'args': {'operation': 'controller.perform', 'request': {'action': 'release_all'}},
                'poll': True, 'assert': [{'path': 'released', 'equals': True}]}
        with self.assertRaisesRegex(ValueError, 'Polling'): scenarios.validate({'schemaVersion': 1, 'steps': [step]})
        with self.assertRaises(ValueError): platform.validate({'operation': 'object.perform', 'request': {'action': 'console', 'command': 'anything'}})
        with self.assertRaises(ValueError): platform.validate({'operation': 'world.read', 'request': {'observation': 'body_slot.display', 'slot': 13, 'guess': True}})

    def test_live_readiness_not_bootstrap_flag_alone(self):
        session = Session()
        session.responses.update(inspect={'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}},
                                 menu={'messageBoxOpen': True, 'openMenus': ['HUD Menu', 'MessageBoxMenu']})
        observed = platform.execute(session, {'operation': 'state.read'}, platform.time.monotonic()+10)
        self.assertFalse(observed['world']['ready'])
        self.assertTrue(all(d == session.deadlines[0] for d in session.deadlines))

    def test_measured_tracking_solve_axes_and_singular_failure(self):
        columns = [[70, 0, 0], [0, 0, 70], [0, -70, 0]]
        self.assertEqual(solve3(columns, [7, -14, 21]), [.1, .3, .2])
        with self.assertRaisesRegex(ValueError, 'singular'): solve3([[0,0,0]]*3, [1,2,3])

    def test_local_dispatch_preserves_step_deadline_and_field_names(self):
        class Fake:
            state = {'checks': []}
            def phase(self, *a): pass
            def save(self): pass
            def tool(self, name, args, timeout, deadline):
                self.deadline = deadline
                return {'world': {'ready': True}}
        session = Fake()
        scenario = {'schemaVersion': 1, 'steps': [{'name': 'check', 'tool': 'platform', 'args': {'operation': 'state.read'},
                    'assert': [{'path': 'world.ready', 'equals': True}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            session.dir = Path(tmp)
            scenarios.execute(session, scenario)
        self.assertGreater(session.deadline, platform.time.monotonic())
        self.assertEqual(session.state['checks'][0]['name'], 'check')
        self.assertEqual(operations()['world.read']['fields']['hand.reference.id'], 'hand.reference.id')


if __name__ == '__main__': unittest.main()
