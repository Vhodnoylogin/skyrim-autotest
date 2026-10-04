"""Reacquire pinned external source and build it with our file-control adapter.

All downloaded source, SDK headers and compiler outputs live outside Git in the configured external runtime directory.
Only our protocol and transformation instructions belong in this repository.
Requires Microsoft Visual Studio C++ desktop tools (MSVC, Windows SDK).
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
from . import runner

COMMIT = 'dedb8ab33fc46b25ecee191f882951c064422505'
URL = 'https://github.com/DubiousDuo/VR-Emulator-Driver---SkyrimVR-Devkit.git'
SDK_URL = 'https://raw.githubusercontent.com/ValveSoftware/openvr/v1.26.7/headers/openvr_driver.h'
SDK_HASH = '2d0f91ea9bfe0ef1a60d0010f7a8fb8b4ce8bed759803c135ce4f185bdf4a9ab'
HERE = Path(__file__).resolve().parent


def replace_function(text, signature, body):
    start = text.index(signature)
    opening = text.index('{', start + len(signature))
    depth = 1
    cursor = opening + 1
    while depth:
        depth += (text[cursor] == '{') - (text[cursor] == '}')
        cursor += 1
    return text[:opening] + '{\n' + body + '\n}' + text[cursor:]


def main():
    # Fetch only the pinned source files, avoiding the repository's huge binary
    # history/archive. Foreign content is cached externally; this package stores
    # filenames/digests only. Leave any incomplete old Git cache untouched.
    pins = runner.read_json(HERE / 'driver_sources.json')
    if pins['commit'] != COMMIT:
        raise RuntimeError('Source catalogue commit mismatch')
    source = runner.ROOT / 'dependencies/driver-source-files'
    source.mkdir(parents=True, exist_ok=True)
    build = runner.ROOT / 'dependencies/driver-build'
    build.mkdir(exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor
    def acquire(item):
        name, digest = item
        file = source / name
        if file.is_file() and runner.sha(file) == digest:
            return file
        url = 'https://raw.githubusercontent.com/DubiousDuo/VR-Emulator-Driver---SkyrimVR-Devkit/' + COMMIT + '/' + name
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError('Pinned source hash/size mismatch: ' + name)
        file.write_bytes(data)
        return file
    with ThreadPoolExecutor(max_workers=4) as workers:
        files = list(workers.map(acquire, pins['files'].items()))
    for file in files:
        shutil.copy2(file, build / file.name)
    header = build / 'openvr_driver.h'
    with urllib.request.urlopen(SDK_URL, timeout=30) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise RuntimeError('SDK header exceeds the bounded download size')
    header.write_bytes(data)
    if runner.sha(header) != SDK_HASH:
        raise RuntimeError('Pinned OpenVR SDK header hash mismatch')
    shutil.copy2(HERE / 'autotest_protocol.h', build / 'autotest_protocol.h')
    device = build / 'csampledevicedriver.cpp'
    text = device.read_text(encoding='utf-8-sig')
    text = '#include "autotest_protocol.h"\n' + text
    text = replace_function(text, 'vr::DriverPose_t CSampleDeviceDriver::GetPose()', 'return autotest::Pose(0);')
    device.write_text(text, encoding='utf-8')
    controller = build / 'csamplecontrollerdriver.cpp'
    text = '#include "autotest_protocol.h"\n' + controller.read_text(encoding='utf-8-sig')
    text = text.replace('m_ulPropertyContainer = vr::k_ulInvalidPropertyContainer;',
                        'm_ulPropertyContainer = vr::k_ulInvalidPropertyContainer;\n    for (auto &h:HButtons) h=0;\n    for (auto &h:HAnalog) h=0;\n    m_compHaptic=0;')
    # The upstream ZIP omits its referenced profile. Reuse the installed SteamVR
    # Vive profile, matching the device's advertised controller_type.
    text = text.replace('{null}/input/mycontroller_profile.json', '{htc}/input/vive_controller_profile.json')
    text = re.sub(r'^\s*vr::VRDriverInput\(\)->CreateBooleanComponent\([^\n]*"/input/trigger/value"[^\n]*\);', '', text, flags=re.MULTILINE)
    text = text.replace('// Analog handles', 'vr::VRProperties()->SetInt32Property(m_ulPropertyContainer, vr::Prop_Axis1Type_Int32, vr::k_eControllerAxis_Trigger);', 1)
    text = replace_function(text, 'vr::DriverPose_t CSampleControllerDriver::GetPose()', 'return autotest::Pose(ControllerIndex);')
    body = '''auto frame=autotest::Read();
auto &d=frame.devices[ControllerIndex];
const int bits[15]={0,1,2,3,4,5,6,7,-1,-1,-1,33,-1,32,32};
for (int i=0; i<15; ++i) {
    if (i==12) continue; // trigger scalar has a separate handle
    bool pressed=bits[i]>=0 && ((i==14 ? d.touched : d.pressed) & (1ULL << bits[i]));
    if (HButtons[i]) vr::VRDriverInput()->UpdateBooleanComponent(HButtons[i], pressed, 0);
}
vr::VRDriverInput()->UpdateScalarComponent(HAnalog[0], (float)d.axes[0], 0);
vr::VRDriverInput()->UpdateScalarComponent(HAnalog[1], (float)d.axes[1], 0);
vr::VRDriverInput()->UpdateScalarComponent(HAnalog[2], (float)d.axes[2], 0);
if (m_unObjectId != vr::k_unTrackedDeviceIndexInvalid)
    vr::VRServerDriverHost()->TrackedDevicePoseUpdated(m_unObjectId, GetPose(), sizeof(vr::DriverPose_t));'''
    text = replace_function(text, 'void CSampleControllerDriver::RunFrame()', body)
    controller.write_text(text, encoding='utf-8')
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    vs = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip()
    if not vs:
        raise RuntimeError('Visual Studio MSVC desktop component is not installed')
    files = sorted(build.glob('*.cpp'))
    command = ['cl.exe', '/nologo', '/std:c++17', '/EHsc', '/O2', '/LD', '/DWIN32', '/D_WINDOWS', '/I' + str(build),
               *[str(p) for p in files], '/link', '/OUT:' + str(build / 'driver_null.dll'), 'user32.lib']
    batch = build / 'build.cmd'
    batch.write_text('@echo off\ncall "' + vs + '\\Common7\\Tools\\VsDevCmd.bat" -arch=amd64 -host_arch=amd64 >nul\nif errorlevel 1 exit /b 1\n' + subprocess.list2cmdline(command) + '\n', encoding='utf-8')
    with (build / 'build.log').open('w', encoding='utf-8') as output:
        subprocess.run(['cmd.exe', '/d', '/c', str(batch)], cwd=build, check=True, stdout=output, stderr=subprocess.STDOUT, timeout=300)
    manifest = {'source': URL, 'commit': COMMIT, 'sdkHeader': SDK_URL, 'sdkHeaderSha256': runner.sha(header),
                'sourceFileHashes': pins['files'], 'sourceCatalogueSha256': runner.sha(HERE / 'driver_sources.json'),
                'ownProtocolSha256': runner.sha(HERE / 'autotest_protocol.h'), 'buildScriptSha256': runner.sha(Path(__file__)),
                'dllSha256': runner.sha(build / 'driver_null.dll'), 'visualStudio': vs}
    runner.atomic_json(build / 'manifest.json', manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
