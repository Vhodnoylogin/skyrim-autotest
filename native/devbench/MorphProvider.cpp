// Authored for Skyrim Autotest; not part of the read-only World Observer.
#include "MorphProvider.h"
#include "ToolRegistry.h"
#include "MainThread.h"
#include "GameState.h"
#include <array>
#include <charconv>
#include <cmath>
#include <set>
#include <IPluginInterface.h>
#include <OBodyAPI.h>

namespace dvb::MorphProvider {
namespace {
// Process-lifetime borrowed interfaces/listener. Never delete, Revert or retain
// provider string_views after releasing the readiness gate.
std::recursive_mutex providerGate;
OBody::API::IPluginInterface* obody{};
IBodyMorphInterface* skee{};
bool initialized{}, obodyReady{}, worldLoading{true};
std::uint64_t providerEpoch{}, worldGeneration{1};
std::uint32_t skeeVersion{};
std::set<std::uint32_t> mutatedActors;
std::set<std::string> admittedTestKeys;
struct SampledModel {
    std::uint32_t handle{};
    std::uint64_t generation{}, token{};
    std::uintptr_t address{};  // Hidden sampled identity; never exported or dereferenced.
};
std::unordered_map<std::uint32_t, SampledModel> sampledModels;
std::uint64_t nextModelToken{};
std::mutex receiptsGate;
std::unordered_map<std::string, json> receipts;

class Readiness final : public OBody::API::IOBodyReadinessEventListener {
    void Set(bool ready) {
        std::lock_guard lock(providerGate);
        if (obodyReady != ready) ++providerEpoch;
        obodyReady = ready;
    }
public:
    void OBodyIsBecomingReady() override { Set(false); }
    void OBodyIsReady() override { Set(true); }
    // Stop new calls before OBody starts rearranging its storage. An in-flight
    // call owns this gate, so the invalidation callback cannot return early.
    void OBodyIsBecomingUnready() override { Set(false); }
    void OBodyIsNoLongerReady() override { Set(false); }
} readiness;

std::string Hex(std::uint32_t id) { return std::format("0x{:08X}", id); }
std::uint32_t FormID(const std::string& value) {
    auto text = std::string_view(value);
    if (text.starts_with("0x")) text.remove_prefix(2);
    std::uint32_t id{};
    const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), id, 16);
    if (text.empty() || text.size() > 8 || error != std::errc{} || end != text.data() + text.size() || !id)
        throw ToolError(400, "Exact nonzero 32-bit hexadecimal FormID required");
    return id;
}
std::string Text(std::string_view value, std::size_t bound, bool empty = false) {
    if ((!empty && value.empty()) || value.size() > bound || value.find('\0') != value.npos)
        throw ToolError(422, "Provider text is empty, oversized or contains a null byte");
    std::string copy(value);
    try { (void)json(copy).dump(); }
    catch (...) { throw ToolError(422, "Provider text is not valid UTF-8"); }
    return copy;
}
void ExactKeys(const json& value, const std::set<std::string>& allowed) {
    if (!value.is_object()) throw ToolError(400, "Object required");
    for (const auto& [key, unused] : value.items())
        if (!allowed.contains(key)) throw ToolError(400, "Unknown morph provider argument: " + key);
}
void RequireOBody() {
    if (!obody || !obodyReady) throw ToolError(409, "Official OBody v1 interface is not ready in this epoch");
}
void RequireSkee() {
    if (!skee || skeeVersion != 5) throw ToolError(409, "Official SKEE BodyMorph v5 interface unavailable");
}
json Stamp() {
    return {{"schemaVersion", 1}, {"protocol", "morph-provider/1"}, {"pid", GetCurrentProcessId()},
        {"worldGeneration", worldGeneration}, {"worldLoading", worldLoading}, {"frame", game::CurrentFrame()},
        {"phase", "skse_main_thread_task"}};
}
void WorldReady() {
    auto* player = RE::PlayerCharacter::GetSingleton();
    auto* ui = RE::UI::GetSingleton();
    if (worldLoading || !player || !player->Get3D(false) || !player->GetParentCell() || !ui ||
        ui->IsMenuOpen(RE::MainMenu::MENU_NAME) || ui->IsMenuOpen(RE::LoadingMenu::MENU_NAME))
        throw ToolError(409, "Loaded gameplay world required");
}
std::string ModelIdentity(RE::Actor* actor, const RE::NiAVObject* root) {
    const auto id = actor->GetFormID(), handle = actor->GetHandle().native_handle();
    const auto address = reinterpret_cast<std::uintptr_t>(root);
    const auto found = sampledModels.find(id);
    if (found == sampledModels.end() && sampledModels.size() >= 64)
        throw ToolError(409, "Sampled actor model identity bound64 reached in this world");
    auto& sampled = sampledModels[id];
    if (!sampled.token || sampled.handle != handle || sampled.generation != worldGeneration || sampled.address != address) {
        if (nextModelToken == UINT64_MAX) throw ToolError(409, "Sampled model identity token exhausted");
        sampled = {handle, worldGeneration, ++nextModelToken, address};
    }
    // Sampling cannot detect an unobserved destruction/reallocation at exactly
    // the same address/handle. Keep no root reference in this cache.
    return std::format("model:{:016X}", sampled.token);
}
struct ActorSnapshot {
    RE::Actor* actor{};
    RE::NiPointer<RE::Actor> retainedActor;
    RE::NiPointer<RE::NiAVObject> root;
    json identity;
    bool Current() const {
        auto* found = RE::TESForm::LookupByID(actor->GetFormID());
        return !worldLoading && found == actor && !actor->IsDeleted() && root && actor->Get3D(false) == root.get() &&
            actor->GetHandle().native_handle() == identity.at("runtimeHandle").get<std::uint32_t>() &&
            actor->GetActorBase() && Hex(actor->GetActorBase()->GetFormID()) == identity.at("baseFormId").get<std::string>() &&
            actor->GetRace() && Hex(actor->GetRace()->GetFormID()) == identity.at("raceFormId").get<std::string>() &&
            worldGeneration == identity.at("worldGeneration").get<std::uint64_t>();
    }
};
ActorSnapshot Actor(const std::string& value) {
    WorldReady();
    auto* form = RE::TESForm::LookupByID(FormID(value));
    auto* actor = form ? form->As<RE::Actor>() : nullptr;
    if (!actor || actor->IsDeleted() || !actor->GetActorBase() || !actor->GetRace() || !actor->Get3D(false) ||
        !actor->GetParentCell() || !actor->GetHandle().native_handle())
        throw ToolError(422, "Exact live actor/base/race/handle/model unavailable");
    ActorSnapshot out{actor, RE::NiPointer<RE::Actor>(actor), RE::NiPointer<RE::NiAVObject>(actor->Get3D(false)), {}};
    out.identity = {{"actorFormId", Hex(actor->GetFormID())}, {"baseFormId", Hex(actor->GetActorBase()->GetFormID())},
        {"raceFormId", Hex(actor->GetRace()->GetFormID())}, {"runtimeHandle", actor->GetHandle().native_handle()},
        {"modelIdentity", ModelIdentity(actor, out.root.get())},
        {"worldGeneration", worldGeneration}, {"pid", GetCurrentProcessId()}};
    return out;
}
void Guard(const ActorSnapshot& actor, const json& guard) {
    if (guard != actor.identity || !actor.Current())
        throw ToolError(409, "Actor/base/race/handle/model/process/world guard changed; no provider call");
    if ((actor.actor->GetFormID() >> 24) != 0xff || actor.actor == RE::PlayerCharacter::GetSingleton())
        throw ToolError(403, "Only exact disposable runtime-created NPC references may be mutated");
    if (!mutatedActors.contains(actor.actor->GetFormID()) && mutatedActors.size() >= Policy::MaxActorsPerWorld)
        throw ToolError(409, "Six disposable actor mutation limit reached in this world");
}
json Assignment(RE::Actor* actor) {
    RequireOBody();
    OBody::API::PresetAssignmentInformation value{};
    value.flags = OBody::API::PresetAssignmentInformation::Flags::None;
    obody->GetPresetAssignedToActor(reinterpret_cast<::Actor*>(actor), value);
    const auto name = Text(value.presetName, Policy::MaxPresetBytes, true);
    return {{"status", "available"}, {"presetName", name}, {"assigned", !name.empty()},
        {"flags", static_cast<std::uint64_t>(value.flags)}, {"providerEpoch", providerEpoch},
        {"processed", obody->ActorIsProcessed(reinterpret_cast<::Actor*>(actor))},
        {"blacklisted", obody->ActorIsBlacklisted(reinterpret_cast<::Actor*>(actor))},
        {"coherence", "sampled_assignment_not_morph_completion_or_automatic_origin"}};
}
json Capabilities() {
    auto out = Stamp();
    out["obody"] = {{"available", obody != nullptr}, {"ready", obodyReady}, {"apiVersion", 1},
        {"providerEpoch", providerEpoch}, {"assignment", true}, {"unassignment", true},
        {"reset", "RemoveOBodyMorphsFromActor_retains_assignment_and_per_actor_configuration"},
        {"catalog", "GetPresetCounts_and_GetPresetNames"}};
    out["skee"] = {{"available", skee != nullptr}, {"interfaceVersion", skeeVersion},
        {"testKeyPolicy", "printable_ASCII_max128_contains_.Test._exact_domain_allowlist_required"},
        {"admittedTestKeys", admittedTestKeys}, {"maxFixtureValues", 3}, {"maxDistinctTestKeysPerWorld", 3},
        {"coefficientRange", {-2.0, 2.0}}};
    out["limits"] = {{"maxCommandsPerProcess", Policy::MaxCommands}, {"maxMutatedActorsPerWorld", Policy::MaxActorsPerWorld},
        {"maxCatalogPage", Policy::MaxCatalogPage}, {"maxTimeoutMs", 5000}};
    out["providerCallReturnIsCompletion"] = false;
    out["modelIdentityBasis"] = "opaque_process_local_token_for_sampled_actor_handle_world_root_changes";
    out["unobservedRootAddressReuseDetectable"] = false;
    out["configurationRead"] = "external_staged_effective_file_evidence_required";
    out["automaticOriginRead"] = "independent_World_Observer_stock_event_witness_required";
    return out;
}
json Catalog(const json& args) {
    RequireOBody();
    const auto category = args.at("category").get<std::string>();
    OBody::API::PresetCategory selected{};
    if (category == "female") selected = OBody::API::PresetCategoryFemale;
    else if (category == "female_blacklisted") selected = OBody::API::PresetCategoryFemaleBlacklisted;
    else if (category == "male") selected = OBody::API::PresetCategoryMale;
    else if (category == "male_blacklisted") selected = OBody::API::PresetCategoryMaleBlacklisted;
    else throw ToolError(400, "Explicit single preset category required");
    const auto offset = args.value("offset", 0), limit = args.value("limit", 64);
    if (offset < 0 || offset > 65535 || limit < 1 || limit > Policy::MaxCatalogPage)
        throw ToolError(400, "Catalog offset outside0..65535 or page outside1..256");
    OBody::API::PresetCounts counts{};
    obody->GetPresetCounts(counts);
    std::array<std::string_view, Policy::MaxCatalogPage> buffer{};
    const auto written = obody->GetPresetNames(selected, buffer.data(), limit, offset, limit);
    if (written > static_cast<std::size_t>(limit)) throw ToolError(422, "OBody catalog exceeded supplied page capacity");
    json names = json::array();
    for (std::size_t i = 0; i < written; ++i) names.push_back(Text(buffer[i], Policy::MaxPresetBytes));
    auto out = Stamp();
    out.update({{"providerEpoch", providerEpoch}, {"category", category}, {"offset", offset}, {"limit", limit},
        {"names", names}, {"returnedCount", written}, {"counts", {{"female", counts.female},
            {"femaleBlacklisted", counts.femaleBlacklisted}, {"male", counts.male}, {"maleBlacklisted", counts.maleBlacklisted}}},
        {"coherence", "sampled_bounded_provider_catalog_not_configuration_or_actor_generation"}});
    return out;
}
void UpdateReceipt(const std::string& key, const json& fields) {
    std::lock_guard lock(receiptsGate);
    receipts.at(key).update(fields);
}
json Receipt(const std::string& key) {
    std::lock_guard lock(receiptsGate);
    const auto found = receipts.find(key);
    return found == receipts.end() ? json{{"status", "unknown"}} : found->second;
}
struct FixtureValue { std::string morph, key; float value; };
std::vector<FixtureValue> FixtureValues(const json& args) {
    const auto& values = args.at("values");
    if (!values.is_array() || values.empty() || values.size() > 3) throw ToolError(400, "One to three explicit fixture values required");
    std::set<std::string> seen;
    std::vector<FixtureValue> out;
    for (const auto& value : values) {
        ExactKeys(value, {"morph", "key", "value"});
        FixtureValue item{value.at("morph").get<std::string>(), value.at("key").get<std::string>(), value.at("value").get<float>()};
        if (!Policy::FixtureKey(item.key) || !Policy::Name(item.morph) || !seen.insert(item.key).second ||
            !std::isfinite(item.value) || item.value < -2.f || item.value > 2.f)
            throw ToolError(400, "Invalid test namespace/morph name, duplicate key or coefficient outside -2..2");
        out.push_back(std::move(item));
    }
    return out;
}
std::vector<std::string> FixtureKeys(const json& args) {
    const auto& values = args.at("keys");
    if (!values.is_array() || values.empty() || values.size() > 3) throw ToolError(400, "One to three owned fixture keys required");
    std::set<std::string> seen;
    std::vector<std::string> out;
    for (const auto& value : values) {
        const auto key = value.get<std::string>();
        if (!Policy::FixtureKey(key) || !seen.insert(key).second) throw ToolError(400, "Invalid or duplicate test namespace key");
        out.push_back(key);
    }
    return out;
}
bool Mutation(const std::string& action) {
    return action == "assign_preset" || action == "unassign_preset" || action == "reset_provider_morphs" ||
        action == "set_test_morphs" || action == "remove_test_keys";
}
json Mutate(const json& args, const std::string& action, const std::string& key) {
    bool called = false;
    try {
        std::lock_guard lock(providerGate);
        auto actor = Actor(args.at("actorFormId").get<std::string>());
        Guard(actor, args.at("guard"));
        std::vector<FixtureValue> values;
        std::vector<std::string> keys;
        std::string preset;
        if (action == "set_test_morphs") { RequireSkee(); values = FixtureValues(args); }
        else if (action == "remove_test_keys") { RequireSkee(); keys = FixtureKeys(args); }
        else {
            RequireOBody();
            if (action == "assign_preset") preset = Text(args.at("presetName").get<std::string>(), Policy::MaxPresetBytes);
        }
        Guard(actor, args.at("guard"));
        auto prospectiveKeys = admittedTestKeys;
        for (const auto& value : values) prospectiveKeys.insert(value.key);
        for (const auto& owned : keys) prospectiveKeys.insert(owned);
        if (prospectiveKeys.size() > 3) throw ToolError(409, "Three distinct admitted test keys per world limit reached");
        admittedTestKeys = std::move(prospectiveKeys);
        mutatedActors.insert(actor.actor->GetFormID());
        UpdateReceipt(key, {{"status", "provider_call_started"}, {"identity", actor.identity}, {"providerEpoch", providerEpoch},
            {"startedFrame", game::CurrentFrame()}, {"nativeCallsReturned", 0}});
        bool accepted = true;
        std::size_t returned = 0;
        const auto progress = [&] { UpdateReceipt(key, {{"nativeCallsReturned", ++returned}}); };
        called = true;
        if (action == "assign_preset" || action == "unassign_preset") {
            OBody::API::AssignPresetPayload payload{};
            payload.flags = OBody::API::AssignPresetPayload::ForceImmediateApplicationOfMorphs;
            payload.presetName = preset;
            accepted = obody->AssignPresetToActor(reinterpret_cast<::Actor*>(actor.actor), payload);
            progress();
        } else if (action == "reset_provider_morphs") {
            obody->RemoveOBodyMorphsFromActor(reinterpret_cast<::Actor*>(actor.actor));
            progress();
        } else {
            auto* native = reinterpret_cast<::TESObjectREFR*>(actor.actor);
            for (const auto& value : values) {
                if (!actor.Current()) throw ToolError(409, "Actor identity changed within fixture operation; remaining calls refused");
                skee->SetMorph(native, value.morph.c_str(), value.key.c_str(), value.value);
                progress();
            }
            for (const auto& owned : keys) {
                if (!actor.Current()) throw ToolError(409, "Actor identity changed within fixture operation; remaining calls refused");
                skee->ClearBodyMorphKeys(native, owned.c_str());
                progress();
            }
            // This schedules the provider's ordinary model update; it does not
            // prove rendering or subject consumption of the changed coefficients.
            if (!actor.Current()) throw ToolError(409, "Actor identity changed before fixture model update");
            skee->UpdateModelWeight(native, false);
            progress();
        }
        UpdateReceipt(key, {{"status", "call_returned"}, {"providerAccepted", accepted}, {"returnedFrame", game::CurrentFrame()},
            {"identityCurrentAfterCall", actor.Current()}, {"requiresIndependentObservation", true},
            {"completion", "unobserved"}});
        return Receipt(key);
    } catch (const std::exception& error) {
        UpdateReceipt(key, {{"status", called ? "call_outcome_unknown" : "rejected_before_call"}, {"error", error.what()},
            {"requiresIndependentObservation", called}, {"completion", "unobserved"}});
        throw;
    } catch (...) {
        UpdateReceipt(key, {{"status", called ? "call_outcome_unknown" : "rejected_before_call"},
            {"error", "Unknown native exception"}, {"completion", "unobserved"}});
        throw;
    }
}
json Handle(const json& args, const ToolContext&) {
    const auto action = args.at("action").get<std::string>();
    std::set<std::string> allowed{"action", "timeoutMs"};
    if (action == "catalog") allowed.insert({"category", "offset", "limit"});
    else if (action == "actor_status") allowed.insert("actorFormId");
    else if (action == "action_status") allowed.insert({"owner", "command"});
    else if (Mutation(action)) {
        allowed.insert({"owner", "command", "actorFormId", "guard"});
        if (action == "assign_preset") allowed.insert("presetName");
        if (action == "set_test_morphs") allowed.insert("values");
        if (action == "remove_test_keys") allowed.insert("keys");
    } else if (action != "capabilities") throw ToolError(400, "Unknown morph provider action");
    ExactKeys(args, allowed);
    const auto timeout = args.value("timeoutMs", 3000);
    if (timeout < 1 || timeout > 5000) throw ToolError(400, "Morph provider timeout outside1..5000ms");
    std::string key;
    if (Mutation(action) || action == "action_status") {
        const auto owner = args.at("owner").get<std::string>(), command = args.at("command").get<std::string>();
        if (!Policy::Token(owner) || !Policy::Token(command)) throw ToolError(400, "Exact owner/command tokens required");
        key = owner + ":" + command;
    }
    if (Mutation(action)) {
        // Reserve before queueing: an HTTP timeout before task start also cannot
        // make this command identifier replayable. Receipts survive world loads.
        std::lock_guard lock(receiptsGate);
        if (receipts.contains(key)) throw ToolError(409, "Command already attempted; read action_status, never replay");
        if (receipts.size() >= Policy::MaxCommands) throw ToolError(409, "Process command receipt bound reached");
        receipts.emplace(key, json{{"status", "queued"}, {"action", action}, {"owner", args.at("owner")},
            {"command", args.at("command")}, {"pid", GetCurrentProcessId()}, {"completion", "unobserved"}});
    }
    try {
        return MainThread::RunAndWait([args, action, key]() -> json {
            if (Mutation(action)) return Mutate(args, action, key);
            std::lock_guard lock(providerGate);
            if (action == "capabilities") return Capabilities();
            if (action == "catalog") return Catalog(args);
            if (action == "action_status") {
                auto out = Stamp(); out["receipt"] = Receipt(key); return out;
            }
            auto actor = Actor(args.at("actorFormId").get<std::string>());
            auto out = Stamp(); out["identity"] = actor.identity;
            out["assignment"] = obody && obodyReady ? Assignment(actor.actor) : json{{"status", "unavailable"}};
            out["identityCurrentAfterRead"] = actor.Current();
            if (!actor.Current()) throw ToolError(409, "Actor identity changed during provider status read");
            return out;
        }, std::chrono::milliseconds(timeout));
    } catch (const MainThread::TaskTimeout& error) {
        if (Mutation(action)) {
            std::lock_guard lock(receiptsGate);
            auto& receipt = receipts.at(key);
            receipt["transportTimedOut"] = true;
            receipt["mainThreadTaskStartedAtTimeout"] = error.started;
            if (!error.started && receipt.at("status") == "queued") receipt["status"] = "abandoned_before_start";
        }
        throw;
    }
}
void Initialize() {
    std::lock_guard lock(providerGate);
    if (initialized) return;
    initialized = true;
    const auto messaging = SKSE::GetMessagingInterface();
    if (!messaging) return;
    OBody::API::SKSEMessages::RequestPluginInterface request{};
    request.version = OBody::API::PluginAPIVersion::v1;
    request.pluginInterface = &obody;
    request.readinessEventListener = &readiness;
    // The provider may synchronously invoke readiness with the newly written
    // interface pointer; both pointer and listener have process lifetime.
    messaging->Dispatch(decltype(request)::type, &request, sizeof(request), "OBody");
    InterfaceExchangeMessage exchange{};
    if (messaging->Dispatch(static_cast<std::uint32_t>(InterfaceExchangeMessage::kMessage_ExchangeInterface), &exchange, sizeof(exchange), "skee") && exchange.interfaceMap) {
        if (auto* base = exchange.interfaceMap->QueryInterface("BodyMorph")) {
            skeeVersion = base->GetVersion();
            if (skeeVersion == 5) skee = static_cast<IBodyMorphInterface*>(base);
        }
    }
}
}
void OnSKSEMessage(std::uint32_t type) {
    if (type == SKSE::MessagingInterface::kPostPostLoad) Initialize();
    std::lock_guard lock(providerGate);
    if (type == SKSE::MessagingInterface::kPreLoadGame || type == SKSE::MessagingInterface::kNewGame) {
        ++worldGeneration;
        mutatedActors.clear();
        admittedTestKeys.clear();
        sampledModels.clear();
        worldLoading = type == SKSE::MessagingInterface::kPreLoadGame;
    } else if (type == SKSE::MessagingInterface::kPostLoadGame) worldLoading = false;
}
void Register(ToolRegistry& registry) {
    ToolDescriptor descriptor;
    descriptor.name = "morph_provider";
    descriptor.description = "Bounded real OBody native control/catalog and three owned SKEE fixture keys. Mutations require exact disposable actor guards and non-replayable owner/command tokens; call return is not completion.";
    descriptor.inputSchema = {{"type", "object"}, {"required", {"action"}}, {"additionalProperties", false},
        {"properties", {{"action", {{"type", "string"}, {"enum", {"capabilities", "catalog", "actor_status", "action_status", "assign_preset", "unassign_preset", "reset_provider_morphs", "set_test_morphs", "remove_test_keys"}}}},
            {"timeoutMs", {{"type", "integer"}, {"minimum", 1}, {"maximum", 5000}}},
            {"actorFormId", {{"type", "string"}}}, {"guard", {{"type", "object"}}},
            {"owner", {{"type", "string"}}}, {"command", {{"type", "string"}}}, {"presetName", {{"type", "string"}}},
            {"category", {{"type", "string"}}}, {"offset", {{"type", "integer"}}}, {"limit", {{"type", "integer"}}},
            {"values", {{"type", "array"}}}, {"keys", {{"type", "array"}}}}}};
    registry.Register(std::move(descriptor), &Handle);
}
}
