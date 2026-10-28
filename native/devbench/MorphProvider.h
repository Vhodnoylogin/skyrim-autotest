// Authored integration; official OBody/SKEE ABI headers are acquired externally.
#pragma once
#include <cstdint>
#include <string_view>

namespace dvb {
class ToolRegistry;
namespace MorphProvider {
// Call Register once with the host's registry, and forward every SKSE message
// type to OnSKSEMessage. The provider never opens a listener of its own.
void Register(ToolRegistry&);
void OnSKSEMessage(std::uint32_t type);

namespace Policy {
// External platforms retain six by default; an explicit twelve-ref manual
// group opt-in can use the same provider without changing the six-ref save ABI.
inline constexpr std::size_t MaxCommands = 512, MaxActorsPerWorld = 12;
inline constexpr std::size_t MaxCatalogPage = 256, MaxPresetBytes = 512;
inline constexpr bool Token(std::string_view text) {
    return text.size() == 32 && text.find_first_not_of("0123456789abcdef") == std::string_view::npos;
}
inline constexpr bool Name(std::string_view text) {
    if (text.empty() || text.size() > 128) return false;
    for (const auto ch : text) if (ch < 0x21 || ch > 0x7e) return false;
    return true;
}
// Domain adapters additionally pin their exact fixture keys. This provider only
// admits explicit test namespaces, never an arbitrary provider ownership key.
inline constexpr bool FixtureKey(std::string_view key) {
    return Name(key) && key.find(".Test.") != key.npos &&
        key != "OBody" && key != "ORefit" && key != "CLAW.Distribution";
}
}
}
}
