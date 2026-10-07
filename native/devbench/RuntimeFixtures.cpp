// Authored for Skyrim Autotest. External CommonLib/DevBench headers are not bundled.
#include "RuntimeFixtures.h"
#include "ToolRegistry.h"
#include "MainThread.h"
#include "GameState.h"
#include <charconv>
#include <set>
#include <unordered_map>

namespace dvb::RuntimeFixtures {
namespace {
bool Token(const std::string& value) {
    return value.size()==32 && value.find_first_not_of("0123456789abcdef")==std::string::npos;
}
RE::TESForm* Form(const std::string& value) {
    auto text=std::string_view(value);if(text.starts_with("0x"))text.remove_prefix(2);
    std::uint32_t id=0;auto [end,error]=std::from_chars(text.data(),text.data()+text.size(),id,16);
    if(error!=std::errc{}||end!=text.data()+text.size()||!id)throw ToolError(400,"Exact nonzero 32-bit hex FormID required");
    auto* form=RE::TESForm::LookupByID(id);if(!form)throw ToolError(404,"Native form unavailable");return form;
}
json Identity(const RE::TESForm* form) {
    json files=json::array();const auto* array=form->sourceFiles.array;
    if(array && array->size()>256)throw ToolError(422,"Native source file array exceeds bound");
    if(array)for(auto* file:*array){if(!file)throw ToolError(422,"Null native source file entry");files.push_back(file->fileName);}
    const bool dynamic=(form->GetFormID()>>24)==0xff;
    json out={{"runtimeId",std::format("0x{:08X}",form->GetFormID())},
        {"formType",std::string(RE::FormTypeToString(form->GetFormType()))},
        {"runtimeCreated",dynamic},{"sourceFiles",files},{"sourceFileCount",files.size()},
        {"sourceFilePolicy",files.empty()?"absent":dynamic?"inherited-template-file":"plugin-file"},
        {"plugin",files.empty()?json(nullptr):files.front()},
        {"localId",dynamic?json(nullptr):json(std::format("{:06X}",form->GetLocalFormID()))}};
    if(auto* object=form->As<RE::TESBoundObject>()) {
        const auto& min=object->boundData.boundMin;
        const auto& max=object->boundData.boundMax;
        out["bounds"]={{"min",{min.x,min.y,min.z}},{"max",{max.x,max.y,max.z}}};
    }
    return out;
}
// Accessed only inside MainThread::RunAndWait. Entries precede mutations and are
// never silently retried, including failures whose engine effect is uncertain.
std::unordered_map<std::string,json> creations;
json Handle(const json& args,const ToolContext&) {
    const auto action=args.value("action",std::string{});
    std::set<std::string> keys;
    if(action=="identity")keys={"action","formId","referenceBase","timeoutMs"};
    else if(action=="create_runtime_potion")keys={"action","templateFormId","sourceFilePolicy","owner","command","timeoutMs"};
    else if(action=="creation_status")keys={"action","owner","command","timeoutMs"};
    else throw ToolError(400,"Unknown runtime fixture action");
    for(const auto& [key,value]:args.items())if(!keys.contains(key))throw ToolError(400,"Unknown runtime fixture argument");
    const auto timeout=args.value("timeoutMs",5000);if(timeout<1||timeout>5000)throw ToolError(400,"Fixture timeout must be1..5000ms");
    return MainThread::RunAndWait([args,action]()->json {
        if(action=="identity") {
            auto* form=Form(args.at("formId").get<std::string>());
            const auto requestedId=form->GetFormID();
            const bool referenceBase=args.value("referenceBase",false);
            if(referenceBase) {
                auto* ref=form->As<RE::TESObjectREFR>();if(!ref||!ref->GetBaseObject())throw ToolError(422,"Reference base unavailable");
                form=ref->GetBaseObject();
            }
            return {{"schemaVersion",1},{"pid",GetCurrentProcessId()},{"frame",game::CurrentFrame()},
                {"requestedFormId",std::format("0x{:08X}",requestedId)},
                {"referenceBase",referenceBase},{"item",Identity(form)}};
        }
        const auto owner=args.at("owner").get<std::string>(),command=args.at("command").get<std::string>();
        if(!Token(owner)||!Token(command))throw ToolError(400,"Exact owner/command tokens required");
        const auto key=owner+":"+command;
        const auto previous=creations.find(key);
        if(action=="creation_status")return previous==creations.end()?json{{"status","unknown"}}:previous->second;
        if(previous!=creations.end())throw ToolError(409,"Creation command already attempted; inspect creation_status, never replay");
        if(creations.size()>=32)throw ToolError(409,"Runtime fixture creation bound32 reached");
        auto* player=RE::PlayerCharacter::GetSingleton();
        if(!player||!player->Get3D()||!player->GetParentCell())throw ToolError(409,"Loaded gameplay world required");
        auto* source=Form(args.at("templateFormId").get<std::string>())->As<RE::AlchemyItem>();
        if(!source||(source->GetFormID()>>24)>=0xfe)throw ToolError(422,"Static ALCH template required");
        const auto policy=args.at("sourceFilePolicy").get<std::string>();
        if(policy!="absent"&&policy!="inherited-template-file")throw ToolError(400,"Unknown source file policy");
        if(policy=="inherited-template-file"&&!source->GetFile(0))throw ToolError(422,"Template has no native source file");
        const auto templateBounds=source->boundData;
        const auto& min=templateBounds.boundMin;
        const auto& max=templateBounds.boundMax;
        if(min.x>max.x||min.y>max.y||min.z>max.z||
           (min.x==max.x&&min.y==max.y&&min.z==max.z))
            throw ToolError(422,"Native template model bounds unavailable; no allocation");
        creations[key]={{"status","creating"},{"owner",owner},{"command",command},{"template",Identity(source)}};
        auto* duplicate=source->CreateDuplicateForm(false,nullptr);
        if(!duplicate||duplicate==source||duplicate->GetFormType()!=RE::FormType::AlchemyItem||
           (duplicate->GetFormID()>>24)!=0xff||RE::TESForm::LookupByID(duplicate->GetFormID())!=duplicate)
            throw ToolError(422,"Engine did not register a distinct runtime ALCH base; no fallback or replay");
        // Engine duplication can omit OBND even when the model path/effects
        // were copied. Preserve the exact native template extents by value;
        // never substitute guessed mesh bounds or edit the source object.
        auto* potion=duplicate->As<RE::AlchemyItem>();
        if(!potion)throw ToolError(422,"Duplicated ALCH object unavailable; no replay");
        potion->boundData=templateBounds;
        // Change only the duplicate's pointer field. Never edit/free the source
        // array, which may be shared by the engine's duplicate operation.
        if(policy=="absent")duplicate->sourceFiles.array=nullptr;
        else if(duplicate->GetFile(0)!=source->GetFile(0))duplicate->SetFile(source->GetFile(0));
        auto observed=Identity(duplicate);
        if(observed["bounds"]!=creations[key]["template"]["bounds"]||observed["sourceFilePolicy"]!=policy ||
            (policy=="inherited-template-file"&&duplicate->GetFile(0)!=source->GetFile(0)))
            throw ToolError(422,"Actual runtime ALCH bounds/source policy mismatch; no replay");
        creations[key].update({{"status","completed"},{"pid",GetCurrentProcessId()},
            {"frame",game::CurrentFrame()},{"item",observed}});
        return creations[key];
    },std::chrono::milliseconds(timeout));
}
}
void Register(ToolRegistry& registry) {
    ToolDescriptor descriptor;descriptor.name="runtime_fixture";
    descriptor.description="Bounded owned runtime ALCH fixtures and native form/source identity. Creation is once per owner/command; inspect creation_status after uncertainty. No automatic replay.";
    descriptor.inputSchema={{"type","object"},{"properties",{{"action",{{"type","string"}}},
        {"formId",{{"type","string"}}},{"referenceBase",{{"type","boolean"}}},
        {"templateFormId",{{"type","string"}}},{"sourceFilePolicy",{{"type","string"}}},
        {"owner",{{"type","string"}}},{"command",{{"type","string"}}},{"timeoutMs",{{"type","integer"}}}}}};
    registry.Register(std::move(descriptor),&Handle);
}
}
