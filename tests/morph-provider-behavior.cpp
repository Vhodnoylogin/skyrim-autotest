// Offline behavioral harness: compile with the acquired DevBench src, official
// provider-api directory and nlohmann include roots. No game/plugin is loaded.
#include <atomic>
#include <chrono>
#include <cstdint>
#include <format>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
#include <IPluginInterface.h>
#include <OBodyAPI.h>
#include "ToolRegistry.h"
#include "MainThread.h"

namespace fake {
inline std::function<bool(std::uint32_t, void*, std::uint32_t, const char*)> dispatch;
inline int timeoutMode{}, frame{100}, assertions{};
void Check(bool condition, const char* message) {
    ++assertions;
    if (!condition) throw std::runtime_error(message);
}
}
inline std::uint32_t GetCurrentProcessId() { return 4242; }
namespace RE {
class NiAVObject {};
template<class T> class NiPointer {
    T* pointer{};
public:
    NiPointer() = default;
    explicit NiPointer(T* value) : pointer(value) {}
    T* get() const { return pointer; }
    explicit operator bool() const { return pointer != nullptr; }
};
class TESForm {
public:
    static inline std::map<std::uint32_t, TESForm*> forms;
    std::uint32_t id{};
    explicit TESForm(std::uint32_t value = 0) : id(value) { if (id) forms[id] = this; }
    virtual ~TESForm() = default;
    template<class T> T* As() { return dynamic_cast<T*>(this); }
    std::uint32_t GetFormID() const { return id; }
    static TESForm* LookupByID(std::uint32_t value) { auto it = forms.find(value); return it == forms.end() ? nullptr : it->second; }
};
class TESNPC : public TESForm { public: using TESForm::TESForm; };
class TESRace : public TESForm { public: using TESForm::TESForm; };
struct Handle { std::uint32_t value{}; std::uint32_t native_handle() const { return value; } };
class Actor : public TESForm {
public:
    TESNPC* base{};
    TESRace* race{};
    NiAVObject* root{};
    Handle handle{};
    bool deleted{};
    using TESForm::TESForm;
    TESNPC* GetActorBase() const { return base; }
    TESRace* GetRace() const { return race; }
    NiAVObject* Get3D(bool) const { return root; }
    void* GetParentCell() const { return root; }
    Handle GetHandle() const { return handle; }
    bool IsDeleted() const { return deleted; }
};
class PlayerCharacter : public Actor {
public:
    using Actor::Actor;
    static inline PlayerCharacter* player{};
    static PlayerCharacter* GetSingleton() { return player; }
};
class MainMenu { public: static constexpr auto MENU_NAME = "MainMenu"; };
class LoadingMenu { public: static constexpr auto MENU_NAME = "LoadingMenu"; };
class UI {
public:
    static inline bool blocked{};
    static UI* GetSingleton() { static UI ui; return &ui; }
    bool IsMenuOpen(std::string_view) const { return blocked; }
};
}
namespace SKSE {
class MessagingInterface {
public:
    enum : std::uint32_t { kPostPostLoad = 1, kPreLoadGame = 2, kNewGame = 3, kPostLoadGame = 4 };
    bool Dispatch(std::uint32_t type, void* data, std::uint32_t size, const char* target) const {
        return fake::dispatch && fake::dispatch(type, data, size, target);
    }
};
inline const MessagingInterface* GetMessagingInterface() { static MessagingInterface value; return &value; }
}
namespace dvb {
bool ToolRegistry::Register(ToolDescriptor, ToolHandler) { return true; }
namespace MainThread {
json RunAndWait(std::function<json()> fn, std::chrono::milliseconds, const std::atomic<bool>*) {
    if (fake::timeoutMode == 1) throw TaskTimeout(false, "offline queued timeout");
    const auto result = fn();
    if (fake::timeoutMode == 2) throw TaskTimeout(true, "offline response timeout after return");
    return result;
}
}
namespace game { int CurrentFrame() { return fake::frame; } }
}

