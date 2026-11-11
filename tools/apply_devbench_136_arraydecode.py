"""Prepare only our exact DevBench 1.36/CommonLib decoder repair externally.

Default is read-only review. --apply writes the repair, owned regressions and
an original-TU negative control, never builds, installs, commits or starts a game.
"""
import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEV_BENCH = 'cb0c0a9898f656e6df9697570026e7ef2705c44f'
SUBMODULES = {
    'lib/commonlibsse-ng': 'abe9ca7b7318dbc04bccfcd59fc3fb670244c2d7',
    'lib/cpp-mcp': 'f1117d5286efe6477ddd14322703f034615b6c0e',
    'lib/commonlibsse-ng/extern/openvr': '60eb187801956ad277f1cae6680e3a410ee0873b',
}
TYPEINFO = 'lib/commonlibsse-ng/src/RE/T/TypeInfo.cpp'
BEFORE = 'a3766c4636da466eb416af393a89ea124ffc235c742c904d55fb62eca4d3f74d'
AFTER = '28b198b61889d9f8dcd479e4bb9333d8a8073a509df3d4515cbf4fae329d3ab9'
XMAKE_BEFORE = '285926cad0ca7305aef9b32373ea27223213b6b1dc6c8a20d187a6e9ea6e19cd'
OWNED = {
    'tests/regressions/TypeInfoArrayDecode.cpp': 'typeinfo_array_decode_136.cpp',
    'tests/regressions/TypeInfoPCH.h': 'typeinfo_assertion_pch.h',
}
FIXED_FUNCTION = b'''\t\tObjectTypeInfo* TypeInfo::GetTypeInfo() const
\t\t{
\t\t\tconst auto rawType = std::to_underlying(GetRawType());
\t\t\tif (rawType < std::to_underlying(RawType::kArraysEnd)) {
\t\t\t\treturn nullptr;
\t\t\t}
\t\t\tassert(IsObject() || IsObjectArray());
\t\t\t// Only bit 0 tags an object array; the other enum bits belong to the pointer.
\t\t\treturn reinterpret_cast<ObjectTypeInfo*>(rawType & ~std::to_underlying(RawType::kObject));
\t\t}'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    value = data.replace(b'\r\n', b'\n')
    if b'\r' in value or (b'\r\n' in data and data.count(b'\r\n') != value.count(b'\n')):
        raise ValueError('Mixed or bare-CR line endings are unsupported')
    return value


def original_eol(value, original):
    return value.replace(b'\n', b'\r\n') if b'\r\n' in original else value


def transform(data):
    """Pure, complete-preimage and complete-postimage checked function replacement."""
    text = canonical(data)
    if digest(text) != BEFORE:
        raise ValueError('Pinned TypeInfo preimage changed or was already patched')
    start = b'\t\tObjectTypeInfo* TypeInfo::GetTypeInfo() const\n'
    end = b'\n\n\t\tauto TypeInfo::GetUnmangledRawType() const'
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError('Ambiguous decoder function boundaries')
    first, last = text.index(start), text.index(end)
    if last <= first:
        raise ValueError('Invalid decoder function order')
    result = text[:first] + FIXED_FUNCTION + text[last:]
    if digest(result) != AFTER:
        raise ValueError('Patched TypeInfo postimage mismatch')
    return original_eol(result, data)


def external_source(path):
    source = Path(path).resolve()
    if (source == ROOT or ROOT in source.parents or
            any((parent / '.git').exists() for parent in source.parents) or
            {part.lower() for part in source.parts} & {'mods', 'data', 'overwrite', 'downloads'}):
        raise ValueError('Source must be an independent external development checkout')
    return source


def verify_checkout(source):
    def git(path, *args):
        return subprocess.check_output(['git', '-C', str(path), *args], text=True,
                                       stderr=subprocess.PIPE, timeout=30).strip()
    if git(source, 'remote', 'get-url', 'origin') != 'https://github.com/alandtse/devbench.git':
        raise ValueError('Unexpected official DevBench remote')
    for path, expected in {'.': DEV_BENCH, **SUBMODULES}.items():
        checkout = source / path
        if (git(checkout, 'rev-parse', 'HEAD') != expected or
                git(checkout, 'status', '--porcelain', '--untracked-files=all')):
            raise ValueError('Official checkout/submodule changed: ' + path)


def prepare(path):
    """Read and validate every source/output precondition before any file write."""
    source = external_source(path)
    verify_checkout(source)
    inputs = {}
    for relative in (TYPEINFO, 'xmake.lua'):
        target = source / relative
        if target.is_symlink() or not target.resolve().is_relative_to(source):
            raise ValueError('Source file escapes checkout')
        inputs[target] = target.read_bytes()
    before = inputs[source / TYPEINFO]
    outputs = {source / TYPEINFO: transform(before)}
    xmake = canonical(inputs[source / 'xmake.lua'])
    if digest(xmake) != XMAKE_BEFORE:
        raise ValueError('Pinned upstream Xmake preimage changed')
    snippet = canonical((ROOT / 'tools/native/devbench_136_arraydecode.xmake.lua').read_bytes())
    outputs[source / 'xmake.lua'] = original_eol(xmake + b'\n' + snippet, inputs[source / 'xmake.lua'])
    for relative, owned in OWNED.items():
        outputs[source / relative] = canonical((ROOT / 'tools/native' / owned).read_bytes())
    backup = source.parent / 'TypeInfo-before.cpp'
    receipt = source.parent / 'devbench-136-arraydecode.json'
    outputs[backup] = before
    for target in [*outputs, receipt]:
        allowed = target in inputs or target in (backup, receipt)
        if (not allowed and not target.resolve().is_relative_to(source)) or target.is_symlink():
            raise ValueError('Repair output escapes checkout')
        if target not in inputs and target.exists():
            raise ValueError('Repair output already exists; no replay or overwrite')
    return source, inputs, outputs, receipt


@contextmanager
def exclusive_file(path, *, create=False):
    """Windows share-deny handle: other opens cannot write, rename or delete it."""
    if os.name != 'nt':
        raise ValueError('File application requires Windows exclusive handles; review is portable')
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    handle = kernel.CreateFileW(str(path), 0xC0000000, 0, None, 1 if create else 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, 'r+b', buffering=0) as stream:
        yield stream


def contents(stream):
    stream.seek(0)
    return stream.read()


def write_checked(path, stream, expected, data):
    if contents(stream) != expected:
        raise ValueError('Source changed before replacement: ' + str(path))
    stream.seek(0)
    if stream.write(data) != len(data):
        raise OSError('Incomplete repair write: ' + str(path))
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())
    if contents(stream) != data:
        raise OSError('Repair readback failed: ' + str(path))


def checkpoint(receipt, state, *, initial=False):
    temporary = receipt if initial else receipt.with_suffix('.pending')
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(state, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    if not initial:
        temporary.replace(receipt)


def apply(path):
    source, inputs, outputs, receipt = prepare(path)
    # Recheck immediately before the first write, including both captured files.
    if any(target.read_bytes() != before for target, before in inputs.items()):
        raise ValueError('Source changed after preparation; nothing written')
    result = {'sourceCommit': DEV_BENCH, 'submodules': SUBMODULES,
              'canonicalTypeInfoBefore': BEFORE, 'canonicalTypeInfoAfter': AFTER,
              'gameValidated': False, 'installedFilesChanged': False, 'buildPerformed': False,
              'changes': [{'path': str(target), 'beforeSha256': digest(inputs[target]) if target in inputs else None,
                           'afterSha256': digest(data)} for target, data in outputs.items()]}
    state = {**result, 'completed': False, 'operations': [], 'rollback': [], 'stagedFilesRetained': True}
    checkpoint(receipt, state, initial=True)
    attempted = []
    with ExitStack() as leases:
        handles = {}
        try:
            # Hold both tracked-file leases through commit/rollback, not just
            # their initial read. Edits after receipt reservation are detected.
            for target, original in inputs.items():
                handles[target] = leases.enter_context(exclusive_file(target))
                if contents(handles[target]) != original:
                    raise ValueError('Source changed before replacement: ' + str(target))
            backup = source.parent / 'TypeInfo-before.cpp'
            # The verified, durable original exists before ANY tracked write.
            order = [backup, *[target for target in outputs if target not in inputs and target != backup], *inputs]
            for target in order:
                state['operations'].append({'path': str(target), 'state': 'pending'})
                checkpoint(receipt, state)
                if target not in handles:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    handles[target] = leases.enter_context(exclusive_file(target, create=True))
                if target in inputs:
                    attempted.append(target)
                write_checked(target, handles[target], inputs.get(target, b''), outputs[target])
                state['operations'][-1]['state'] = 'verified'
                checkpoint(receipt, state)
            if any(contents(handles[target]) != data for target, data in outputs.items()):
                raise OSError('Final leased output verification failed')
            state['completed'] = True
            checkpoint(receipt, state)
        except BaseException as error:
            state.update(completed=False, errorType=type(error).__name__)
            for target in reversed(attempted):
                rollback = {'path': str(target)}
                try:
                    current = contents(handles[target])
                    rollback['observedSha256'] = digest(current)
                    if current == inputs[target]:
                        rollback['state'] = 'unchanged'
                    elif current == outputs[target]:
                        write_checked(target, handles[target], outputs[target], inputs[target])
                        rollback['state'] = 'restored-original'
                    else:
                        rollback['state'] = 'unsafe-bytes-preserved'
                except BaseException as rollback_error:
                    rollback.update(state='rollback-unconfirmed', errorType=type(rollback_error).__name__)
                state['rollback'].append(rollback)
            try:
                checkpoint(receipt, state)
            except OSError:
                pass  # Keep the last durable pending journal and primary error.
            raise
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        result = apply(args.source)
    else:
        source, _, outputs, receipt = prepare(args.source)
        result = {'source': str(source), 'reviewOnly': True, 'writesPerformed': False,
                  'plannedFiles': [str(path) for path in outputs], 'receipt': str(receipt)}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
