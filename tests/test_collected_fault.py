from datetime import datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from skyrim_autotest.collected_fault import collected_game_faults


LOG = b'''CRASH TIME: 2026-11-20 19:12:12\r
Skyrim VR v1.4.15\r
CrashLoggerSSE v1-25-0-0\r
\r
Unhandled exception "EXCEPTION_ACCESS_VIOLATION" at 0x7ff ucrtbase.dll+00ED921\r
PROCESS INFO:\r
\tProcess ID: 48048\r
CALL STACK ([P]robable / [S]tack scan):\r
\t[ 0][P] 0x7ff ucrtbase.dll+00ED921\r
\t[ 1][P] 0x7fa ExampleFixture.dll+0010391\r
\t[ 2][S] 0x7fb OtherModule.dll+0022222\r
'''
GAME = {'pid': 48048, 'birth': 134396646762928512, 'path': r'D:\Mock\SkyrimVR.exe'}
TERMINATION = {'identity': GAME, 'exitCode': 1, 'firstExitObservedAtUtc': '2026-11-20T16:12:19.502Z'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class CollectedFaultTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        evidence = self.root / 'evidence'
        evidence.mkdir()
        self.log = evidence / 'crash-2026-11-20-19-12-12.log'
        self.manifest = evidence / 'manifest.json'
        self.state = {'collectionComplete': True, 'finalCollectionCheckpoint': {}}

    def prepare(self, log=LOG, **fields):
        self.log.write_bytes(log)
        entry = {'name': self.log.name, 'bytes': len(log), 'sha256': digest(log),
                 'kind': 'skse-log', 'fresh': True, 'mtime': 1795191133.0321438, **fields}
        raw = json.dumps([entry]).encode()
        self.manifest.write_bytes(raw)
        self.state['finalCollectionCheckpoint']['manifestSha256'] = digest(raw)

    def test_copied_actual_header_shape_is_independent_of_event_log_correlation(self):
        self.prepare()
        self.assertEqual(collected_game_faults(self.state, self.root, TERMINATION), [{
            'artifact': self.log.name, 'exception': 'EXCEPTION_ACCESS_VIOLATION',
            'module': 'ucrtbase.dll', 'offsetHex': '0xED921', 'probableFrames': [
                {'module': 'ucrtbase.dll', 'offsetHex': '0xED921'},
                {'module': 'ExampleFixture.dll', 'offsetHex': '0x10391'},
            ],
        }])

    def test_foreign_pid_stale_artifact_or_incomplete_collection_are_not_credited(self):
        self.prepare()
        for term in (dict(TERMINATION, identity=dict(GAME, pid=49123)), dict(TERMINATION, exitCode=0), None):
            with self.subTest(term=term):
                self.assertEqual(collected_game_faults(self.state, self.root, term), [])
        self.assertEqual(collected_game_faults(dict(self.state, collectionComplete=False), self.root, TERMINATION), [])
        self.prepare(mtime=datetime.fromisoformat('2026-11-20T16:07:00+00:00').timestamp())
        self.assertEqual(collected_game_faults(self.state, self.root, TERMINATION), [])
        self.prepare(fresh=False)
        self.assertEqual(collected_game_faults(self.state, self.root, TERMINATION), [])

    def test_changed_log_and_manifest_refuse(self):
        self.prepare()
        self.log.write_bytes(LOG.replace(b'ExampleFixture', b'OtherExampleXX'))
        self.assertEqual(collected_game_faults(self.state, self.root, TERMINATION), [])
        self.prepare()
        self.manifest.write_bytes(self.manifest.read_bytes() + b'\n')
        self.assertEqual(collected_game_faults(self.state, self.root, TERMINATION), [])
