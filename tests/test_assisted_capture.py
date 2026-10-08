import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from skyrim_autotest.assisted_capture import capture, image_info


def bmp():
    return (b'BM' + struct.pack('<IHHI', 58, 0, 0, 54)
            + struct.pack('<IiiHHIIiiII', 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0)
            + b'\x12\x34\x56\x00')


def png():
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\x12\x34\x56')) + chunk(b'IEND', b''))


class AssistedCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = []

    def guard(self):
        self.events.append('guard')

    def say(self, text):
        self.events.append(('countdown', text))

    def provider(self, body):
        self.events.append(('capture', body))
        folder = Path(body['outDir']) / body['recording'] / body['variant']
        folder.mkdir(parents=True)
        file = folder / (body['checkpointId'] + '.bmp')
        file.write_bytes(bmp())
        return dict(ok=True, file=file.name, provider='native', degraded=['nativeFallback'])

    def test_countdown_before_single_capture_and_actual_file_verified(self):
        result = capture(self.root, 'voice-1', self.guard, self.provider, self.say)
        self.assertEqual([e[0] if isinstance(e, tuple) else e for e in self.events],
                         ['guard', 'countdown', 'guard', 'capture', 'guard'])
        self.assertTrue(result['captureFileVerified'])
        self.assertFalse(result['visualContentVerified'])
        self.assertEqual(result['providerReceipt']['degraded'], ['nativeFallback'])
        self.assertTrue(Path(result['image']).is_file())

    def test_ok_receipt_missing_file_is_failure_not_virtual_path_fallback(self):
        with self.assertRaises(ValueError):
            capture(self.root, 'voice-1', self.guard,
                    lambda body: dict(ok=True, file='fake.png', path='C:/virtual/fake.png'), self.say)
        result = json.loads((self.root / 'voice-1/capture-receipt.json').read_text())
        self.assertFalse(result['captureFileVerified'])

    def test_duplicate_uncertain_request_does_not_retry(self):
        def failed(body):
            self.events.append('capture-failed')
            raise TimeoutError('unknown capture outcome')
        with self.assertRaises(TimeoutError):
            capture(self.root, 'voice-1', self.guard, failed, self.say)
        with self.assertRaises(FileExistsError):
            capture(self.root, 'voice-1', self.guard, self.provider, self.say)
        self.assertEqual(self.events.count('capture-failed'), 1)

    def test_voice_or_identity_failure_never_captures(self):
        def failed(*args):
            raise RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            capture(self.root, 'voice-1', self.guard, self.provider, failed)
        with self.assertRaises(RuntimeError):
            capture(self.root, 'voice-2', failed, self.provider, self.say)
        self.assertFalse(any(isinstance(e, tuple) and e[0] == 'capture' for e in self.events))

    def test_corrupt_and_truncated_images_rejected(self):
        for data in (b'', bmp()[:-1], png()[:-1], png()[:-5] + b'xxxxx'):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                image_info(data)
        self.assertEqual(image_info(png())['format'], 'png')
        self.assertEqual(image_info(bmp())['height'], 1)

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            capture(self.root, 'voice-1', self.guard,
                    lambda body: dict(ok=True, file='../fake.png'), self.say)


if __name__ == '__main__':
    unittest.main()
