"""Owned recorder evidence cannot delete another session's files."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from skyrim_autotest import input_activity

class Session:
    state={'id':'owned', 'preflight':{'dlls':{'RenamedProvider/SKSE/Plugins/devbench.dll':'pin'}}}
    def log(self,*args,**kwargs): pass

class InputActivityTests(unittest.TestCase):
    def test_copy_before_removing_one_owned_file_and_preserve_foreign_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); session=Session();session.dir=root/'run';session.dir.mkdir()
            config=SimpleNamespace(game=root/'game',overwrite=root/'overwrite',mods=root/'mods')
            path=config.overwrite/'SKSE/Plugins/devbench/recordings/recording_123.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'meta':{'correlationId':'owned','format':'devbench-recording-3'},
                                        'activityEvents':[{'kind':'input','userEvent':'Activate'}]}))
            other=path.with_name('recording_124.json');other.write_text('foreign')
            result={'path':'Data/SKSE/Plugins/devbench/recordings/recording_123.json',
                    'meta':{'correlationId':'owned'}}
            with patch.object(input_activity.runner,'P',config):value=input_activity.collect(session,result)
            self.assertFalse(path.exists());self.assertEqual(other.read_text(),'foreign')
            self.assertEqual(json.loads((session.dir/'evidence/pickup-input-recording.json').read_bytes()),value)
    def test_foreign_correlation_never_removes_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); session=Session();session.dir=root/'run'
            config=SimpleNamespace(game=root/'game',overwrite=root/'overwrite',mods=root/'mods')
            path=config.overwrite/'SKSE/Plugins/devbench/recordings/recording_123.json'
            path.parent.mkdir(parents=True);path.write_text(json.dumps({'meta':{'correlationId':'foreign'}}))
            result={'path':'Data/SKSE/Plugins/devbench/recordings/recording_123.json',
                    'meta':{'correlationId':'owned'}}
            with patch.object(input_activity.runner,'P',config), self.assertRaisesRegex(AssertionError,'Unique owned'):
                input_activity.collect(session,result)
            self.assertTrue(path.exists())
    def test_foreign_active_recording_is_never_stopped_or_replaced(self):
        session=Session();calls=[]
        def tool(name,args):calls.append(args);return {'recording':True,'state':'running'}
        session.tool=tool
        with self.assertRaisesRegex(AssertionError,'not idle'):input_activity.start(session)
        self.assertEqual(calls,[{'action':'status'}])

if __name__=='__main__':unittest.main()
