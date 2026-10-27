// Read the actual fixed game-VFS configuration; never echo requested config.
#include "FixtureConfig.h"
#include "ToolRegistry.h"
#include "MainThread.h"
#include <filesystem>
#include <fstream>
namespace dvb::FixtureConfig {
void Register(ToolRegistry& registry) {
    ToolDescriptor descriptor;descriptor.name="fixture_config";descriptor.readOnly=true;
    descriptor.description="Bounded raw read of the fixed OBody distribution file through the current game VFS; no config writes/in-memory-state claim";
    descriptor.inputSchema={{"type","object"},{"properties",{{"action",{{"const","obody"}}},{"timeoutMs",{{"type","integer"}}}}}};
    registry.Register(std::move(descriptor),[](const json& args,const ToolContext&)->json {
        for(const auto& [key,unused]:args.items())if(key!="action"&&key!="timeoutMs")throw ToolError(400,"Unknown config read field");
        if(args.at("action")!="obody")throw ToolError(400,"Fixed OBody config action required");
        const auto ms=args.value("timeoutMs",3000);if(ms<1||ms>3000)throw ToolError(400,"Config timeout outside1..3000");
        return MainThread::RunAndWait([]()->json {
            std::wstring executable(32768,L'\0');const auto length=GetModuleFileNameW(nullptr,executable.data(),static_cast<DWORD>(executable.size()));
            if(!length||length>=executable.size())throw ToolError(503,"Actual game executable path unavailable");executable.resize(length);
            const auto path=std::filesystem::path(executable).parent_path()/"Data/SKSE/Plugins/OBody_presetDistributionConfig.json";
            std::ifstream input(path,std::ios::binary);if(!input)throw ToolError(404,"Actual game-VFS OBody config unavailable");
            std::string raw(1024*1024+1,'\0');input.read(raw.data(),static_cast<std::streamsize>(raw.size()));
            const auto n=input.gcount();if(n<1||n>1024*1024)throw ToolError(422,"Config empty or exceeds1MiB");raw.resize(static_cast<std::size_t>(n));
            (void)json::parse(raw);
            return json{{"pid",GetCurrentProcessId()},{"path",path.string()},{"rawText",raw},{"bytes",raw.size()},
                {"inMemoryConfigObserved",false},{"basis","actual fixed game-VFS file bytes; startup pins/lifecycle and actual generation establish use separately"}};
        },std::chrono::milliseconds(ms));
    });
}
}
