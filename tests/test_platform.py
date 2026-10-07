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
    def log(self, *args, **kwargs): pass
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
        def pap(script, function, values, target, **kwargs):
            if function == 'GetItemCount': return next(counts)
            mutations.append((function, values, kwargs))
        backend.pap = pap
        req = {'action': 'set_fixture_inventory_quantity', 'owner': 'player',
               'item': {'plugin': 'Skyrim.esm', 'localId': '03EADD'}, 'quantityItems': 2}
        self.assertEqual(backend.mutate(req)['inventory']['quantity']['items'], 2)
        self.assertEqual(mutations, [('RemoveItem', [{'form': '0x0003EADD'}, 5, True], {'fill_neutral': True})])

    def test_remove_destination_neutral_is_explicit_and_other_calls_stay_strict(self):
        session = Session()
        session.responses['papyrus'] = {'returned': None}
        backend = self.backend(session)
        backend.pap('ObjectReference', 'RemoveItem', [{'form': '0x0003EADD'}, 2, True], '0x14', fill_neutral=True)
        self.assertTrue(session.calls[-1][1]['fillNeutral'])
        self.assertNotIn(None, session.calls[-1][1]['args'])
        backend.pap('ObjectReference', 'GetItemCount', [{'form': '0x0003EADD'}], '0x14')
        self.assertNotIn('fillNeutral', session.calls[-1][1])

    def test_integer_health_spec_uses_native_float_vm_arguments_and_observed_result(self):
        backend = self.backend(Session())
        calls = []
        def pap(script, function, values, target):
            calls.append((function, values))
            if function == 'GetActorValue': return 299.5
        backend.pap = pap
        result = backend.mutate({'action': 'set_fixture_health', 'baseHealthPoints': 500,
                                 'damageHealthPoints': 200})
        self.assertEqual(result['player']['health']['points'], 299.5)
        for function, values in calls[:-1]: self.assertIs(type(values[1]), float)
        self.assertEqual(calls[0], ('SetActorValue', ['Health', 500.0]))
        self.assertEqual(calls[2], ('DamageActorValue', ['Health', 200.0]))

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

    @patch('skyrim_autotest.vr_probe.ensure_owned_focus')
    def test_explicit_initial_pose_before_subject_is_open_and_keeps_head(self, focus):
        class Fake(Session):
            def phase(self, *args): self.phase_name = args[0]
            def log(self, *args, **kwargs): self.logged = kwargs
            def tool(self, tool, args, **kwargs):
                result = super().tool(tool, args, **kwargs)
                return {'returned': True} if tool == 'papyrus' else result
        session = Fake()
        session.state.update(inputBackend='driver', driverBackend='file')
        platform.initialize_controllers(session, {'controller_start_positions_metres': {'left': [-.3,.3,-.55], 'right': [0,.3,-.55]}})
        frame = session.calls[-1][1]['frame']
        self.assertEqual([frame['right']['matrix'][i] for i in (3,7,11)], [0,.3,-.55])
        self.assertEqual(frame['hmd']['matrix'][7], 1.65)
        self.assertEqual(frame['right']['controller']['pressed'], 0)
        self.assertEqual(frame['left']['controller']['pressed'], 0)
        self.assertFalse(session.logged['subjectAction'])
        self.assertTrue(session.logged['consumedByGameNotProven'])
        self.assertEqual([a['function'] for t,a in session.calls if t == 'papyrus'],
                         ['EnablePlayerControls', 'IsMovementControlsEnabled', 'IsFightingControlsEnabled',
                          'IsLookingControlsEnabled', 'IsActivateControlsEnabled'])
        focus.assert_called_once()
        session.state['gameplayBootstrap']['completed'] = False
        session.calls.clear()
        with self.assertRaises(ValueError): platform.initialize_controllers(session, {'controller_start_positions_metres': {'left': [0,0,0], 'right': [0,0,0]}})
        self.assertEqual(session.calls, [])

    def test_start_pose_configuration_fails_bad_dimensions_or_units(self):
        from skyrim_autotest.config import configure, template, ConfigurationError
        config = template()
        config['controller_start_positions_metres'] = {'right': [0,.3,-.55], 'left': [-.3,.3,-.55]}
        configure(config)
        for bad in ({'right': [0,0,0]}, {'right': [0,3,0], 'left': [0,0,0]},
                    {'right': [0,True,0], 'left': [0,0,0]}, {'right': [0,float('nan'),0], 'left': [0,0,0]}):
            with self.subTest(bad=bad):
                config['controller_start_positions_metres'] = bad
                with self.assertRaises(ConfigurationError): configure(config)

    def test_recorded_geometry_keeps_original_half_metre_bound(self):
        columns = [[-11.8976,68.9795,0], [0,0,70], [68.9813,11.8994,0]]
        baseline = [-381.05688,2056.01636,7067.85010]
        target = [-411.90506,2026.27026,6991.82471]
        old_delta = solve3(columns, [t-b for t,b in zip(target,baseline)])
        self.assertGreater(sum(v*v for v in old_delta)**.5, .5)
        shift = [-.3,-.9,-.2]  # Initial platform pose difference, before bounded reach.
        prepared = [baseline[r]+sum(columns[c][r]*shift[c] for c in range(3)) for r in range(3)]
        new_delta = solve3(columns, [t-b for t,b in zip(target,prepared)])
        self.assertLess(sum(v*v for v in new_delta)**.5, .5)

    @patch('skyrim_autotest.vr_probe.ensure_owned_focus')
    def test_measured_physical_reach_uses_open_calibration_and_bounded_motion(self, focus):
        import copy
        from skyrim_autotest.hardware import neutral
        columns = [[-11.8976,68.9795,0], [0,0,70], [68.9813,11.8994,0]]
        baseline = [-381.05688,2056.01636,7067.85010]
        reference = [-411.90506,2026.27026,6981.82471]
        origin = [.3,1.2,-.35]
        class Fake(Session):
            def log(self, kind, **kwargs):
                if kind == 'platform-reach-position': self.increments.append(kwargs['trackingIncrementMetres'])
            def tool(self, tool, args, **kwargs):
                self.calls.append((tool, copy.deepcopy(args)))
                if tool == 'driver': self.state['hardwareFrame'] = copy.deepcopy(args['frame'])
                if tool == 'menu':
                    self.menu_observed = True
                    return {'messageBoxOpen': False, 'openMenus': [], 'menuStates': []}
                return {'published': True, 'acknowledgedByDriver': False}
        for prepared, escaped, collision in ((False, False, False), (True, False, False), (True, True, False), (True, False, True)):
            with self.subTest(prepared=prepared, escaped=escaped):
                session = Fake()
                session.increments, session.menu_observed = [], False
                frame = neutral()
                if prepared:
                    for i,v in zip((3,7,11), [0,.3,-.55]): frame['right']['matrix'][i] = v
                session.state['hardwareFrame'] = frame
                backend = self.backend(session)
                backend.pause = lambda seconds: None
                backend.xyz = lambda ref: [v+(350 if escaped and session.menu_observed else 0) for v in reference]
                def pap(script, function, *a, **k):
                    if function == 'CanGrabObject': return True
                    if function == 'GetGrabbedObject': return {'formId': '0xFF001234'}
                    return 260.2147521972656
                backend.pap = pap
                def hand_xyz(hand):
                    point = [session.state['hardwareFrame'][hand]['matrix'][i] for i in (3,7,11)]
                    return [baseline[r]+sum(columns[c][r]*(point[c]-origin[c]) for c in range(3)) for r in range(3)]
                backend.hand_xyz = hand_xyz
                if collision:
                    moving = list(reference)
                    def dynamic_xyz(ref):
                        # Recorded blocker: open hand pushes bottle before grip.
                        if sum((a-b)**2 for a,b in zip(hand_xyz('right'), moving))**.5 < 15:
                            moving[1] -= 1
                        return list(moving)
                    backend.xyz = dynamic_xyz
                def center(ref, hand=None):
                    position=hand_xyz('right')
                    shoulder=[reference[0],reference[1],reference[2]+70]
                    backend._reach_body={'hand':position,'shoulder':shoulder,
                                         'elbow':[(a+b)/2 for a,b in zip(shoulder,position)]}
                    return backend.xyz(ref)
                backend.reference_center = center
                req = {'action': 'reach_and_grip_reference', 'hand': 'right', 'grip': 'closed',
                       'holdSeconds': 2, 'maximumReachMetres': .5, 'referenceTag': 'seed-potion'}
                if escaped:
                    with self.assertRaisesRegex(ValueError, 'body reach envelope'): backend.controller(req)
                    self.assertTrue(all(args['frame']['right']['controller']['pressed'] == 0
                                        for tool,args in session.calls if tool == 'driver'))
                else:
                    result = backend.controller(req)
                    self.assertIsNone(result['observedGameplaySuccess'])
                    self.assertEqual(session.calls[-1][1]['frame']['right']['controller']['pressed'], 4)
                    start = [0,.3,-.55] if prepared else origin
                    end = [session.calls[-1][1]['frame']['right']['matrix'][i] for i in (3,7,11)]
                    if prepared:self.assertLess(sum((a-b)**2 for a,b in zip(end,start))**.5, .5)
                    else:self.assertGreater(sum((a-b)**2 for a,b in zip(end,start))**.5, .5)
                    # Small-bottle regression: the old long-clutter landmark
                    # left the hand over 23 game units from the reference.
                    # This checks approach distance, not collision/selection.
                    reached = hand_xyz('right')
                    self.assertLess(sum((a-b)**2 for a,b in zip(reached,reference))**.5, 18)
                    self.assertGreater(sum((a-b)**2 for a,b in zip(reached,reference))**.5, 15)
                    self.assertGreater(len(session.increments), 1)
                    self.assertTrue(all(sum(v*v for v in delta)**.5 <= .01000001 for delta in session.increments))

    @patch('skyrim_autotest.vr_probe.ensure_owned_focus', side_effect=AssertionError('foreground denied'))
    def test_focus_denial_prevents_controller_publication(self, focus):
        session = Session()
        with self.assertRaisesRegex(AssertionError, 'foreground denied'):
            self.backend(session).controller({'action': 'release_reference', 'hand': 'right',
                                             'referenceTag': 'seed-potion', 'settleSeconds': 0})
        self.assertEqual(session.calls, [])

    @patch('skyrim_autotest.vr_probe.ensure_owned_focus')
    def test_disabled_controls_stop_common_stage_before_pose_publication(self, focus):
        class Fake(Session):
            def phase(self, *args): pass
            def log(self, *args, **kwargs): pass
        session = Fake()
        session.state.update(inputBackend='driver', driverBackend='file')
        session.responses['papyrus'] = {'returned': False}
        with self.assertRaisesRegex(AssertionError, 'remain disabled'):
            platform.initialize_controllers(session, {'controller_start_positions_metres':
                                                     {'left': [0,0,0], 'right': [0,0,0]}})
        self.assertFalse(any(t == 'driver' for t,a in session.calls))

    def test_native_menu_flags_allow_benign_rollover_without_name_whitelist(self):
        row = dict(name='AnyCustomRollover', available=True, alwaysOpen=False,
                   pausesGame=False, modal=False, usesCursor=False,
                   usesMenuContext=False, freezeFramePause=False)
        state = dict(messageBoxOpen=False, openMenus=[row['name']], menuStates=[row])
        self.assertFalse(platform.menus_block_gameplay(state))
        for flag in ('pausesGame', 'modal', 'usesCursor', 'usesMenuContext', 'freezeFramePause'):
            with self.subTest(flag=flag):
                row[flag] = True
                self.assertTrue(platform.menus_block_gameplay(state))
                row[flag] = False
        row['available'] = False
        self.assertTrue(platform.menus_block_gameplay(state))

    def test_missing_or_inconsistent_menu_flags_never_claim_gameplay_ready(self):
        for state in ({'messageBoxOpen': False, 'openMenus': ['WSActivateRollover']},
                      {'messageBoxOpen': False, 'openMenus': ['MessageBoxMenu'], 'menuStates': []},
                      {'messageBoxOpen': True, 'openMenus': [], 'menuStates': []}):
            self.assertTrue(platform.menus_block_gameplay(state))


