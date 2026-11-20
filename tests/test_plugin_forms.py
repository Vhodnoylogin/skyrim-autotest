import unittest
from unittest.mock import Mock

from skyrim_autotest import platform
from skyrim_autotest.plugin_forms import resolve_full_plugin_form


FIXTURE = 'test_CLAW - VR CBPC Contact Fixture.esp'
# The two raw Papyrus values from SE run 20261120-174916-4d32b7. That run
# stopped at the case-sensitive comparison, before the third Game lookup.
SE_INDEX_REPLY = {'called': True, 'returned': 12, 'returnedType': 'int'}
SE_NAME_REPLY = {'called': True, 'returned': 'test_claw - vr cbpc contact fixture.esp', 'returnedType': 'string'}


def form_reply(form_id):
    return {'called': True, 'returned': {'formId': form_id, 'scriptType': 'Form'}, 'returnedType': 'Form'}


def request(form=None, strict=True):
    return {'operation': 'world.read', 'request': {'observation': 'form.identity',
            'form': form if form is not None else {'plugin': FIXTURE, 'localId': '800'},
            'requireFullPluginIdentity': strict}}


class Session:
    state = {'gameplayBootstrap': {'completed': True}}

    def __init__(self, replies):
        self.tool = Mock(side_effect=replies)


