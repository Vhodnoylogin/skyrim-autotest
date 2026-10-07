import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from skyrim_autotest.collection import snapshot_log


class LiveLogSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/'source.log';self.target=Path(self.temp.name)/'snapshot.log'
        self.source.write_bytes(b'first complete record\n')

    def snapshot_with_write(self, mutation):
        original=Path.open;source_path=self.source;triggered=False
        class Reader:
            def __init__(self,raw):self.raw=raw
            def __enter__(self):return self
            def __exit__(self,*args):return self.raw.__exit__(*args)
            def __getattr__(self,name):return getattr(self.raw,name)
            def read(self,*args):
                nonlocal triggered
                data=self.raw.read(*args)
                if not triggered:
                    triggered=True;mutation(original)
                return data
        def open_file(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            return Reader(stream) if path==source_path and args and args[0]=='rb' else stream
        with patch.object(Path,'open',open_file):return snapshot_log(self.source,self.target)

    def test_append_during_copy_pins_initial_prefix_and_marks_unobserved_tail(self):
        initial=self.source.read_bytes()
        def append(open_file):
            with open_file(self.source,'ab') as out:out.write(b'next record\n')
        value=self.snapshot_with_write(append)
        self.assertEqual(self.target.read_bytes(),initial)
        self.assertEqual(value['byteEndExclusive'],len(initial))
        self.assertTrue(value['tailOutsideSnapshot']);self.assertFalse(value['atomicSnapshot'])

    def test_rewrite_of_copied_prefix_fails_even_with_same_size(self):
        def rewrite(open_file):
            with open_file(self.source,'r+b') as out:out.write(b'OTHER')
        with self.assertRaisesRegex(ValueError,'prefix changed'):self.snapshot_with_write(rewrite)

    def test_truncation_during_copy_cannot_be_claimed_collected(self):
        def truncate(open_file):
            with open_file(self.source,'wb') as out:out.write(b'x')
        with self.assertRaisesRegex(ValueError,'truncated|prefix changed'):self.snapshot_with_write(truncate)

    def test_log_bound_applies_before_copy(self):
        with self.source.open('r+b') as out:out.truncate(64*1024*1024+1)
        with self.assertRaisesRegex(ValueError,'64MiB'):snapshot_log(self.source,self.target)
        self.assertFalse(self.target.exists())
