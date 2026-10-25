"""Apply narrow owned compatibility corrections to exact external DevBench 1.32.

Third-party source and acquired owned-fork payloads remain outside this repository.
No deployment, game launch, branch update or installation is performed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = '938c392d5e0fc19260c65f689ff4a80fbec4007c'
COMMONLIB_COMMIT = 'abe9ca7b7318dbc04bccfcd59fc3fb670244c2d7'
OWNED_COMMIT = '0d8caaec64ff4cfc904c1ff5914533c295003119'
OWNED_BASE = 'https://raw.githubusercontent.com/Vhodnoylogin/devbench/' + OWNED_COMMIT
BASE_SHA256 = {
    'src/Tools.cpp': '5298c963d0ef6f7da5167bc04c3339589b8d34e59807cfb13d61a399640bb599',
    'src/ToolRegistry.cpp': '1eaaabed9f81a67a3dfab7e97b83191c2e107dfbf601a728afca3762b1f35e9e',
    'xmake.lua': '358d7461c3ffed09d233b683033525fee038d9e963f599ba8be32b0566a83345',
    'lib/commonlibsse-ng/src/RE/T/TypeInfo.cpp': 'a3766c4636da466eb416af393a89ea124ffc235c742c904d55fb62eca4d3f74d',
}
OWNED_PAYLOADS = {
    'src/TextEncoding.h': 'fe6411b9bbe3a26d462fad9bf7a517067d790d59e62ab97588640ba3af23ebae',
    'tests/TextEncoding_test.cpp': 'e8d7672830d16a5b71cce67de0b24a1fd614362a9b1315a173f291e6456dd57e',
}

# This helper is ours; unavailable menu objects keep their flags absent rather
# than manufacturing a permissive all-false observation.
MENU_STATE_HEADER = r'''#pragma once
#include "Json.h"
#include <string>
namespace dvb {
template<class Menu> inline json CurrentMenuState(const std::string& name, Menu* menu)
{
    json state{{"name", name}, {"available", menu != nullptr}};
    if (menu) state.update(json{
        {"alwaysOpen", menu->AlwaysOpen()}, {"pausesGame", menu->PausesGame()},
        {"modal", menu->Modal()}, {"usesCursor", menu->UsesCursor()},
        {"usesMenuContext", menu->UsesMenuContext()}, {"freezeFramePause", menu->FreezeFramePause()}});
    return state;
}
}
'''
MENU_STATE_TEST = r'''#include "test_framework.h"
#include "CurrentMenuState.h"
namespace {
struct Menu {
    bool a, p, m, c, x, f;
    bool AlwaysOpen() const { return a; }
    bool PausesGame() const { return p; }
    bool Modal() const { return m; }
    bool UsesCursor() const { return c; }
    bool UsesMenuContext() const { return x; }
    bool FreezeFramePause() const { return f; }
};
}
TEST_CASE("current menu state keeps missing objects explicitly unavailable")
{
    auto state = dvb::CurrentMenuState("Unknown", static_cast<Menu*>(nullptr));
    CHECK(state == dvb::json({{"name", "Unknown"}, {"available", false}}));
}
TEST_CASE("current menu state preserves every independent engine flag")
{
    for (unsigned int mask = 0; mask < 64; ++mask) {
        Menu menu{bool(mask&1), bool(mask&2), bool(mask&4), bool(mask&8), bool(mask&16), bool(mask&32)};
        auto state = dvb::CurrentMenuState("Overlay", &menu);
        CHECK(state["available"] == true);
        CHECK(state["alwaysOpen"] == menu.a);
        CHECK(state["pausesGame"] == menu.p);
        CHECK(state["modal"] == menu.m);
        CHECK(state["usesCursor"] == menu.c);
        CHECK(state["usesMenuContext"] == menu.x);
        CHECK(state["freezeFramePause"] == menu.f);
        CHECK(dvb::json::parse(state.dump()) == state);
    }
}
'''
MENU_HANDLER_INSERT = '''
				if (a_args.value("includeFlags", false)) {
					return MainThread::RunAndWait([]() -> json {
						json open = json::array(), states = json::array();
						bool messageBox = false;
						auto* ui = RE::UI::GetSingleton();
						for (const auto& name : GetOpenMenus()) {
							open.push_back(name);
							messageBox |= name == RE::MessageBoxMenu::MENU_NAME;
							json state{{ "name", name }, { "available", false }};
							if (ui) {
								const auto menu = ui->GetMenu(name);
								state = CurrentMenuState(name, menu.get());
							}
							states.push_back(std::move(state));
						}
						return json{{ "openMenus", std::move(open) }, { "menuStates", std::move(states) },
							{ "messageBoxOpen", messageBox }, { "registered", ToolExtensions::Keys("menu") }};
					}, std::chrono::milliseconds(5000));
				}'''
PROBE_TARGET = '''
target("devbench-typeinfo-regression")
set_kind("binary")
set_default(false)
add_deps("commonlibsse-ng")
add_files("typeinfo-regression.cpp")
add_defines("_WINSOCKAPI_")
target_end()
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(data):
    return data.replace(b'\r\n', b'\n')


def external_source(path):
    source = Path(path).resolve()
    if source == ROOT or ROOT in source.parents or any((p / '.git').exists() for p in source.parents):
        raise ValueError('Source must be an independent external checkout, outside every parent Git repository')
    return source


def acquire_payloads(directory):
    cache = Path(directory).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    payloads = {}
    for relative, expected in OWNED_PAYLOADS.items():
        target = cache / Path(relative).name
        if target.exists():
            data = target.read_bytes()
        else:
            with urllib.request.urlopen(OWNED_BASE + '/' + relative, timeout=60) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if digest(data) != expected:
                raise ValueError('Owned source acquisition digest mismatch: ' + relative)
            target.write_bytes(data)
        if digest(data) != expected:
            raise ValueError('Owned cached source digest mismatch: ' + relative)
        payloads[relative] = data
    return payloads


def replace_once(text, before, after, label):
    if text.count(before) != 1:
        raise ValueError('Exact patch anchor mismatch: ' + label)
    return text.replace(before, after, 1)


def prepare(source, payloads):
    """Validate every preimage before producing an in-memory, non-mutating patch plan."""
    source = external_source(source)
    inputs = {}
    for relative, expected in BASE_SHA256.items():
        target = source / relative
        if not target.resolve().is_relative_to(source) or target.is_symlink():
            raise ValueError('Source target escapes external checkout: ' + relative)
        data = normalized(target.read_bytes())
        if digest(data) != expected:
            raise ValueError('Pinned source digest mismatch: ' + relative)
        inputs[relative] = data
    for relative, expected in OWNED_PAYLOADS.items():
        if relative not in payloads or digest(payloads[relative]) != expected:
            raise ValueError('Owned correction digest mismatch: ' + relative)
    outputs = dict(inputs)
    tools = inputs['src/Tools.cpp'].decode('utf-8')
    tools = replace_once(tools, '#include "Tools.h"', '#include "Tools.h"\n#include "CurrentMenuState.h"', 'menu helper include')
    anchor = '\t\t\tif (action == "list") {\n\t\t\t\tjson open = json::array();'
    tools = replace_once(tools, anchor, '\t\t\tif (action == "list") {' + MENU_HANDLER_INSERT + '\n\t\t\t\tjson open = json::array();', 'menu flag read')
    anchor = '\t\t\tmenu.inputSchema = json{'
    tools = replace_once(tools, anchor,
                         '\t\t\tmenu.description += " list with includeFlags=true reads menuStates with availability and native flags on the game thread; unavailable flags stay absent.";\n' + anchor,
                         'menu discovery description')
    anchor = '{ "index", json{ { "type", "integer" }, { "description", "accept: 0-based button index to select (default 0). See describe\'s buttons/cancelIndex." } } },'
    tools = replace_once(tools, anchor, anchor + '\n\t\t\t\t\t\t\t\t\t{ "includeFlags", json{ { "type", "boolean" }, { "description", "list: read native menu states on the main thread (default false)." } } },', 'menu discovery schema')
    outputs['src/Tools.cpp'] = tools.encode('utf-8')
    registry = inputs['src/ToolRegistry.cpp'].decode('utf-8')
    registry = replace_once(registry, '#include "ToolRegistry.h"', '#include "ToolRegistry.h"\n#include "TextEncoding.h"', 'UTF8 include')
    registry = replace_once(registry, 'ToolResult::Success(handler(a_args, a_ctx))',
                            'ToolResult::Success(NormalizeToolText(handler(a_args, a_ctx)))', 'shared UTF8 boundary')
    outputs['src/ToolRegistry.cpp'] = registry.encode('utf-8')
    array_file = 'lib/commonlibsse-ng/src/RE/T/TypeInfo.cpp'
    outputs[array_file] = replace_once(inputs[array_file].decode('utf-8'),
        '~std::to_underlying(RawType::kObjectArray)', '~std::to_underlying(RawType::kObject)', 'object array bit mask').encode('utf-8')
    outputs['xmake.lua'] += PROBE_TARGET.encode('utf-8')
    outputs.update(payloads)
    outputs['src/CurrentMenuState.h'] = MENU_STATE_HEADER.encode('utf-8')
    outputs['tests/CurrentMenuState_test.cpp'] = MENU_STATE_TEST.encode('utf-8')
    probe = ROOT / 'tools/native/typeinfo_array_probe.cpp'
    outputs['typeinfo-regression.cpp'] = probe.read_bytes()
    for relative in outputs.keys() - inputs.keys():
        target = source / relative
        if target.exists() or not target.resolve().is_relative_to(source):
            raise ValueError('Correction output already exists or escapes checkout: ' + relative)
    return inputs, outputs


def apply(source, payloads):
    source = external_source(source)
    inputs, outputs = prepare(source, payloads)
    changes = []
    for relative, data in outputs.items():
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        changes.append({'path': relative, 'originalSha256': digest(inputs[relative]) if relative in inputs else None,
                        'patchedSha256': digest(data)})
    return {'sourceCommit': SOURCE_COMMIT, 'commonlibCommit': COMMONLIB_COMMIT,
            'ownedTextCorrectionCommit': OWNED_COMMIT, 'changes': changes,
            'features': ['menu.includeFlags/menuStates', 'invalid-utf8-text-unavailable', 'object-array-bit0-decoder'],
            'installedFilesChanged': False, 'liveQualification': 'pending'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--acquisition-cache', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    source = external_source(args.source)
    result = apply(source, acquire_payloads(args.acquisition_cache))
    args.manifest.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'patchManifest': str(args.manifest.resolve())}))


if __name__ == '__main__':
    main()
