import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import owned_saves, native, runner
import test_owned_saves as fixture


class LoadHistoryTests(unittest.TestCase):
    def test_two_loads_keep_both_native_pairs_and_raw_envelopes(self):
        f=fixture.OwnedSaveTests();f.setUp();self.addCleanup(f.doCleanups);f.complete()
        records=[];f.b.s.log=lambda kind,**data:records.append((kind,copy.deepcopy(data)))
        scene={'playerLoaded':True,'cell':{'editorId':'QASmoke'}}
        for cursor in (0,2):
            f.b.s.capture_probe_cursor=lambda:cursor
            events=[fixture.event(cursor+1,'preLoadGame'),fixture.event(cursor+2,'postLoadGame')]
            responses=[{'headSeq':cursor+2,'events':events},{'headSeq':cursor+2,'events':[]}]
            with patch('skyrim_autotest.runner.request',side_effect=responses), \
                 patch('skyrim_autotest.bootstrap.wait_gameplay_ready',return_value=(scene,{})), \
                 patch('skyrim_autotest.platform.initialize_controllers'):
                owned_saves.perform(f.b,f.request('load_game'))
        history=f.b.s.state['ownedLoadHistory']
        self.assertEqual([v['ordinal'] for v in history],[1,2])
        self.assertEqual([[e['seq'] for e in v['events']] for v in history],[[1,2],[3,4]])
        self.assertEqual([v['worldGeneration'] for v in history],[1,2])
        self.assertTrue(all(v['completed'] for v in history))
        envelopes=[v for kind,v in records if kind=='owned-save-lifecycle-envelope']
        self.assertEqual([v['cursorRequested'] for v in envelopes],[0,2,2,4])
        self.assertEqual(envelopes[0]['envelope']['events'],history[0]['events'])
        self.assertEqual(envelopes[2]['envelope']['events'],history[1]['events'])
        self.assertEqual(len([v for kind,v in records if kind=='owned-load-completed']),2)

    def test_malformed_raw_envelope_is_retained_before_rejection(self):
        f=fixture.OwnedSaveTests();f.setUp();self.addCleanup(f.doCleanups)
        records=[];f.b.s.log=lambda kind,**data:records.append(data)
        malformed={'headSeq':2,'events':[fixture.event(2,'postLoadGame')]}
        with patch('skyrim_autotest.runner.request',return_value=malformed),self.assertRaisesRegex(ValueError,'gap'):
            owned_saves.Events(f.b,0).read()
        self.assertEqual(records[0]['envelope'],malformed)

    def test_incomplete_load_is_not_replayed(self):
        f=fixture.OwnedSaveTests();f.setUp();self.addCleanup(f.doCleanups);f.complete()
        f.b.s.state['ownedLoadTransition']={'completed':False};before=len(f.b.calls)
        with self.assertRaisesRegex(ValueError,'incomplete'):owned_saves.perform(f.b,f.request('load_game'))
        self.assertEqual(len(f.b.calls),before)

    def test_discovered_owned_loader_never_becomes_game_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);ident={'pid':18,'birth':134000000000000000,'path':str(path/'sksevr_loader.exe')}
            parent={'pid':17,'birth':ident['birth']-1,'path':str(path/'ModOrganizer.exe')}
            s=runner.Session(path,{'owned':[{'role':'mo2','identity':parent}],
                'launchIntents':{'game':{'at':0,'directory':str(path)}}})
            with patch.object(native,'processes',return_value=[{'pid':18,'parent':17,'name':'sksevr_loader.exe'}]), \
                 patch.object(native,'identity',side_effect=lambda pid:ident if pid==18 else parent):
                s.discover()
            self.assertEqual(next(v['role'] for v in s.state['owned'] if v['identity']==ident),'loader')