class PluginFormTests(unittest.TestCase):
    def test_platform_replays_actual_case_difference_then_matches_indexed_record(self):
        session = Session([SE_INDEX_REPLY, SE_NAME_REPLY, form_reply('0x0C000800')])
        deadline = platform.time.monotonic() + 10
        result = platform.execute(session, request(), deadline)
        self.assertEqual(result, {'form': {'plugin': SE_NAME_REPLY['returned'], 'loadIndex': 12,
                                          'localId': '000800', 'runtimeId': '0x0C000800'}})
        self.assertEqual([(c.args[0], c.args[1]['script'], c.args[1]['function'], c.args[1]['args'])
                          for c in session.tool.call_args_list],
                         [('papyrus', 'Game', 'GetModByName', [FIXTURE]),
                          ('papyrus', 'Game', 'GetModName', [12]),
                          ('papyrus', 'Game', 'GetFormFromFile', [0x800, FIXTURE])])
        self.assertTrue(all(c.kwargs['deadline'] == deadline for c in session.tool.call_args_list))

    def test_zero_load_index_and_top_full_index_are_valid_with_real_record_ids(self):
        for index, plugin, local, runtime in ((0, 'Skyrim.esm', '07', '0x00000007'),
                                              (0xFD, "Author's [Variant] (SE).ESP", 'ffffff', '0xFDFFFFFF')):
            with self.subTest(index=index):
                call = Mock(side_effect=[dict(SE_INDEX_REPLY, returned=index),
                                         dict(SE_NAME_REPLY, returned=plugin.lower()), form_reply(runtime)])
                identity = resolve_full_plugin_form(call, plugin, local)
                self.assertEqual(identity['loadIndex'], index)
                self.assertEqual(identity['runtimeId'], runtime)

    def test_light_and_dynamic_indices_and_invalid_int_values_stop_before_name_lookup(self):
        for index in (0xFE, 0xFF, 0x100, -1, True, 12.0, '12'):
            with self.subTest(index=index):
                call = Mock(return_value=dict(SE_INDEX_REPLY, returned=index))
                with self.assertRaisesRegex(ValueError, 'load index'):
                    resolve_full_plugin_form(call, FIXTURE, '800')
                call.assert_called_once_with('GetModByName', [FIXTURE])

    def test_wrong_whole_plugin_name_stops_before_record_lookup(self):
        for name in (FIXTURE + '.esp', FIXTURE + ' ', 'Data/' + FIXTURE, FIXTURE.replace('CLAW', 'CLAW2'), '', 12):
            with self.subTest(name=name):
                call = Mock(side_effect=[SE_INDEX_REPLY, dict(SE_NAME_REPLY, returned=name)])
                with self.assertRaisesRegex(ValueError, 'filename differs'):
                    resolve_full_plugin_form(call, FIXTURE, '800')
                self.assertEqual(call.call_count, 2)

    def test_wrong_or_malformed_native_id_and_failures_are_unavailable(self):
        for runtime in ('0x0D000800', '0x0C000801', '0xFE000800', '0xFF000800', '0xC000800',
                        '0x0C0000800', '0x0C00080G', ' 0x0C000800', 0x0C000800, None):
            with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, 'FormID'):
                resolve_full_plugin_form(Mock(side_effect=[SE_INDEX_REPLY, SE_NAME_REPLY, form_reply(runtime)]), FIXTURE, '800')
        zero = Mock(side_effect=[dict(SE_INDEX_REPLY, returned=0), dict(SE_NAME_REPLY, returned='skyrim.esm'),
                                 form_reply('0x00000000')])
        with self.assertRaisesRegex(ValueError, 'FormID'):
            resolve_full_plugin_form(zero, 'Skyrim.esm', '0')
        expected_replies = [SE_INDEX_REPLY, SE_NAME_REPLY, form_reply('0x0C000800')]
        for offset, expected in enumerate(expected_replies):
            for bad in (None, {'returned': expected['returned']}, dict(expected, called=1),
                        dict(expected, returnedType='untyped'), dict(expected, error='failed'), dict(expected, isError=True)):
                with self.subTest(offset=offset, bad=bad):
                    call = Mock(side_effect=expected_replies[:offset] + [bad])
                    with self.assertRaisesRegex(ValueError, 'Typed Game'):
                        resolve_full_plugin_form(call, FIXTURE, '800')
                    self.assertEqual(call.call_count, offset + 1)

    def test_invalid_selectors_are_refused_before_game_reads(self):
        for plugin, local in (('Data/' + FIXTURE, '800'), ('invalid:.esp', '800'), ('Unicode K.esp', '800'),
                              ('plug.esl', '800'), (FIXTURE, '1000000'), (FIXTURE, '0x800'),
                              (FIXTURE, ''), (FIXTURE, 0x800)):
            with self.subTest(plugin=plugin, local=local):
                call = Mock()
                with self.assertRaises(ValueError):
                    resolve_full_plugin_form(call, plugin, local)
                call.assert_not_called()
                with self.assertRaises(ValueError):
                    platform.validate(request({'plugin': plugin, 'localId': local}))
        with self.assertRaises(ValueError):
            platform.validate(request({'runtimeItemTag': 'crafted', 'type': 'ALCH'}))
        with self.assertRaises(ValueError):
            platform.validate(request(strict=1))

    def test_requested_form_type_is_verified_for_that_exact_runtime_id(self):
        form = {'plugin': FIXTURE, 'localId': '800', 'type': 'NPC_'}
        for observed, succeeds in (({'formId': '0x0C000800', 'formType': 'NPC_'}, True),
                                   ({'formId': '0x0C000801', 'formType': 'NPC_'}, False),
                                   ({'formId': '0x0C000800', 'formType': 'RACE'}, False)):
            with self.subTest(observed=observed):
                session = Session([SE_INDEX_REPLY, SE_NAME_REPLY, form_reply('0x0C000800'), {'refs': [observed]}])
                deadline = platform.time.monotonic() + 10
                if succeeds:
                    self.assertEqual(platform.execute(session, request(form), deadline)['form']['runtimeId'], '0x0C000800')
                else:
                    with self.assertRaisesRegex(ValueError, 'identity or type'):
                        platform.execute(session, request(form), deadline)
                self.assertEqual(session.tool.call_args.args, ('inspect', {'kind': 'refs', 'formId': '0x0C000800'}))

    def test_legacy_form_identity_preserves_single_call_and_compact_id(self):
        for supplied_flag in (False, None):
            with self.subTest(supplied_flag=supplied_flag):
                args = request({'plugin': 'Light.esp', 'localId': '800'}, strict=False)
                if supplied_flag is None:
                    del args['request']['requireFullPluginIdentity']
                session = Session([{'returned': {'formId': '0xFE003800'}}])
                result = platform.execute(session, args, platform.time.monotonic() + 10)
                self.assertEqual(result, {'form': {'runtimeId': '0xFE003800'}})
                self.assertEqual(session.tool.call_count, 1)
                self.assertEqual(session.tool.call_args.args[1]['function'], 'GetFormFromFile')