// Include the implementation itself so every test executes the production
// validator, queue reservation, guard and provider dispatch, not a reimplementation.
#include "../native/devbench/MorphProvider.cpp"

namespace fake {
class Skee final : public IBodyMorphInterface {
public:
    std::map<std::string, std::map<std::string, float>> morphs;
    int clearAllCalls{}, clearKeyCalls{}, updateCalls{};
    skee_u32 GetVersion() override { return 5; }
    void Revert() override { ++clearAllCalls; }
    void SetMorph(::TESObjectREFR*, const char* name, const char* key, float value) override { morphs[name][key] = value; }
    float GetMorph(::TESObjectREFR*, const char* name, const char* key) override { return morphs[name][key]; }
    void ClearMorph(::TESObjectREFR*, const char* name, const char* key) override { morphs[name].erase(key); }
    float GetBodyMorphs(::TESObjectREFR*, const char*) override { return 0.f; }
    void ClearBodyMorphNames(::TESObjectREFR*, const char*) override { ++clearAllCalls; }
    void VisitMorphs(::TESObjectREFR*, MorphVisitor&) override {}
    void VisitKeys(::TESObjectREFR*, const char*, MorphKeyVisitor&) override {}
    void VisitMorphValues(::TESObjectREFR*, MorphValueVisitor&) override {}
    void ClearMorphs(::TESObjectREFR*) override { ++clearAllCalls; }
    void ApplyVertexDiff(::TESObjectREFR*, ::NiAVObject*, bool) override {}
    void ApplyBodyMorphs(::TESObjectREFR*, bool) override {}
    void UpdateModelWeight(::TESObjectREFR*, bool) override { ++updateCalls; }
    void SetCacheLimit(skee_u64) override {}
    bool HasMorphs(::TESObjectREFR*) override { return !morphs.empty(); }
    skee_u32 EvaluateBodyMorphs(::TESObjectREFR*) override { return 0; }
    bool HasBodyMorph(::TESObjectREFR*, const char* name, const char* key) override { return morphs[name].contains(key); }
    bool HasBodyMorphName(::TESObjectREFR*, const char* name) override { return morphs.contains(name); }
    bool HasBodyMorphKey(::TESObjectREFR*, const char*) override { return false; }
    void ClearBodyMorphKeys(::TESObjectREFR*, const char* key) override { ++clearKeyCalls; for (auto& [name, values] : morphs) values.erase(key); }
    void VisitStrings(StringVisitor&) override {}
    void VisitActors(ActorVisitor&) override {}
    skee_u64 ClearMorphCache() override { ++clearAllCalls; return 0; }
    void AddMorphShapeCallback(MorphShapeCallback, skee_u64) override {}
} skee;
class FakeOBody final : public OBody::API::IPluginInterface {
public:
    int assignCalls{}, resetCalls{}, ensureCalls{}, applyCalls{};
    std::string assigned;
    OBody::API::IOBodyReadinessEventListener* readiness{};
    OBody::API::PluginAPIVersion PluginAPIVersion() override { return OBody::API::PluginAPIVersion::v1; }
    const char* SetOwner(const char* value) override { return owner = value; }
    bool ActorIsNaked(::Actor*) override { return true; }
    bool ActorIsNaked(::Actor*, bool, const ::TESForm*) override { return true; }
    bool ActorHasORefitApplied(::Actor*) override { return false; }
    bool ActorIsProcessed(::Actor*) override { return !assigned.empty(); }
    bool ActorIsBlacklisted(::Actor*) override { return false; }
    bool IsORefitEnabled() override { return false; }
    bool RegisterEventListener(OBody::API::IActorChangeEventListener&) override { return true; }
    bool DeregisterEventListener(OBody::API::IActorChangeEventListener&) override { return false; }
    bool HasRegisteredEventListener(OBody::API::IActorChangeEventListener&) override { return false; }
    void GetPresetCounts(OBody::API::PresetCounts& counts) override { counts = {2, 1, 2, 0}; }
    std::size_t GetPresetNames(OBody::API::PresetCategory, std::string_view* buffer, std::size_t length, std::size_t offset, std::size_t limit) override {
        static constexpr std::array names{"Thin", "Wide"};
        std::size_t written{};
        while (written < length && written < limit && offset + written < names.size()) { buffer[written] = names[offset + written]; ++written; }
        return written;
    }
    void EnsureActorIsProcessed(::Actor*) override { ++ensureCalls; }
    void ApplyOBodyMorphsToActor(::Actor*) override { ++applyCalls; }
    void RemoveOBodyMorphsFromActor(::Actor*) override { ++resetCalls; skee.morphs["MuscleArms"].erase("OBody"); }
    void ForcefullyChangeORefitForActor(::Actor*, bool) override {}
    void GetPresetAssignedToActor(::Actor*, OBody::API::PresetAssignmentInformation& info) override { info.flags = OBody::API::PresetAssignmentInformation::None; info.presetName = assigned; }
    bool AssignPresetToActor(::Actor*, OBody::API::AssignPresetPayload& payload) override {
        ++assignCalls;
        Check(payload.flags == OBody::API::AssignPresetPayload::ForceImmediateApplicationOfMorphs, "assignment flag changed");
        if (!payload.presetName.empty() && payload.presetName != "Thin" && payload.presetName != "Wide") return false;
        assigned = payload.presetName;
        if (assigned.empty()) skee.morphs["MuscleArms"].erase("OBody");
        else skee.morphs["MuscleArms"]["OBody"] = .4f;
        return true;
    }
} obody;
class Interfaces final : public IInterfaceMap {
public:
    IPluginInterface* QueryInterface(const char* name) override { return std::string_view(name) == "BodyMorph" ? &skee : nullptr; }
    bool AddInterface(const char*, IPluginInterface*) override { return false; }
    IPluginInterface* RemoveInterface(const char*) override { return nullptr; }
} interfaces;
using dvb::json;
json Call(json args) { return dvb::MorphProvider::Handle(args, {}); }
template<class Function> void Refuses(Function fn, const char* message) {
    try { fn(); } catch (const dvb::ToolError&) { ++assertions; return; }
    throw std::runtime_error(message);
}
int nextCommand{};
json Mutation(std::string action, const json& guard) {
    return {{"action", action}, {"actorFormId", guard.at("actorFormId")}, {"guard", guard},
        {"owner", std::string(32, 'a')}, {"command", std::format("{:032x}", ++nextCommand)}};
}
json Status(const json& args) { return Call({{"action", "action_status"}, {"owner", args.at("owner")}, {"command", args.at("command")}}).at("receipt"); }
}
int main() {
    using namespace fake;
    try {
        RE::TESNPC base(0x123); RE::TESRace race(0x456); RE::NiAVObject root, replacement;
        RE::PlayerCharacter player(0x14); player.base = &base; player.race = &race; player.root = &root; player.handle.value = 1;
        RE::PlayerCharacter::player = &player;
        RE::Actor actor(0xff000001); actor.base = &base; actor.race = &race; actor.root = &root; actor.handle.value = 7;
        dispatch = [](std::uint32_t type, void* data, std::uint32_t, const char* target) {
            if (std::string_view(target) == "OBody") {
                auto& request = *static_cast<::OBody::API::SKSEMessages::RequestPluginInterface*>(data);
                Check(request.version == ::OBody::API::PluginAPIVersion::v1, "API request not pinned to v1");
                *request.pluginInterface = &obody; obody.readiness = request.readinessEventListener;
                obody.readiness->OBodyIsBecomingReady(); obody.readiness->OBodyIsReady(); return true;
            }
            if (type == InterfaceExchangeMessage::kMessage_ExchangeInterface) {
                static_cast<InterfaceExchangeMessage*>(data)->interfaceMap = &interfaces; return true;
            }
            return false;
        };
        dvb::MorphProvider::OnSKSEMessage(SKSE::MessagingInterface::kPostPostLoad);
        dvb::MorphProvider::OnSKSEMessage(SKSE::MessagingInterface::kNewGame);
        auto caps = Call({{"action", "capabilities"}});
        Check(caps["obody"]["ready"] && caps["skee"]["available"], "interfaces unavailable");
        Check(Call({{"action", "catalog"}, {"category", "female"}, {"offset", 1}, {"limit", 1}})["names"] == json::array({"Wide"}), "catalog paging wrong");
        Refuses([] { Call({{"action", "catalog"}, {"category", "female"}, {"limit", 257}}); }, "oversized catalog accepted");
        auto guard = Call({{"action", "actor_status"}, {"actorFormId", "0xFF000001"}})["identity"];
        auto assign = Mutation("assign_preset", guard); assign["presetName"] = "Thin";
        Check(Call(assign)["status"] == "call_returned" && obody.assignCalls == 1 && obody.assigned == "Thin", "native assignment not called once");
        Refuses([&] { Call(assign); }, "replayed assignment accepted");
        Check(obody.assignCalls == 1 && Status(assign)["completion"] == "unobserved", "receipt falsely completes or replays");
        auto stale = Mutation("reset_provider_morphs", guard); stale["guard"]["runtimeHandle"] = 8;
        Refuses([&] { Call(stale); }, "stale actor handle accepted");
        Check(Status(stale)["status"] == "rejected_before_call" && obody.resetCalls == 0, "rejected guard called provider");
        auto wrongBase = Mutation("reset_provider_morphs", guard); wrongBase["guard"]["baseFormId"] = "0x00000999";
        Refuses([&] { Call(wrongBase); }, "stale actor base accepted");
        actor.root = &replacement;
        Refuses([&] { Call(Mutation("reset_provider_morphs", guard)); }, "stale model accepted");
        actor.root = &root;
        guard = Call({{"action", "actor_status"}, {"actorFormId", "0xFF000001"}})["identity"];
        obody.readiness->OBodyIsBecomingUnready();
        Refuses([&] { Call(Mutation("reset_provider_morphs", guard)); }, "unready provider accepted");
        obody.readiness->OBodyIsReady();
        skee.morphs["MuscleArms"]["Unrelated.Owner"] = -.9f;
        auto fixture = Mutation("set_test_morphs", guard);
        fixture["values"] = json::array({{{"morph", "MuscleArms"}, {"key", "CLAW.Test.ForeignHuman.20261027"}, {"value", -.875}},
            {{"morph", "ChestDepth"}, {"key", "CLAW.Test.ZeroHuman.20261027"}, {"value", 0.0}},
            {{"morph", "CLAWTailLength"}, {"key", "CLAW.Test.ForeignWolf.20261027"}, {"value", .125}}});
        Call(fixture);
        Check(skee.morphs["ChestDepth"].contains("CLAW.Test.ZeroHuman.20261027"), "existing zero was discarded by adapter");
        auto bad = Mutation("set_test_morphs", guard); bad["values"] = json::array({{{"morph", "MuscleArms"}, {"key", "OBody"}, {"value", 0}}});
        Refuses([&] { Call(bad); }, "foreign fixture key accepted");
        auto fourthKey = Mutation("set_test_morphs", guard); fourthKey["values"] = json::array({{{"morph", "ChestDepth"}, {"key", "Another.Test.Key"}, {"value", .1}}});
        Refuses([&] { Call(fourthKey); }, "fourth distinct test key admitted");
        Check(!skee.morphs["ChestDepth"].contains("Another.Test.Key"), "rejected test key was written");
        auto duplicateKey = Mutation("set_test_morphs", guard); duplicateKey["values"] = json::array({fixture["values"][0], fixture["values"][0]});
        Refuses([&] { Call(duplicateKey); }, "duplicate test key admitted");
        auto excessiveValue = Mutation("set_test_morphs", guard); excessiveValue["values"] = json::array({fixture["values"][0]}); excessiveValue["values"][0]["value"] = 2.1;
        Refuses([&] { Call(excessiveValue); }, "unbounded test coefficient admitted");
        auto foreignRemoval = Mutation("remove_test_keys", guard); foreignRemoval["keys"] = json::array({"Unrelated.Owner"});
        Refuses([&] { Call(foreignRemoval); }, "foreign removal admitted");
        const auto beforeRead = obody.assignCalls + obody.resetCalls;
        Call({{"action", "actor_status"}, {"actorFormId", "0xFF000001"}});
        Call({{"action", "catalog"}, {"category", "male"}});
        Check(beforeRead == obody.assignCalls + obody.resetCalls, "read-only provider action mutated OBody");
        auto reset = Call(Mutation("reset_provider_morphs", guard));
        Check(obody.resetCalls == 1 && obody.assigned == "Thin" && !skee.morphs["MuscleArms"].contains("OBody"), "reset API or assignment retention wrong");
        Check(skee.morphs["MuscleArms"].contains("Unrelated.Owner") && skee.morphs["MuscleArms"].contains("CLAW.Test.ForeignHuman.20261027"), "reset adapter cleared nonprovider keys");
        auto remove = Mutation("remove_test_keys", guard); remove["keys"] = json::array({"CLAW.Test.ForeignHuman.20261027", "CLAW.Test.ZeroHuman.20261027", "CLAW.Test.ForeignWolf.20261027"});
        Call(remove);
        Check(skee.clearKeyCalls == 3 && skee.clearAllCalls == 0 && skee.morphs["MuscleArms"]["Unrelated.Owner"] == -.9f, "fixture cleanup cleared foreign morphs");
        auto unassign = Call(Mutation("unassign_preset", guard));
        Check(unassign["providerAccepted"] && obody.assigned.empty(), "unassign did not use empty native assignment");
        auto missing = Mutation("assign_preset", guard); missing["presetName"] = "missing";
        Check(!Call(missing)["providerAccepted"], "unknown preset became accepted");
        auto queued = Mutation("reset_provider_morphs", guard); timeoutMode = 1;
        Refuses([&] { Call(queued); }, "queued timeout missing"); timeoutMode = 0;
        Check(Status(queued)["status"] == "abandoned_before_start", "queued timeout did not retain non-replay receipt");
        Refuses([&] { Call(queued); }, "abandoned command replayable");
        auto returned = Mutation("reset_provider_morphs", guard); timeoutMode = 2;
        Refuses([&] { Call(returned); }, "started timeout missing"); timeoutMode = 0;
        Check(Status(returned)["status"] == "call_returned" && Status(returned)["transportTimedOut"], "response timeout overwrote actual receipt");
        dvb::MorphProvider::OnSKSEMessage(SKSE::MessagingInterface::kPreLoadGame);
        Refuses([&] { Call(Mutation("reset_provider_morphs", guard)); }, "loading world accepted");
        dvb::MorphProvider::OnSKSEMessage(SKSE::MessagingInterface::kPostLoadGame);
        Refuses([&] { Call(Mutation("reset_provider_morphs", guard)); }, "old world guard accepted");
        Check(obody.ensureCalls == 0 && obody.applyCalls == 0, "adapter forced automatic generation");
        Check(Status(assign)["status"] == "call_returned", "world load lost mutation receipts");
        auto currentGuard = Call({{"action", "actor_status"}, {"actorFormId", "0xFF000001"}})["identity"];
        Call(Mutation("reset_provider_morphs", currentGuard));
        std::vector<std::unique_ptr<RE::Actor>> extraActors;
        for (int index = 0; index < 6; ++index) {
            auto extra = std::make_unique<RE::Actor>(0xff000010 + index);
            extra->base = &base; extra->race = &race; extra->root = &root; extra->handle.value = 20 + index;
            const auto extraGuard = Call({{"action", "actor_status"}, {"actorFormId", std::format("0x{:08X}", extra->GetFormID())}})["identity"];
            if (index < 5) Call(Mutation("reset_provider_morphs", extraGuard));
            else Refuses([&] { Call(Mutation("reset_provider_morphs", extraGuard)); }, "seventh distinct actor admitted");
            extraActors.push_back(std::move(extra));
        }
        std::cout << "morph-provider offline behavioral assertions passed: " << assertions << '\n';
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
