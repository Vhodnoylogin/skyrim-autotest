// Authored owned-fixture identity records, never an arbitrary save/load broker.
#include "NPCPersistence.h"
#include "ToolRegistry.h"
#include "MainThread.h"
#include <charconv>
#include <fstream>
#include <set>
#include <filesystem>

namespace dvb::NPCPersistence {
namespace {
constexpr std::uint32_t UniqueID=0x5356544E, RecordType=0x4E504350;
constexpr std::size_t MaximumBytes=65536;
json bundle;
std::vector<RE::VMHandle> retained;
std::set<std::string> preparationCommands;
const std::string session=std::format("{}-{}",GetCurrentProcessId(),GetTickCount64());
bool initialized=false;
auto* Policy() { auto* vm=RE::BSScript::Internal::VirtualMachine::GetSingleton();return vm?vm->GetObjectHandlePolicy():nullptr; }
bool Token(const std::string& s) { return s.size()==32&&s.find_first_not_of("0123456789abcdef")==std::string::npos; }
bool Label(const std::string& s) { return !s.empty()&&s.size()<=96&&s.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")==std::string::npos; }
std::string Hex(std::uint32_t id) { return std::format("0x{:08X}",id); }
std::uint32_t FormID(const std::string& s) {
    if(!s.starts_with("0x")||s.size()<3||s.size()>10)throw ToolError(400,"Exact nonzero FormID required");
    std::uint32_t v=0;auto [p,e]=std::from_chars(s.data()+2,s.data()+s.size(),v,16);
    if(e!=std::errc{}||p!=s.data()+s.size()||!v)throw ToolError(400,"Invalid FormID");return v;
}
std::uint64_t HandleID(const std::string& s) {
    std::uint64_t v=0;auto [p,e]=std::from_chars(s.data(),s.data()+s.size(),v);
    if(e!=std::errc{}||p!=s.data()+s.size()||!v)throw ToolError(400,"Invalid VM handle");return v;
}
RE::Actor* Actor(std::uint32_t id) {
    auto* form=RE::TESForm::LookupByID(id);auto* actor=form?form->As<RE::Actor>():nullptr;
    if(!actor||actor->IsDeleted()||!actor->IsPersistent()||(id>>24)!=0xff)
        throw ToolError(422,"Actual persistent dynamic NPC required");return actor;
}
json Inspection(RE::Actor* actor) {
    json slots=json::array();
    for(unsigned slot=30;slot<=61;++slot) {
        auto* armor=actor->GetWornArmor(static_cast<RE::BGSBipedObjectForm::BipedObjectSlot>(std::uint32_t(1)<<(slot-30)),true);
        slots.push_back({{"slot",slot},{"form",armor?json(Hex(armor->GetFormID())):json(nullptr)}});
    }
    const auto* left=actor->GetEquippedObject(true);const auto* right=actor->GetEquippedObject(false);
    const auto pos=actor->GetPosition();const auto* label=actor->GetDisplayFullName();
    const auto length=label?strnlen_s(label,513):0;if(length>512)throw ToolError(422,"Display name exceeds bound");
    auto* policy=Policy();if(!policy)throw ToolError(503,"Inspection VM policy unavailable");
    const auto h=policy->GetHandleForObject(static_cast<RE::VMTypeID>(actor->GetFormType()),actor);
    if(h==policy->EmptyHandle()||!policy->IsHandleObjectAvailable(h)||policy->GetObjectForHandle(static_cast<RE::VMTypeID>(actor->GetFormType()),h)!=actor)
        throw ToolError(422,"Inspection native VM identity unavailable");
    return {{"protocol","npc-persistence/1"},{"pid",GetCurrentProcessId()},{"providerSession",session},
        {"currentReference",Hex(actor->GetFormID())},{"base",Hex(actor->GetActorBase()->GetFormID())},
        {"runtimeHandle",actor->GetHandle().native_handle()},{"currentVmHandle",std::to_string(h)},
        {"persistent",actor->IsPersistent()},
        {"displayName",label?std::string(label,length):std::string{}},{"position",{pos.x,pos.y,pos.z}},
        {"wornArmorSlots",slots},{"equippedLeft",left?json(Hex(left->GetFormID())):json(nullptr)},
        {"equippedRight",right?json(Hex(right->GetFormID())):json(nullptr)},
        {"equippedLeftIsWeapon",left&&left->GetFormType()==RE::FormType::Weapon},
        {"equippedRightIsWeapon",right&&right->GetFormType()==RE::FormType::Weapon},
        {"dontMove",actor->GetActorRuntimeData().boolFlags.all(RE::Actor::BOOL_FLAGS::kMovementBlocked)},
        {"movementObservationBasis","typed Actor runtime BOOL_FLAGS::kMovementBlocked"},
        {"collisionStateObserved",false},{"collisionDisableCommandsIssued",0}};
}
void Release() noexcept {
    try { if(auto* p=Policy())for(auto h:retained)if(p->IsHandleObjectAvailable(h))p->ReleaseHandle(h); }
    catch(...) {} retained.clear();
}
void Retain(RE::VMHandle h) {
    if(std::find(retained.begin(),retained.end(),h)==retained.end()){Policy()->PersistHandle(h);retained.push_back(h);}
}
json Fresh(json value) {
    auto* policy=Policy();if(!policy)throw ToolError(503,"VM policy unavailable");
    for(auto& row:value["actors"]) {
        const bool loaded=value["phase"]=="loaded";
        auto id=FormID(row.at(loaded?"resolvedReference":"savedReference").get<std::string>());
        auto* actor=Actor(id);const auto* base=actor->GetActorBase();
        if(!base||Hex(base->GetFormID())!=row.at("base").get<std::string>())throw ToolError(422,"Persistent NPC base changed");
        const auto h=policy->GetHandleForObject(static_cast<RE::VMTypeID>(actor->GetFormType()),actor);
        if(h==policy->EmptyHandle()||!policy->IsHandleObjectAvailable(h)||
           policy->GetObjectForHandle(static_cast<RE::VMTypeID>(actor->GetFormType()),h)!=actor)
            throw ToolError(422,"Actual VM handle/reference correspondence unavailable");
        if(loaded&&h!=HandleID(row.at("resolvedVmHandle").get<std::string>()))
            throw ToolError(422,"Resolved saved VM handle does not identify current NPC");
        if(!loaded&&h!=HandleID(row.at("savedVmHandle").get<std::string>()))
            throw ToolError(422,"Saved NPC VM handle changed before load");
        Retain(h);
        row["currentReference"]=Hex(id);row["currentVmHandle"]=std::to_string(h);
        row["runtimeHandle"]=actor->GetHandle().native_handle();row["persistent"]=true;
    }
    value["providerSession"]=session;value["pid"]=GetCurrentProcessId();return value;
}
void Save(SKSE::SerializationInterface* serialization) {
    if(bundle.is_null())return;
    try {
        auto value=Fresh(bundle);value["saveOrdinal"]=value.at("saveOrdinal").get<unsigned>()+1;
        for(auto& row:value["actors"]) { row["savedReference"]=row["currentReference"];row["savedVmHandle"]=row["currentVmHandle"]; }
        value["phase"]="saved";const auto raw=value.dump();
        if(raw.size()>MaximumBytes||!serialization->WriteRecord(RecordType,1,raw.data(),static_cast<std::uint32_t>(raw.size())))
            throw std::runtime_error("NPC identity record write failed");
        bundle=std::move(value);
    } catch(const std::exception& e){bundle["error"]=e.what();logs::error("NPC persistence save: {}",e.what());}
}
void Load(SKSE::SerializationInterface* serialization) {
    Release();bundle=nullptr;
    std::uint32_t type=0,version=0,length=0;
    try {
        while(serialization->GetNextRecordInfo(type,version,length)) {
            if(type!=RecordType)continue;
            if(!bundle.is_null()||version!=1||!length||length>MaximumBytes)throw std::runtime_error("Invalid or duplicate NPC record");
            std::string raw(length,'\0');if(serialization->ReadRecordData(raw.data(),length)!=length)throw std::runtime_error("Short NPC record");
            auto value=json::parse(raw);
            if(value.at("protocol")!="npc-persistence/1"||value.at("phase")!="saved"||
                !value.at("actors").is_array()||value["actors"].empty()||value["actors"].size()>16)
                throw std::runtime_error("Invalid saved NPC bundle");
            for(auto& row:value["actors"]) {
                RE::FormID resolved=0;RE::VMHandle handle=0;
                const bool formOK=serialization->ResolveFormID(FormID(row.at("savedReference").get<std::string>()),resolved);
                const bool handleOK=serialization->ResolveHandle(HandleID(row.at("savedVmHandle").get<std::string>()),handle);
                if(!formOK||!handleOK||!resolved||!handle)throw std::runtime_error("SKSE NPC form/VM remap failed");
                if(!Policy())throw std::runtime_error("VM policy unavailable while retaining remapped NPC handle");
                Retain(handle);
                row["resolvedReference"]=Hex(resolved);row["resolvedVmHandle"]=std::to_string(handle);
                row["formResolved"]=true;row["handleResolved"]=true;
            }
            value["loadOrdinal"]=value.at("loadOrdinal").get<unsigned>()+1;value["phase"]="loaded";
            value["providerSession"]=session;value["pid"]=GetCurrentProcessId();bundle=std::move(value);
        }
    }catch(const std::exception& e){Release();bundle={{"error",e.what()}};logs::error("NPC persistence load: {}",e.what());}
}
void Revert(SKSE::SerializationInterface*) { Release();bundle=nullptr; }
json Handle(const json& args,const ToolContext&) {
    const auto action=args.at("action").get<std::string>();
    const std::set<std::string> allowed=action=="bind"?std::set<std::string>{"action","runId","saveTag","bindingId","actors","timeoutMs"}:
        action=="read"?std::set<std::string>{"action","bindingId","timeoutMs"}:
        action=="mapping_probe"?std::set<std::string>{"action","marker","nonce","timeoutMs"}:
        (action=="identity"||action=="inspection")?std::set<std::string>{"action","reference","base","timeoutMs"}:
        action=="prepare"?std::set<std::string>{"action","reference","base","kind","displayName","requestId","timeoutMs"}:std::set<std::string>{};
    if(allowed.empty())throw ToolError(400,"Unknown NPC persistence action");
    for(const auto& [key,unused]:args.items())if(!allowed.contains(key))throw ToolError(400,"Unknown NPC persistence field");
    const auto ms=args.value("timeoutMs",3000);if(ms<1||ms>5000)throw ToolError(400,"Timeout outside1..5000");
    return MainThread::RunAndWait([args,action]()->json {
        if(action=="inspection"||action=="prepare") {
            auto* actor=Actor(FormID(args.at("reference").get<std::string>()));
            if(!actor->GetActorBase()||Hex(actor->GetActorBase()->GetFormID())!=args.at("base").get<std::string>())throw ToolError(422,"Inspection actor base mismatch");
            if(action=="prepare") {
                const auto token=args.at("requestId").get<std::string>(),kind=args.at("kind").get<std::string>();
                const auto name=args.at("displayName").get<std::string>();
                if(!Token(token)||kind!="name"||name.empty()||name.size()>128||name.find('\0')!=std::string::npos)
                    throw ToolError(400,"Only bounded reference-name preparation is available");
                (void)json(name).dump();
                if(preparationCommands.size()>=64||!preparationCommands.insert(token).second)throw ToolError(409,"Name command consumed or bound reached; never replay");
                const bool accepted=actor->SetDisplayName(RE::BSFixedString(name),true);
                auto out=Inspection(actor);out["requestId"]=token;out["kind"]=kind;out["prepared"]=accepted;return out;
            }
            return Inspection(actor);
        }
        if(action=="identity") {
            auto* actor=Actor(FormID(args.at("reference").get<std::string>()));auto* policy=Policy();
            if(!policy||!actor->GetActorBase()||Hex(actor->GetActorBase()->GetFormID())!=args.at("base").get<std::string>())throw ToolError(422,"Persistent actor/VM base mismatch");
            const auto h=policy->GetHandleForObject(static_cast<RE::VMTypeID>(actor->GetFormType()),actor);
            if(h==policy->EmptyHandle()||!policy->IsHandleObjectAvailable(h)||policy->GetObjectForHandle(static_cast<RE::VMTypeID>(actor->GetFormType()),h)!=actor)
                throw ToolError(422,"Native persistent actor VM correspondence unavailable");
            Retain(h);
            return json{{"protocol","npc-persistence/1"},{"pid",GetCurrentProcessId()},{"providerSession",session},
                {"persistent",true},{"currentReference",Hex(actor->GetFormID())},{"base",Hex(actor->GetActorBase()->GetFormID())},
                {"currentVmHandle",std::to_string(h)},{"runtimeHandle",actor->GetHandle().native_handle()}};
        }
        if(action=="mapping_probe") {
            const auto marker=args.at("marker").get<std::string>(),nonce=args.at("nonce").get<std::string>();
            if(!Token(marker)||!Token(nonce))throw ToolError(400,"Exact random probe tokens required");
            auto logs=SKSE::log::log_directory();if(!logs)throw ToolError(503,"Game user directory unavailable");
            auto* ini=RE::INISettingCollection::GetSingleton();auto* setting=ini?ini->GetSetting("sLocalSavePath:General"):nullptr;
            if(!setting||!setting->GetString())throw ToolError(503,"Native save directory setting unavailable");
            std::filesystem::path local(setting->GetString());
            auto path=(local.is_absolute()?local:logs->parent_path()/local)/("Autotest_Map_"+marker+".probe");
            std::ifstream file(path,std::ios::binary);std::string observed(33,'\0');file.read(observed.data(),33);
            if(file.gcount()!=32||observed.substr(0,32)!=nonce)throw ToolError(422,"Native mapped nonce read failed");
            return json{{"protocol","npc-save-mapping/1"},{"pid",GetCurrentProcessId()},{"nativeDirectory",path.parent_path().string()},
                {"marker",marker},{"nonce",nonce},{"exactBytes",32},{"readOnly",true}};
        }
        const auto binding=args.at("bindingId").get<std::string>();if(!Token(binding))throw ToolError(400,"Exact binding UUID required");
        if(action=="bind") {
            if(!bundle.is_null())throw ToolError(409,"NPC persistence already bound; never overwrite/replay");
            const auto run=args.at("runId").get<std::string>(),tag=args.at("saveTag").get<std::string>();
            if(!Label(run)||!Label(tag)||!args.at("actors").is_array()||args["actors"].empty()||args["actors"].size()>16)
                throw ToolError(400,"Bound run/save/actor set required");
            json rows=json::array();std::set<std::uint32_t> seen;std::set<std::string> tags;
            auto* policy=Policy();if(!policy)throw ToolError(503,"VM policy unavailable");
            for(const auto& row:args["actors"]) {
                if(row.size()!=4||!row.contains("tag")||!row.contains("creationId")||!row.contains("reference")||!row.contains("base"))throw ToolError(400,"Exact actor identity fields required");
                const auto ref=FormID(row.at("reference").get<std::string>());auto* actor=Actor(ref);
                const auto name=row.at("tag").get<std::string>(),creation=row.at("creationId").get<std::string>();
                if(!Label(name)||!Token(creation)||!seen.insert(ref).second||!tags.insert(name).second||
                    !actor->GetActorBase()||Hex(actor->GetActorBase()->GetFormID())!=row.at("base").get<std::string>())throw ToolError(400,"Duplicate or mismatched actor identity");
                auto h=policy->GetHandleForObject(static_cast<RE::VMTypeID>(actor->GetFormType()),actor);
                if(!h||h==policy->EmptyHandle())throw ToolError(422,"VM handle unavailable");
                rows.push_back({{"tag",name},{"creationId",creation},{"base",row["base"]},{"savedReference",Hex(ref)},
                    {"savedVmHandle",std::to_string(h)}});
            }
            auto value=Fresh(json{{"schemaVersion",1},{"protocol","npc-persistence/1"},{"bindingId",binding},{"runId",run},
                {"saveTag",tag},{"phase","bound"},{"saveOrdinal",0},{"loadOrdinal",0},{"actors",rows}});
            bundle=std::move(value);
        }
        if(bundle.is_null()||bundle.value("bindingId",std::string{})!=binding||bundle.contains("error"))throw ToolError(422,"Exact valid bound/saved/loaded bundle unavailable");
        return Fresh(bundle);
    },std::chrono::milliseconds(ms));
}
}
void Initialize() {
    if(initialized)return;auto* s=SKSE::GetSerializationInterface();if(!s)return;
    s->SetUniqueID(UniqueID);s->SetSaveCallback(Save);s->SetLoadCallback(Load);s->SetRevertCallback(Revert);initialized=true;
}
void Register(ToolRegistry& registry) {
    ToolDescriptor d;d.name="npc_persistence";d.description="Owned persistent NPC co-save identities and bounded mapped-save nonce reads; no save/load commands";
    d.inputSchema={{"type","object"},{"properties",{{"action",{{"type","string"}}},{"runId",{{"type","string"}}},
        {"saveTag",{{"type","string"}}},{"bindingId",{{"type","string"}}},{"actors",{{"type","array"}}},
        {"reference",{{"type","string"}}},{"base",{{"type","string"}}},{"kind",{{"type","string"}}},
        {"displayName",{{"type","string"}}},{"requestId",{{"type","string"}}},
        {"marker",{{"type","string"}}},{"nonce",{{"type","string"}}},{"timeoutMs",{{"type","integer"}}}}}};
    registry.Register(std::move(d),Handle);
}
void OnSKSEMessage(std::uint32_t type) { if(type==SKSE::MessagingInterface::kPreLoadGame)Release(); }
}