if __name__ == '__main__': unittest.main()


class PoseMotionTests(unittest.TestCase):
    def test_large_held_translation_keeps_grip_and_rigid_rotations(self):
        import copy, math
        from skyrim_autotest.hardware import neutral, quaternion
        from skyrim_autotest.platform_math import pose_frames
        start=neutral();start['left']['controller']['pressed']=4
        target=copy.deepcopy(start);target['left']['matrix'][7]+= .9
        target['left']['matrix'][:3]=[-1,0,0]
        target['left']['matrix'][4:7]=[0,-1,0]
        frames=list(pose_frames(start,target)); previous=start
        self.assertGreaterEqual(len(frames),90)
        for frame in frames:
            self.assertEqual(frame['left']['controller']['pressed'],4)
            for role in ('hmd','left','right'):
                a,b=previous[role]['matrix'],frame[role]['matrix']
                self.assertLessEqual(math.dist([a[i] for i in (3,7,11)],[b[i] for i in (3,7,11)]),.0100001)
                quaternion(b)
            previous=frame
        for a,b in zip(frames[-1]['left']['matrix'],target['left']['matrix']):self.assertAlmostEqual(a,b)
        self.assertEqual(start['left']['matrix'][7],neutral()['left']['matrix'][7])

    @patch('skyrim_autotest.vr_probe.ensure_owned_focus')
    def test_pose_controller_publishes_smooth_held_path_before_endpoint(self, focus):
        import copy, math
        from skyrim_autotest.hardware import neutral
        session=Session();session.log=lambda *a,**k: None;session.state['hardwareFrame']=neutral()
        session.state['hardwareFrame']['left']['controller'].update(pressed=4,touched=4)
        session.state['hardwareFrame']['left']['matrix'][7]=.3
        backend=platform.Backend(session,platform.time.monotonic()+30);backend.pause=lambda seconds: None
        start=copy.deepcopy(session.state['hardwareFrame']);frames=[]
        def publish(frame,duration):
            frames.append(copy.deepcopy(frame));session.state['hardwareFrame']=copy.deepcopy(frame)
            return {'published':True}
        backend.publish=publish
        req={'action':'pose_and_grip','hand':'left','trackingPosition':{'units':'metres','xyz':[-.4,1.2,-.5]},
             'trackingOrientation':{'quaternionXYZW':[0,0,0,1]},'referenceHeadPosition':{'units':'metres','xyz':[0,1.65,0]},
             'otherHandPosition':{'units':'metres','xyz':[.4,1.2,-.5]},'grip':'closed','durationSeconds':1.5}
        backend.controller(req)
        previous=start
        self.assertGreater(len(frames),90)
        for frame in frames:
            self.assertEqual(frame['left']['controller']['pressed'],4)
            self.assertLessEqual(math.dist([previous['left']['matrix'][i] for i in (3,7,11)],
                                          [frame['left']['matrix'][i] for i in (3,7,11)]),.0100001)
            previous=frame


