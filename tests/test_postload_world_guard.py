from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock,patch
from skyrim_autotest import platform,runner


class PostloadTests(unittest.TestCase):
    def backend(self):
        game=dict(pid=17,birth=3,path='SkyrimVR.exe')
        state=dict(game=game,port=1,gameplayBootstrap=dict(completed=True),
                   probeObject='0xFF001234',probeObjectLive=False,probeEventCursor=10,
                   ownedWorldGeneration=2,platformReferences={},invalidatedReferenceTags=['old'],
                   ownedLoadTransition=dict(completed=True,afterGame=game,worldGeneration=2,cursor=20))
        session=SimpleNamespace(state=state,save=Mock(),log=Mock(),
                                validate_probe_reference=Mock(side_effect=AssertionError('Old probe must remain invalid')))
        return platform.Backend(session,time.monotonic()+20)

    def test_actual_empty_hand_after_known_load_does_not_resurrect_old_probe(self):
        b=self.backend(); b.pap=Mock(return_value=None)
        with patch.object(runner,'request',return_value=dict(headSeq=20,events=[])):
            result=b.held(dict(hand='left',continuityWindowSeconds=0))
        self.assertFalse(result['hand']['occupied'])
        self.assertFalse(b.s.state['probeObjectLive'])
        self.assertEqual(b.s.state['probeEventCursor'],10)
        self.assertEqual(b.s.state['platformReferences'],{})
        b.s.validate_probe_reference.assert_not_called()

    def test_old_tag_not_restored_even_when_current_world_is_valid(self):
        b=self.backend()
        with patch.object(runner,'request',return_value=dict(headSeq=20,events=[])), \
             self.assertRaisesRegex(ValueError,'Reference tag is unavailable'):
            b.tagged(dict(referenceTag='old'))
        self.assertEqual(b.s.state['invalidatedReferenceTags'],['old'])

    def test_new_actual_held_incarnation_can_be_tagged_without_reviving_probe(self):
        b=self.backend();b.pap=Mock(return_value={'formId':'0xFF009999'})
        b.reference_incarnation=Mock(return_value=dict(sessionId='new',loadGeneration=2,runtimeHandle=91))
        with patch.object(runner,'request',return_value=dict(headSeq=20,events=[])):
            result=b.mutate(dict(action='tag_held_reference',hand='left',referenceTag='new-held'))
        self.assertEqual(result['reference']['id'],'0xFF009999')
        self.assertEqual(b.s.state['platformReferences']['new-held']['incarnation']['runtimeHandle'],91)
        self.assertFalse(b.s.state['probeObjectLive'])
        self.assertNotIn('old',b.s.state['platformReferences'])

    def test_later_world_transition_or_event_gap_invalidates_new_world_guard(self):
        for reply in (dict(headSeq=21,events=[dict(seq=21,topic='lifecycle',data=dict(event='postLoadGame'))]),
                      dict(headSeq=23,events=[dict(seq=23,topic='menu',data={})])):
            b=self.backend()
            with self.subTest(reply=reply),patch.object(runner,'request',return_value=reply),self.assertRaises(ValueError):
                b.guard_world()
            self.assertTrue(b.s.state['ownedLoadTransition']['worldInvalidated'])
            with patch.object(runner,'request') as request,self.assertRaisesRegex(ValueError,'unavailable or invalidated'):
                b.guard_world()
            request.assert_not_called()

    def test_incomplete_or_wrong_process_or_epoch_load_never_becomes_world_guard(self):
        for change in (lambda s:s['ownedLoadTransition'].update(completed=False),
                       lambda s:s['game'].update(birth=9),
                       lambda s:s.update(ownedWorldGeneration=3)):
            b=self.backend()
            # Preserve distinct before/after dictionaries for process-reuse case.
            b.s.state['ownedLoadTransition']['afterGame']=dict(b.s.state['game'])
            change(b.s.state)
            with self.subTest(change=change),patch.object(runner,'request') as request, \
                 self.assertRaisesRegex(ValueError,'unavailable or invalidated'):
                b.guard_world()
            request.assert_not_called()
