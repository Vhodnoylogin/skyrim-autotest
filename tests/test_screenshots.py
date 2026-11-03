"""Real loopback DevBench capture transport with synthetic image files; no game."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zlib

from skyrim_autotest import screenshots


def png():
    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'\x00\x12\x34\x56'))
            + chunk(b'IEND', b''))


def bmp():
    return (b'BM' + struct.pack('<IHHI', 58, 0, 0, 54)
            + struct.pack('<IiiHHIIiiII', 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0)
            + b'\x12\x34\x56\x00')


class ScreenshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'shots'
        self.outside = self.base / 'outside'
        self.outside.mkdir()
        self.sentinel = self.outside / 'owner.bin'
        self.sentinel.write_bytes(b'owner-original')
        self.events = []
        self.posts = []
        self.mode = 'png'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self, value, status=200):
                data = json.dumps(value).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                owner.events.append(('get', self.path))
                if self.path != '/api/health':
                    return self.answer({'error': 'unexpected endpoint'}, 404)
                self.answer({'pid': 12345})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.events.append(('post', self.path))
                owner.posts.append((self.path, body))
                if self.path != '/api/tool/capture':
                    return self.answer({'error': 'unexpected endpoint'}, 404)
                mode = owner.mode
                suffix = '.bmp' if mode == 'bmp' else '.png'
                name = body['checkpointId'] + suffix
                directory = Path(body['outDir']) / body['recording'] / body['variant']
                image = directory / name
                receipt = {'ok': True, 'file': name, 'path': str(image),
                           'provider': 'native' if mode == 'bmp' else 'loopback-fixture',
                           'degraded': ['nativeFallback'] if mode == 'bmp' else []}
                if mode in ('traversal', 'absolute', 'wrong-stem'):
                    receipt['file'] = {'traversal': '../escape.png',
                                       'absolute': str(owner.outside / 'escape.png'),
                                       'wrong-stem': 'different-request.png'}[mode]
                elif mode != 'missing':
                    directory.mkdir(parents=True, exist_ok=True)
                    if mode == 'symlink':
                        image.symlink_to(owner.sentinel)
                    elif mode == 'directory-symlink':
                        # Replace the requested variant directory with an outside alias.
                        directory.rmdir()
                        directory.symlink_to(owner.outside, target_is_directory=True)
                        (owner.outside / name).write_bytes(png())
                    else:
                        image.write_bytes({'empty': b'', 'corrupt': b'not an image',
                                           'truncated': png()[:-1]}.get(
                                               mode, bmp() if mode == 'bmp' else png()))
                if mode == 'false':
                    receipt['ok'] = False
                elif mode == 'string-ok':
                    receipt['ok'] = 'true'
                elif mode == 'missing-ok':
                    del receipt['ok']
                elif mode == 'different-path':
                    receipt['path'] = str(owner.outside / name)
                elif mode == 'wrong-bytes':
                    receipt['bytes'] = 1
                elif mode == 'boolean-bytes':
                    receipt['bytes'] = True
                elif mode == 'disguised-format':
                    image.write_bytes(bmp())
                self.answer(receipt)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def guard(self):
        self.events.append(('guard', None))
        self.assertEqual(screenshots.request(self.port, 'health')['pid'], 12345)

    def call(self, body):
        return screenshots.request(self.port, 'tool/capture', body)

    def report(self, identifier):
        return json.loads((self.root / identifier / 'screenshot-receipt.json').read_text(encoding='utf-8'))

    def test_http_png_creates_and_hashes_actual_image_without_other_file_changes(self):
        before_cwd = Path.cwd()
        before_outside = {p.name: p.read_bytes() for p in self.outside.iterdir()}
        result = screenshots.capture(self.root, 'request-1', self.guard, self.call)
        self.assertTrue(result['captureFileVerified'])
        image = Path(result['image'])
        self.assertTrue(image.is_relative_to(self.root.resolve()))
        self.assertEqual(image.read_bytes(), png())
        self.assertEqual(result['sha256'], hashlib.sha256(png()).hexdigest())
        self.assertEqual(result['imageInfo'], {'format': 'png', 'width': 1, 'height': 1})
        self.assertEqual(self.report('request-1')['sha256'], result['sha256'])
        self.assertEqual(len(self.posts), 1)
        endpoint, body = self.posts[0]
        self.assertEqual(endpoint, '/api/tool/capture')
        for key, expected in {'kind': 'auto', 'allowNative': True, 'excludeUi': False,
                              'allowTimeScale': True, 'checkpointId': 'request-1',
                              'recording': 'autotest', 'variant': 'diagnostic',
                              'timeoutMs': 8000}.items():
            self.assertEqual(body[key], expected)
        self.assertEqual(Path(body['outDir']), (self.root / 'request-1').resolve())
        self.assertEqual(Path.cwd(), before_cwd)
        self.assertEqual({p.name: p.read_bytes() for p in self.outside.iterdir()}, before_outside)
        self.assertEqual(self.events[0][0], 'guard')
        self.assertEqual(self.events[-2][0], 'guard')
        self.assertEqual(self.events[-1], ('get', '/api/health'))

    def test_http_native_bmp_keeps_degradation_and_verifies_bytes(self):
        self.mode = 'bmp'
        result = screenshots.capture(self.root, 'native-1', self.guard, self.call)
        self.assertTrue(result['captureFileVerified'])
        self.assertEqual(Path(result['image']).read_bytes(), bmp())
        self.assertEqual(result['imageInfo'], {'format': 'bmp', 'width': 1, 'height': 1})
        self.assertEqual(result['providerReceipt']['degraded'], ['nativeFallback'])
        self.assertEqual(result['sha256'], hashlib.sha256(bmp()).hexdigest())

    def test_announcement_finishes_before_single_capture(self):
        screenshots.capture(self.root, 'announced', self.guard, self.call,
                            announce=lambda text: self.events.append(('announcement', text)))
        names = [e[0] for e in self.events]
        self.assertLess(names.index('announcement'), names.index('post'))
        self.assertEqual(names.count('post'), 1)

    def test_http_receipt_without_valid_new_image_is_failure(self):
        for mode in ('missing', 'empty', 'corrupt', 'truncated', 'false', 'string-ok',
                     'missing-ok', 'different-path', 'wrong-bytes', 'boolean-bytes',
                     'disguised-format'):
            with self.subTest(mode=mode):
                self.mode = mode
                count = len(self.posts)
                with self.assertRaises((ValueError, RuntimeError, OSError, zlib.error)):
                    screenshots.capture(self.root, mode, self.guard, self.call)
                report = self.report(mode)
                self.assertFalse(report['captureFileVerified'])
                self.assertNotEqual(report['status'], 'file_verified')
                self.assertIn('providerReceipt', report)
                self.assertEqual(len(self.posts), count + 1)

    def test_http_receipt_filename_cannot_escape_or_adopt_another_request(self):
        for mode in ('traversal', 'absolute', 'wrong-stem'):
            with self.subTest(mode=mode):
                self.mode = mode
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    screenshots.capture(self.root, mode, self.guard, self.call)
                self.assertFalse(self.report(mode)['captureFileVerified'])
        self.assertEqual(self.sentinel.read_bytes(), b'owner-original')
        self.assertEqual(list(self.outside.iterdir()), [self.sentinel])

    def test_duplicate_verified_request_never_posts_again(self):
        first = screenshots.capture(self.root, 'same-id', self.guard, self.call)
        with self.assertRaises((FileExistsError, ValueError, RuntimeError)):
            screenshots.capture(self.root, 'same-id', self.guard, self.call)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.report('same-id')['sha256'], first['sha256'])

    def test_timeout_preserves_uncertainty_and_duplicate_never_posts(self):
        dispatches = []

        def uncertain(body):
            dispatches.append(body)
            raise TimeoutError('response lost after dispatch')

        with self.assertRaises(TimeoutError):
            screenshots.capture(self.root, 'lost-response', self.guard, uncertain)
        self.assertFalse(self.report('lost-response')['captureFileVerified'])
        with self.assertRaises((FileExistsError, ValueError, RuntimeError)):
            screenshots.capture(self.root, 'lost-response', self.guard, self.call)
        self.assertEqual(len(dispatches), 1)
        self.assertEqual(self.posts, [])

    def test_pre_capture_guard_or_announcement_failure_never_posts(self):
        def failed(*args):
            raise RuntimeError('identity or announcement unavailable')

        for identifier, guard, announce in (('guard-failed', failed, None),
                                            ('announce-failed', self.guard, failed)):
            with self.subTest(identifier=identifier), self.assertRaises(RuntimeError):
                screenshots.capture(self.root, identifier, guard, self.call, announce=announce)
            self.assertFalse(self.report(identifier)['captureFileVerified'])
        self.assertEqual(self.posts, [])

    def test_invalid_identifier_never_posts_or_changes_external_files(self):
        for identifier in ('../escape', '/absolute', 'a/b', 'a\\b', ''):
            with self.subTest(identifier=identifier), self.assertRaises((ValueError, RuntimeError)):
                screenshots.capture(self.root, identifier, self.guard, self.call)
        self.assertEqual(self.posts, [])
        self.assertEqual(self.sentinel.read_bytes(), b'owner-original')

    def test_relative_output_or_different_checkpoint_never_posts(self):
        for index, options in enumerate(({'outDir': 'relative-output'},
                                         {'checkpointId': 'other-request'})):
            with self.subTest(options=options), self.assertRaises((ValueError, RuntimeError)):
                screenshots.capture(self.root, 'bad-options-' + str(index),
                                    self.guard, self.call, options=options)
        self.assertEqual(self.posts, [])

    def test_explicit_provider_and_output_options_are_preserved(self):
        selected = self.base / 'provider-output'
        options = {'kind': 'registered-provider', 'allowNative': False, 'excludeUi': True,
                   'allowTimeScale': False, 'recording': 'selected-recording',
                   'variant': 'original', 'outDir': str(selected.resolve()), 'timeoutMs': 1234}
        result = screenshots.capture(self.root, 'selected', self.guard, self.call, options=options)
        self.assertTrue(result['captureFileVerified'])
        self.assertEqual(Path(result['image']), selected / 'selected-recording' / 'original' / 'selected.png')
        for key, expected in options.items():
            self.assertEqual(self.posts[0][1][key], expected)
        self.assertTrue((self.root / 'selected' / 'screenshot-receipt.json').is_file())

    def test_existing_external_image_is_never_adopted_or_overwritten(self):
        selected = self.base / 'provider-output'
        existing = selected / 'autotest' / 'diagnostic' / 'existing.png'
        existing.parent.mkdir(parents=True)
        existing.write_bytes(png())
        with self.assertRaises((ValueError, RuntimeError)):
            screenshots.capture(self.root, 'existing', self.guard, self.call,
                                options={'outDir': str(selected.resolve())})
        self.assertEqual(self.posts, [])
        self.assertEqual(existing.read_bytes(), png())
        self.assertFalse(self.report('existing')['captureFileVerified'])

    @unittest.skipUnless(os.name == 'nt', 'CLI requires Windows')
    def test_cli_uses_exact_identity_and_devbench_without_audio_arguments(self):
        identity = {'pid': 12345, 'birth': 10001, 'path': 'C:/fixture/SkyrimSE.exe'}
        identity_file = self.base / 'identity.json'
        identity_file.write_text(json.dumps(identity), encoding='utf-8')
        output = io.StringIO()
        with patch('skyrim_autotest.native.alive', return_value=True) as alive, redirect_stdout(output):
            exit_code = screenshots.main(['--out', str(self.root), '--id', 'cli-request',
                                          '--identity', str(identity_file), '--port', str(self.port)])
        self.assertEqual(exit_code, 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result['captureFileVerified'])
        self.assertEqual(Path(result['image']).read_bytes(), png())
        self.assertEqual(len(self.posts), 1)
        self.assertGreaterEqual(alive.call_count, 2)
        self.assertTrue(all(call.args == (identity,) for call in alive.call_args_list))

    def test_symlink_or_reparse_output_cannot_be_verified(self):
        probe = self.base / 'symlink-probe'
        try:
            probe.symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symbolic links unavailable without platform privileges')
        else:
            probe.unlink()
        for mode in ('symlink', 'directory-symlink'):
            with self.subTest(mode=mode):
                self.mode = mode
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    screenshots.capture(self.root, mode, self.guard, self.call)
                self.assertFalse(self.report(mode)['captureFileVerified'])
        self.assertEqual(self.sentinel.read_bytes(), b'owner-original')


if __name__ == '__main__':
    unittest.main()