class MultiTagAlchemyTests(unittest.TestCase):
    def backend(self, session=None):
        return platform.Backend(session or Session(), platform.time.monotonic()+60)

    def test_second_tag_independent_of_consumed_anchor(self):
        session = Session()
        session.state['platformReferences']['poison'] = {'id': '0xFF005678'}
        backend = self.backend(session)
        # Lifecycle validation reads event continuity, never the anchor's object.
        self.assertEqual(backend.tagged({'referenceTag': 'poison'}), '0xFF005678')
        session.state['probeObjectLive'] = False
        with self.assertRaisesRegex(ValueError, 'generation'):
            backend.tagged({'referenceTag': 'poison'})
        self.assertEqual(session.calls, [])

    def request(self, tag='poison'):
        return {'action': 'create_fixture_reference', 'referenceTag': tag,
                'item': {'plugin': 'Skyrim.esm', 'localId': '03EADD'},
                'quantityItems': 1,
                'placement': 'settled reachable surface away from slot 13 and mouth'}

    def test_duplicate_cap_and_stale_world_refuse_before_mutation(self):
        for reason in ('duplicate', 'cap', 'stale'):
            session = Session()
            req = self.request()
            if reason == 'duplicate': req['referenceTag'] = 'seed-potion'
            if reason == 'cap':
                session.state['platformReferences'] = {str(i): {'id': hex(i+1)} for i in range(16)}
            if reason == 'stale': session.state['probeObjectLive'] = False
            with self.assertRaises(ValueError): self.backend(session).mutate(req)
            self.assertEqual(session.calls, [])

    def test_new_tag_preserves_prior_and_does_not_rebind_world(self):
        session = Session()
        session.save = lambda: None
        session.capture_probe_cursor = lambda: self.fail('must preserve old cursor')
        session.bind_probe_reference = lambda *args: self.fail('must not rebind world')
        backend = self.backend(session)
        calls = []
        def pap(script, function, values=None, target=None):
            calls.append(function)
            return {'PlaceAtMe': {'formId': '0xFF005678'}, 'GetAngleZ': 0,
                    'Is3DLoaded': True, 'GetMass': 1}.get(function)
        backend.pap = pap
        backend.resolve = lambda spec: '0x0003EADD'
        backend.xyz = lambda ref: [1, 2, 3]
        backend.pause = lambda value: None
        backend.remaining = lambda: 30
        with patch.object(platform.time, 'monotonic', side_effect=range(100)):
            backend.mutate(self.request())
        self.assertEqual(session.state['platformReferences'], {
            'seed-potion': {'id': '0xFF001234'}, 'poison': {'id': '0xFF005678'}})
        self.assertEqual(session.state['probeObject'], '0xFF001234')
        self.assertEqual(calls.count('PlaceAtMe'), 1)
        self.assertGreaterEqual(session.validations, 3)

    def test_recycled_reference_id_not_adopted(self):
        session = Session()
        backend = self.backend(session)
        backend.resolve = lambda spec: '0x0003EADD'
        backend.pap = lambda *a, **k: {'formId': '0xFF001234'}
        with self.assertRaisesRegex(ValueError, 'ID reused'):
            backend.mutate(self.request())
        self.assertEqual(list(session.state['platformReferences']), ['seed-potion'])

    def alchemy_backend(self, overrides=None):
        backend = self.backend()
        values = {'IsPoison': True, 'IsHostile': False, 'IsFood': False,
                  'GetNumEffects': 1, 'GetNthEffectMagicEffect': {'formId': '0x00012345'},
                  'GetNthEffectMagnitude': 17.5, 'GetNthEffectArea': 0, 'GetNthEffectDuration': 3}
        values.update(overrides or {})
        backend.resolve = lambda spec: '0x0003EADD' if spec['type'] == 'ALCH' else None
        backend.call = lambda *a: {'refs': [{'formType': 'MGEF'}]}
        backend.pap = lambda script, function, values_arg=None, target=None: (
            values_arg == [4] if function == 'IsEffectFlagSet' else values[function])
        return backend

    def test_alchemy_actual_flags_effects_and_no_poison_hostile_conflation(self):
        value = self.alchemy_backend().observe({'observation': 'form.alchemy', 'form': {}})['alchemy']
        self.assertTrue(value['poison'])
        self.assertFalse(value['hostile'])
        self.assertTrue(value['hasDetrimentalEffect'])
        self.assertEqual(value['effects'][0]['runtimeId'], '0x00012345')
        self.assertEqual(value['effects'][0]['magnitude'], 17.5)
        self.assertEqual(value['effects'][0]['durationSeconds'], 3)

    def test_alchemy_missing_or_unbounded_values_fail_closed(self):
        for override in ({'IsPoison': None}, {'GetNumEffects': True}, {'GetNumEffects': 33},
                         {'GetNthEffectMagicEffect': None}, {'GetNthEffectMagnitude': float('nan')},
                         {'GetNthEffectArea': True}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.alchemy_backend(override).alchemy({})

    def test_alchemy_request_is_validated_and_mapping_exposes_observed_fields(self):
        platform.validate({'operation': 'world.read', 'request': {'observation': 'form.alchemy',
                          'form': {'plugin': 'Skyrim.esm', 'localId': '03EADD'}}})
        self.assertIn('alchemy.effects', operations()['world.read']['fields'])


class NativeStackTests(unittest.TestCase):
    backend = MultiTagAlchemyTests.backend
    request = MultiTagAlchemyTests.request
    def stack(self, native_count=5, inventory=(7,12,7)):
        session = Session();session.save = lambda: None
        backend = self.backend(session);calls=[];counts=iter(inventory)
        def pap(script,function,values=None,target=None):
            calls.append((function,values))
            if function == 'GetItemCount': return next(counts)
            return {'DropObject':{'formId':'0xFF005678'},'GetAngleZ':0,
                    'Is3DLoaded':True,'GetMass':1}.get(function)
        backend.pap=pap;backend.resolve=lambda spec:'0x0003EADD'
        backend.call=lambda *args:{'refs':[{'formId':'0xFF005678','quantityItems':native_count}]}
        backend.xyz=lambda ref:[1,2,3];backend.pause=lambda seconds:None;backend.remaining=lambda:30
        return session,backend,calls

    def test_stack5_uses_single_native_drop_and_measures_actual_count(self):
        session,backend,calls=self.stack();req=self.request();req['quantityItems']=5
        with patch.object(platform.time,'monotonic',side_effect=range(100)):
            backend.mutate(req)
        names=[c[0] for c in calls]
        self.assertEqual(names.count('DropObject'),1)
        self.assertEqual(names.count('AddItem'),1)
        self.assertNotIn('PlaceAtMe',names)
        self.assertEqual(session.state['platformReferences']['poison']['id'],'0xFF005678')

    def test_requested5_cannot_substitute_for_native_count1(self):
        session,backend,calls=self.stack(native_count=1);req=self.request();req['quantityItems']=5
        with self.assertRaisesRegex(ValueError,'quantity is not5'):backend.mutate(req)
        self.assertEqual(sum(c[0]=='DropObject' for c in calls),1)
        self.assertFalse(any(c[0]=='MoveTo' for c in calls))

    def test_stack_staging_delta_failure_never_repeats_or_drops(self):
        session,backend,calls=self.stack(inventory=(7,11));req=self.request();req['quantityItems']=5
        with self.assertRaisesRegex(ValueError,'delta5'):backend.mutate(req)
        self.assertEqual(sum(c[0]=='AddItem' for c in calls),1)
        self.assertFalse(any(c[0]=='DropObject' for c in calls))

    def test_held_quantity_is_native_exact_reference_not_requested_count(self):
        backend=self.backend();backend.pap=lambda *a,**k:{'formId':'0xFF001234'}
        backend.item=lambda ref:{'plugin':'Skyrim.esm','localId':'03EADD'}
        backend.call=lambda *a:{'refs':[{'formId':'0xFF001234','quantityItems':5}]}
        self.assertEqual(backend.held({'hand':'right'})['hand']['quantity']['items'],5)
        backend.call=lambda *a:{'refs':[{'formId':'0xFF009999','quantityItems':5}]}
        with self.assertRaisesRegex(ValueError,'quantity unavailable'):backend.held({'hand':'right'})
