#pragma once
#include <cstdint>
namespace dvb { class ToolRegistry; namespace NPCPersistence {
void Initialize();
void Register(ToolRegistry&);
void OnSKSEMessage(std::uint32_t);
} }
