import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from skyrim_autotest.interactive_artifacts import collect


class InteractiveArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.file = self.root / 'interactive-results' / ('a' * 32 + '.json')
        self.file.parent.mkdir()
        self.file.write_bytes(b'{"actual":"complete result"}')
        self.row = {'commandId':'a' * 32,'path':str(self.file),
                    'sha256':hashlib.sha256(self.file.read_bytes()).hexdigest(),
                    'bytes':self.file.stat().st_size,'format':'json'}
        self.session = SimpleNamespace(dir=self.root,state={'interactiveArtifacts':[self.row]})

    def test_complete_result_copied_with_original_receipt(self):
        calls = []
        def copied(path, name, kind, required):
            calls.append((path,name,kind,required))
            return {'sha256':self.row['sha256'],'bytes':self.row['bytes']}
        collect(self.session,copied)
        self.assertEqual(calls,[(self.file,'interactive-'+'a'*32+'.json','interactive-result',True)])

    def test_changed_missing_and_foreign_results_are_refused_before_copy(self):
        original = dict(self.row)
        for edit in [{'path':str(self.root/'foreign.json')},{'sha256':'0'*64},{'bytes':1},{'commandId':'../escape'}]:
            self.session.state['interactiveArtifacts'] = [dict(original,**edit)]
            with self.subTest(edit=edit), self.assertRaises((ValueError,OSError)):
                collect(self.session,lambda *args:self.fail('Unverified result was copied'))

    def test_duplicate_identity_and_changed_collected_copy_are_refused(self):
        self.session.state['interactiveArtifacts'] = [self.row,dict(self.row)]
        with self.assertRaises(ValueError):
            collect(self.session,lambda *args:None)
        self.session.state['interactiveArtifacts'] = [self.row]
        with self.assertRaises(ValueError):
            collect(self.session,lambda *args:{'sha256':'0'*64,'bytes':self.row['bytes']})


if __name__ == '__main__':
    unittest.main()
