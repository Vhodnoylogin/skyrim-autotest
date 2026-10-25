"""Non-game safety checks for the exact-source external compatibility recipe."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(ROOT / 'tools'))
patcher = load('apply_devbench_current')
builder = load('build_devbench_current')
sys.path.pop(0)


class CurrentRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        # Synthetic patch context; no third-party source fixture is retained.
        self.inputs = {
            'src/Tools.cpp': b'''#include "Tools.h"
\t\t\tif (action == "list") {
\t\t\t\tjson open = json::array();
\t\t\tmenu.inputSchema = json{
{ "index", json{ { "type", "integer" }, { "description", "accept: 0-based button index to select (default 0). See describe's buttons/cancelIndex." } } },
''',
            'src/ToolRegistry.cpp': b'#include "ToolRegistry.h"\nToolResult::Success(handler(a_args, a_ctx))\n',
            'xmake.lua': b'-- synthetic build file\n',
            'lib/commonlibsse-ng/src/RE/T/TypeInfo.cpp': b'object = value & ~std::to_underlying(RawType::kObject);\narray = value & ~std::to_underlying(RawType::kObjectArray);\n',
        }
        self.payloads = {'src/TextEncoding.h': b'// synthetic acquired owned correction\n',
                         'tests/TextEncoding_test.cpp': b'// synthetic acquired owned tests\n'}
        for relative, data in self.inputs.items():
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for constant, data in [('BASE_SHA256', self.inputs), ('OWNED_PAYLOADS', self.payloads)]:
            context = mock.patch.dict(getattr(patcher, constant), {k: patcher.digest(v) for k, v in data.items()}, clear=True)
            context.start()
            self.addCleanup(context.stop)

    def assert_unmodified(self):
        for relative, data in self.inputs.items():
            self.assertEqual((self.source / relative).read_bytes(), data)
        self.assertFalse((self.source / 'src/CurrentMenuState.h').exists())

    def test_source_drift_is_rejected_before_any_write(self):
        target = self.source / 'xmake.lua'
        target.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Pinned source digest mismatch'):
            patcher.apply(self.source, self.payloads)
        self.assertEqual((self.source / 'src/Tools.cpp').read_bytes(), self.inputs['src/Tools.cpp'])
        self.assertFalse((self.source / 'src/CurrentMenuState.h').exists())

    def test_owned_payload_drift_is_rejected_before_any_write(self):
        with self.assertRaisesRegex(ValueError, 'Owned correction digest mismatch'):
            patcher.apply(self.source, dict(self.payloads, **{'src/TextEncoding.h': b'wrong'}))
        self.assert_unmodified()

    def test_existing_owned_output_is_not_overwritten(self):
        target = self.source / 'src/CurrentMenuState.h'
        target.write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            patcher.apply(self.source, self.payloads)
        self.assertEqual(target.read_bytes(), b'preserve')
        self.assertEqual((self.source / 'src/Tools.cpp').read_bytes(), self.inputs['src/Tools.cpp'])

    def test_ambiguous_anchor_is_rejected_before_any_write(self):
        relative = 'src/ToolRegistry.cpp'
        value = self.inputs[relative] + b'ToolResult::Success(handler(a_args, a_ctx))\n'
        (self.source / relative).write_bytes(value)
        patcher.BASE_SHA256[relative] = patcher.digest(value)
        with self.assertRaisesRegex(ValueError, 'Exact patch anchor mismatch'):
            patcher.apply(self.source, self.payloads)
        self.assertEqual((self.source / 'src/Tools.cpp').read_bytes(), self.inputs['src/Tools.cpp'])

    def test_corrections_preserve_unavailable_flags_and_single_dispatch(self):
        result = patcher.apply(self.source, self.payloads)
        self.assertEqual(result['liveQualification'], 'pending')
        self.assertFalse(result['installedFilesChanged'])
        tools = (self.source / 'src/Tools.cpp').read_text()
        self.assertIn('"includeFlags", json{ { "type", "boolean" }', tools)
        self.assertIn('"menuStates", std::move(states)', tools)
        helper = (self.source / 'src/CurrentMenuState.h').read_text()
        for flag in ('alwaysOpen', 'pausesGame', 'modal', 'usesCursor', 'usesMenuContext', 'freezeFramePause'):
            self.assertIn('"' + flag + '"', helper)
        self.assertIn('if (menu)', helper)
        registry = (self.source / 'src/ToolRegistry.cpp').read_text()
        self.assertEqual(registry.count('handler(a_args, a_ctx)'), 1)
        self.assertIn('NormalizeToolText(handler(a_args, a_ctx))', registry)
        decoder = (self.source / 'lib/commonlibsse-ng/src/RE/T/TypeInfo.cpp').read_text()
        self.assertNotIn('RawType::kObjectArray', decoder)
        for row in result['changes']:
            self.assertEqual(row['patchedSha256'], patcher.digest((self.source / row['path']).read_bytes()))
        with self.assertRaisesRegex(ValueError, 'Pinned source digest mismatch'):
            patcher.apply(self.source, self.payloads)

    def test_crlf_checkout_is_accepted_but_manifest_hashes_canonical_lf(self):
        for relative, data in self.inputs.items():
            (self.source / relative).write_bytes(data.replace(b'\n', b'\r\n'))
        result = patcher.apply(self.source, self.payloads)
        self.assertEqual(result['changes'][0]['originalSha256'], patcher.digest(self.inputs['src/Tools.cpp']))

    def test_repository_and_nested_git_output_are_refused(self):
        with self.assertRaises(ValueError):
            patcher.external_source(ROOT)
        (self.base / '.git').mkdir()
        with self.assertRaises(ValueError):
            patcher.external_source(self.source)
        with self.assertRaises(ValueError):
            builder.new_output(self.base / 'build')

    def test_deployment_environment_is_removed(self):
        with mock.patch.dict(os.environ, {'SkyrimPluginTargets': 'live', 'COMMONLIB_PREBUILT': 'stale', 'GITHUB_ACTIONS': 'true'}):
            env = builder.build_environment()
            for key in ('SkyrimPluginTargets', 'COMMONLIB_PREBUILT', 'GITHUB_ACTIONS'):
                self.assertNotIn(key, env)

    def test_xmake_rejects_bad_digest_before_extraction(self):
        archive = self.base / 'bad.zip'
        archive.write_bytes(b'not trusted')
        output = self.base / 'tools'
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            builder.extract_xmake(archive, output)
        self.assertFalse(output.exists())

    def test_xmake_rejects_archive_traversal(self):
        archive = self.base / 'escape.zip'
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('../escape', 'bad')
        with mock.patch.object(builder, 'XMAKE_SHA', builder.sha(archive)):
            with self.assertRaisesRegex(ValueError, 'path escape'):
                builder.extract_xmake(archive, self.base / 'tools')
        self.assertFalse((self.base / 'escape').exists())

    def test_cached_payload_mismatch_never_falls_back_to_network(self):
        cache = self.base / 'cache'
        cache.mkdir()
        (cache / 'TextEncoding.h').write_bytes(b'incorrect')
        with mock.patch.object(patcher.urllib.request, 'urlopen') as network:
            with self.assertRaisesRegex(ValueError, 'cached source digest mismatch'):
                patcher.acquire_payloads(cache)
        network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
