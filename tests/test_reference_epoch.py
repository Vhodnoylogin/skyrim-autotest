"""Dynamic FormIDs must not survive world transitions or unobserved event gaps."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import runner

class ReferenceEpochTests(unittest.TestCase):
    def session(self,directory):
        return runner.Session(directory,{'port':1,'probeObject':'0xFF001234','probeObjectLive':True,'probeEventCursor':10})
    def test_load_between_creation_and_binding_is_not_adopted_as_new_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.session(directory)
            responses=[{'headSeq':10,'events':[{'seq':10,'topic':'menu','data':{}}]},
                       {'headSeq':11,'events':[{'seq':11,'topic':'lifecycle','data':{'event':'newGame'}}]}]
            with patch.object(runner,'request',side_effect=responses):
                cursor=session.capture_probe_cursor()
                with self.assertRaisesRegex(runner.Blocked,'world lifecycle'):
                    session.bind_probe_reference('0xFF001234',cursor)
            self.assertFalse(session.state['probeObjectLive'])
            self.assertEqual(session.state['probeEventCursor'],10)
    def test_world_transition_invalidates_before_reference_can_be_reused(self):
        for field in ('event','type'):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as directory:
                session=self.session(directory)
                response={'headSeq':11,'events':[{'seq':11,'topic':'lifecycle','data':{field:'preLoadGame'}}]}
                with patch.object(runner,'request',return_value=response):
                    with self.assertRaisesRegex(runner.Blocked,'world lifecycle'):
                        session.validate_probe_reference()
                self.assertFalse(session.state['probeObjectLive'])
    def test_ring_gap_fails_closed_even_if_retained_events_show_no_load(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.session(directory)
            response={'headSeq':13,'events':[{'seq':13,'topic':'menu','data':{}}]}
            with patch.object(runner,'request',return_value=response):
                with self.assertRaisesRegex(runner.Blocked,'event gap'):
                    session.validate_probe_reference()
            self.assertFalse(session.state['probeObjectLive'])
    def test_head_leading_batch_is_reconciled_without_skipping_unseen_load(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.session(directory)
            responses=[{'headSeq':11,'events':[]},{'headSeq':11,'events':[{'seq':11,'topic':'lifecycle','data':{'event':'postLoadGame'}}]}]
            with patch.object(runner,'request',side_effect=responses) as request:
                with self.assertRaisesRegex(runner.Blocked,'world lifecycle'):
                    session.validate_probe_reference()
            self.assertEqual(request.call_count,2)
            self.assertTrue(all(call.args[1].endswith('since=10') for call in request.call_args_list))
            self.assertFalse(session.state['probeObjectLive'])
    def test_contiguous_events_and_racing_head_can_be_reconciled(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.session(directory)
            responses=[{'headSeq':12,'events':[{'seq':11,'topic':'menu','data':{}}]},{'headSeq':12,'events':[{'seq':12,'topic':'menu','data':{}}]}]
            with patch.object(runner,'request',side_effect=responses) as request:
                session.validate_probe_reference()
            self.assertEqual(session.state['probeEventCursor'],12)
            self.assertTrue(session.state['probeObjectLive'])
            self.assertTrue(request.call_args_list[-1].args[1].endswith('since=11'))
    def test_unseen_head_is_bounded_and_never_accepted_as_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            session=self.session(directory)
            with patch.object(runner,'request',return_value={'headSeq':12,'events':[]}) as request:
                with self.assertRaisesRegex(runner.Blocked,'Unseen lifecycle head'):
                    session.validate_probe_reference()
            self.assertEqual(request.call_count,3)
            self.assertEqual(session.state['probeEventCursor'],10)
            self.assertFalse(session.state['probeObjectLive'])

if __name__=='__main__':unittest.main()
