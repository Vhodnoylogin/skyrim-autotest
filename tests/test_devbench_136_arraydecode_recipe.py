"""Offline preparation boundaries; synthetic source is not SDK/game qualification."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('decoder_recipe', ROOT / 'tools/apply_devbench_136_arraydecode.py')
recipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recipe)
VERIFY_CHECKOUT = recipe.verify_checkout


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source'
        self.source.mkdir()
        self.prefix = b'// synthetic untouched prefix\n'
        self.suffix = b'\n\n\t\tauto TypeInfo::GetUnmangledRawType() const\n// untouched suffix\n'
        self.before = self.prefix + b'\t\tObjectTypeInfo* TypeInfo::GetTypeInfo() const\n\t\t{ return nullptr; }' + self.suffix
        self.after = self.prefix + recipe.FIXED_FUNCTION + self.suffix
        self.xmake = b'-- synthetic original Xmake\n'
        for attribute, value in (('BEFORE', self.before), ('AFTER', self.after), ('XMAKE_BEFORE', self.xmake)):
            patch = mock.patch.object(recipe, attribute, recipe.digest(value))
            patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch.object(recipe, 'verify_checkout')
        self.checkout = patch.start(); self.addCleanup(patch.stop)
        self.decoder = self.source / recipe.TYPEINFO
        self.decoder.parent.mkdir(parents=True)
        self.decoder.write_bytes(self.before)
        (self.source / 'xmake.lua').write_bytes(self.xmake)

    def untouched(self):
        self.assertEqual(self.decoder.read_bytes(), self.before)
        self.assertEqual((self.source / 'xmake.lua').read_bytes(), self.xmake)
        self.assertFalse((self.base / 'TypeInfo-before.cpp').exists())
        self.assertFalse((self.base / 'devbench-136-arraydecode.json').exists())

    def test_whole_pre_and_postimage_preserve_surrounding_bytes(self):
        self.assertEqual(recipe.transform(self.before), self.after)
        self.assertEqual(self.decoder.read_bytes(), self.before)

    def test_crlf_source_keeps_crlf_and_same_canonical_identity(self):
        self.assertEqual(recipe.transform(self.before.replace(b'\n', b'\r\n')), self.after.replace(b'\n', b'\r\n'))

    def test_changed_and_already_patched_source_stop(self):
        for source in (self.before + b'changed', self.after):
            with self.assertRaisesRegex(ValueError, 'preimage'):
                recipe.transform(source)
        self.untouched()

    def test_postimage_guard_detects_accidental_fix_change(self):
        with mock.patch.object(recipe, 'FIXED_FUNCTION', recipe.FIXED_FUNCTION + b'\nchanged'):
            with self.assertRaisesRegex(ValueError, 'postimage'):
                recipe.transform(self.before)

    def test_ambiguous_and_reversed_function_boundaries_are_rejected(self):
        for value in (self.before * 2, self.suffix + self.before[:-len(self.suffix)]):
            with mock.patch.object(recipe, 'BEFORE', recipe.digest(value)):
                with self.assertRaisesRegex(ValueError, 'boundaries|order'):
                    recipe.transform(value)

    def test_mixed_and_bare_cr_are_refused(self):
        for value in (b'a\r\nb\n', b'a\rb\n'):
            with self.assertRaisesRegex(ValueError, 'line endings'):
                recipe.canonical(value)

    def test_readonly_preparation_does_not_change_files(self):
        source, inputs, outputs, receipt = recipe.prepare(self.source)
        self.assertEqual(source, self.source.resolve())
        self.assertEqual(len(inputs), 2)
        self.assertEqual(len(outputs), 5)
        self.assertEqual(receipt.name, 'devbench-136-arraydecode.json')
        self.checkout.assert_called_once_with(source)
        self.untouched()

    def test_checkout_identity_failure_precedes_writes(self):
        self.checkout.side_effect = ValueError('Official checkout/submodule changed')
        with self.assertRaisesRegex(ValueError, 'checkout'):
            recipe.apply(self.source)
        self.untouched()

    def test_real_identity_guard_checks_remote_every_head_and_clean_status(self):
        heads = {str(self.source / key): value for key, value in {'.': recipe.DEV_BENCH, **recipe.SUBMODULES}.items()}
        def git(command, **kwargs):
            path, args = command[2], command[3:]
            if args == ['remote', 'get-url', 'origin']:
                return 'https://github.com/alandtse/devbench.git\n'
            if args == ['rev-parse', 'HEAD']:
                return heads[path] + '\n'
            if args == ['status', '--porcelain', '--untracked-files=all']:
                return ''
            self.fail('Unexpected Git invocation: ' + str(command))
        with mock.patch.object(recipe.subprocess, 'check_output', side_effect=git) as call:
            VERIFY_CHECKOUT(self.source)
            self.assertEqual(call.call_count, 1 + 2 * len(heads))
            heads[str(self.source / 'lib/cpp-mcp')] = '0' * 40
            with self.assertRaisesRegex(ValueError, 'checkout/submodule'):
                VERIFY_CHECKOUT(self.source)

    def test_real_identity_guard_refuses_foreign_remote(self):
        with mock.patch.object(recipe.subprocess, 'check_output', return_value='https://example.invalid/fork.git'):
            with self.assertRaisesRegex(ValueError, 'remote'):
                VERIFY_CHECKOUT(self.source)

    def test_xmake_drift_is_rejected_before_decoder_write(self):
        (self.source / 'xmake.lua').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Xmake preimage'):
            recipe.apply(self.source)
        self.assertEqual(self.decoder.read_bytes(), self.before)
        self.assertFalse((self.base / 'devbench-136-arraydecode.json').exists())

    def test_existing_outputs_are_not_overwritten(self):
        for relative in ('TypeInfo-before.cpp', 'devbench-136-arraydecode.json',
                         'source/tests/regressions/TypeInfoArrayDecode.cpp', 'source/tests/regressions/TypeInfoPCH.h'):
            target = self.base / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'owner original')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                recipe.apply(self.source)
            self.assertEqual(target.read_bytes(), b'owner original')
            self.assertEqual(self.decoder.read_bytes(), self.before)
            target.unlink()

    def test_repository_nested_and_live_destinations_are_refused(self):
        for path in (ROOT, ROOT / 'source', self.base / 'mods/source', self.base / 'Data/source'):
            with self.assertRaisesRegex(ValueError, 'external'):
                recipe.external_source(path)
        (self.base / '.git').mkdir()
        with self.assertRaisesRegex(ValueError, 'external'):
            recipe.external_source(self.source)

    def test_changed_bytes_between_prepare_and_write_are_not_applied(self):
        real = recipe.prepare
        def changed(path):
            plan = real(path)
            self.decoder.write_bytes(b'new concurrent source')
            return plan
        with mock.patch.object(recipe, 'prepare', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed after preparation'):
                recipe.apply(self.source)
        self.assertEqual(self.decoder.read_bytes(), b'new concurrent source')
        self.assertEqual((self.source / 'xmake.lua').read_bytes(), self.xmake)
        self.assertFalse((self.base / 'devbench-136-arraydecode.json').exists())

    def test_apply_preserves_eol_captures_original_and_cannot_replay(self):
        self.decoder.write_bytes(self.before.replace(b'\n', b'\r\n'))
        result = recipe.apply(self.source)
        self.assertEqual(self.decoder.read_bytes(), self.after.replace(b'\n', b'\r\n'))
        self.assertEqual((self.base / 'TypeInfo-before.cpp').read_bytes(), self.before.replace(b'\n', b'\r\n'))
        saved = json.loads((self.base / 'devbench-136-arraydecode.json').read_text())
        self.assertTrue(saved['completed'])
        self.assertFalse(result['installedFilesChanged'])
        self.assertFalse(result['gameValidated'])
        self.assertFalse(result['buildPerformed'])
        snapshot = {path: path.read_bytes() for path in self.base.rglob('*') if path.is_file()}
        with self.assertRaisesRegex(ValueError, 'preimage'):
            recipe.apply(self.source)
        self.assertEqual(snapshot, {path: path.read_bytes() for path in snapshot})

    def test_partial_write_failure_retains_incomplete_receipt_without_replay(self):
        real_write = recipe.write_checked
        verified_backup = []
        def fail(path, stream, expected, data):
            if path == self.source / 'xmake.lua':
                raise OSError('owned synthetic disk failure')
            if path == self.decoder:
                self.assertEqual(verified_backup, [self.before])
            result = real_write(path, stream, expected, data)
            if path == self.base / 'TypeInfo-before.cpp':
                verified_backup.append(recipe.contents(stream))
            return result
        with mock.patch.object(recipe, 'write_checked', side_effect=fail):
            with self.assertRaises(OSError):
                recipe.apply(self.source)
        receipt = self.base / 'devbench-136-arraydecode.json'
        state = json.loads(receipt.read_text())
        self.assertFalse(state['completed'])
        self.assertEqual(self.decoder.read_bytes(), self.before)
        self.assertEqual((self.base / 'TypeInfo-before.cpp').read_bytes(), self.before)
        self.assertIn('restored-original', [row['state'] for row in state['rollback']])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            recipe.apply(self.source)

    def test_foreign_xmake_edit_after_receipt_is_preserved(self):
        checkpoint = recipe.checkpoint
        def edit_after_reservation(path, state, *, initial=False):
            checkpoint(path, state, initial=initial)
            if initial:
                (self.source / 'xmake.lua').write_bytes(b'concurrent owner edit')
        with mock.patch.object(recipe, 'checkpoint', side_effect=edit_after_reservation):
            with self.assertRaisesRegex(ValueError, 'changed before replacement'):
                recipe.apply(self.source)
        self.assertEqual((self.source / 'xmake.lua').read_bytes(), b'concurrent owner edit')
        self.assertEqual(self.decoder.read_bytes(), self.before)
        self.assertFalse(json.loads((self.base / 'devbench-136-arraydecode.json').read_text())['completed'])

    def test_tracked_file_lease_blocks_foreign_write_during_apply(self):
        checkpoint = recipe.checkpoint
        attempts = []
        def attempt_write(path, state, *, initial=False):
            checkpoint(path, state, initial=initial)
            if any(row['path'] == str(self.decoder) and row['state'] == 'verified' for row in state['operations']):
                with self.assertRaises(PermissionError):
                    (self.source / 'xmake.lua').write_bytes(b'foreign write must fail')
                attempts.append(True)
        with mock.patch.object(recipe, 'checkpoint', side_effect=attempt_write):
            recipe.apply(self.source)
        self.assertTrue(attempts)

    def test_rollback_never_overwrites_unrecognized_bytes_and_continues(self):
        write = recipe.write_checked
        def fail_with_changed_bytes(path, stream, expected, data):
            if path == self.source / 'xmake.lua':
                # Model an unknown partial write/foreign mutation even though
                # normal outside writes are excluded by the Windows lease.
                stream.seek(0); stream.write(b'foreign bytes'); stream.truncate()
                raise OSError('unknown completion')
            return write(path, stream, expected, data)
        with mock.patch.object(recipe, 'write_checked', side_effect=fail_with_changed_bytes):
            with self.assertRaises(OSError):
                recipe.apply(self.source)
        self.assertEqual((self.source / 'xmake.lua').read_bytes(), b'foreign bytes')
        self.assertEqual(self.decoder.read_bytes(), self.before)
        self.assertEqual((self.base / 'TypeInfo-before.cpp').read_bytes(), self.before)
        state = json.loads((self.base / 'devbench-136-arraydecode.json').read_text())
        self.assertFalse(state['completed'])
        self.assertEqual([row['state'] for row in state['rollback']], ['unsafe-bytes-preserved', 'restored-original'])

    def test_one_rollback_error_preserves_primary_and_does_not_skip_other_file(self):
        write = recipe.write_checked
        def fail(path, stream, expected, data):
            if path == self.source / 'xmake.lua':
                if expected == self.xmake:
                    write(path, stream, expected, data)
                    raise ValueError('primary synthetic failure')
                raise OSError('independent rollback failure')
            return write(path, stream, expected, data)
        with mock.patch.object(recipe, 'write_checked', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'primary synthetic failure'):
                recipe.apply(self.source)
        self.assertEqual(self.decoder.read_bytes(), self.before)
        state = json.loads((self.base / 'devbench-136-arraydecode.json').read_text())
        self.assertFalse(state['completed'])
        self.assertEqual(state['errorType'], 'ValueError')
        self.assertEqual([row['state'] for row in state['rollback']], ['rollback-unconfirmed', 'restored-original'])


if __name__ == '__main__':
    unittest.main()
