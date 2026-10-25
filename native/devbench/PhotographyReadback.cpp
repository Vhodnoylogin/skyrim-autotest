// Read-only measurements. This does not capture pixels, freeze physics or move a camera.
#include "PhotographyReadback.h"
#include "ToolRegistry.h"
#include "MainThread.h"
#include "GameState.h"
#include <charconv>
#include <cstring>
#include <set>
#include <vector>

namespace dvb::PhotographyReadback {
namespace {
json Vec(const RE::NiPoint3& p) { return {p.x,p.y,p.z}; }
json Transform(const RE::NiTransform& t) {
    json rotation=json::array();for(const auto& row:t.rotate.entry)for(float v:row)rotation.push_back(v);
    return {{"translation",Vec(t.translate)},{"rotationRowMajor",rotation},{"scale",t.scale}};
}
json Frustum(const RE::NiFrustum& f) {
    return {{"left",f.fLeft},{"right",f.fRight},{"top",f.fTop},{"bottom",f.fBottom},
        {"near",f.fNear},{"far",f.fFar},{"orthographic",f.bOrtho}};
}
RE::Actor* Actor(const std::string& value) {
    auto text=std::string_view(value);if(text.starts_with("0x"))text.remove_prefix(2);
    std::uint32_t id=0;const auto [end,error]=std::from_chars(text.data(),text.data()+text.size(),id,16);
    if(error!=std::errc{}||end!=text.data()+text.size()||!id)throw ToolError(400,"Exact nonzero hex actor required");
    auto* form=RE::TESForm::LookupByID(id);auto* actor=form?form->As<RE::Actor>():nullptr;
    if(!actor||!actor->Get3D())throw ToolError(422,"Loaded native actor unavailable");return actor;
}
json Handle(const json& args,const ToolContext&) {
    for(const auto& [key,value]:args.items())if(key!="actor"&&key!="timeoutMs")throw ToolError(400,"Unknown photography readback field");
    const auto id=args.at("actor").get<std::string>();
    const auto timeout=args.value("timeoutMs",3000);if(timeout<1||timeout>5000)throw ToolError(400,"Read deadline outside1..5000ms");
    return MainThread::RunAndWait([id]()->json {
        if(!REL::Module::IsVR())throw ToolError(422,"Photography readback currently supports VR only");
        auto* actor=Actor(id);auto* root=actor->Get3D();auto* playerCamera=RE::PlayerCamera::GetSingleton();
        auto* ui=RE::UI::GetSingleton();auto* main=RE::Main::GetSingleton();
        if(!playerCamera||!playerCamera->cameraRoot||!ui||!main)throw ToolError(422,"Native camera/UI/main unavailable");
        if(!actor->GetCharController())throw ToolError(422,"Native actor collision controller unavailable");
        RE::CFilter filter{};actor->GetCollisionFilterInfo(filter);
        const auto state=actor->AsActorState();
        json out={{"schemaVersion",1},{"protocol","photography-readback/1"},{"pid",GetCurrentProcessId()},
            {"frame",game::CurrentFrame()},{"phase","skse_main_thread_task"},
            {"atomicRenderSnapshot",false},{"projectionSource","primary-camera-worldToCam"},
            {"freezeTime",main->GetRuntimeData().freezeTime},
            {"ui",{{"menusVisible",ui->IsShowingMenus()},{"paused",ui->GameIsPaused()},
                {"blockingMenu",ui->IsModalMenuOpen()||ui->IsItemMenuOpen()||ui->IsApplicationMenuOpen()}}},
            {"actor",{{"reference",std::format("0x{:08X}",actor->GetFormID())},
                {"runtimeHandle",actor->GetHandle().native_handle()},
                {"restrained",state->GetLifeState()==RE::ACTOR_LIFE_STATE::kRestrained},
                {"aiEnabled",actor->IsAIEnabled()},{"collisionsEnabled",!filter.QNoCollision()},
                {"collisionFilter",filter.filter},{"collisionBasis","native actor CFilter no-collision flag; not contact proof"},
                {"position",Vec(actor->GetPosition())},{"angles",Vec(actor->GetAngle())},
                {"bound",{{"center",Vec(root->worldBound.center)},{"radius",root->worldBound.radius}}}}},
            {"cameraRoot",Transform(playerCamera->cameraRoot->world)}};
        std::vector<RE::NiAVObject*> pending{playerCamera->cameraRoot.get()};std::set<RE::NiAVObject*> seen;
        RE::NiCamera* camera=nullptr;
        while(!pending.empty()) {
            auto* current=pending.back();pending.pop_back();if(!current||!seen.insert(current).second)continue;
            if(seen.size()>128)throw ToolError(422,"Native camera tree exceeds128nodes");
            if(auto* candidate=netimmerse_cast<RE::NiCamera*>(current)) {
                if(camera)throw ToolError(422,"Ambiguous primary NiCamera in player camera root");camera=candidate;
            }
            if(auto* node=current->AsNode()) {
                const auto& children=node->GetChildren();
                if(children.size()>128)throw ToolError(422,"Native camera children exceed bound");
                for(auto& child:children)if(child)pending.push_back(child.get());
            }
        }
        if(!camera)throw ToolError(422,"Primary NiCamera unavailable");
        const auto& data=camera->GetVRRuntimeData();const auto& common=camera->GetRuntimeData2();
        if(!data.viewFrustumArray||!data.viewFrustumBuffer)throw ToolError(422,"Native eye frustums unavailable");
        json matrix=json::array();for(const auto& row:data.worldToCam)for(float v:row)matrix.push_back(v);
        json projected=json::array();const auto& bound=root->worldBound;
        if(!(std::isfinite(bound.radius)&&bound.radius>0))throw ToolError(422,"Positive native actor bound unavailable");
        // Project the enclosing cube, a conservative geometric whole-bound test.
        // This primary matrix is NOT claimed to match a provider/eye until live qualification.
        for(int i=0;i<8;++i) {
            const RE::NiPoint3 point{bound.center.x+((i&1)?1.f:-1.f)*bound.radius,
                bound.center.y+((i&2)?1.f:-1.f)*bound.radius,bound.center.z+((i&4)?1.f:-1.f)*bound.radius};
            float x=0,y=0,z=0;const bool valid=RE::NiCamera::WorldPtToScreenPt3(data.worldToCam,common.port,point,x,y,z,1e-5f);
            projected.push_back({{"projected",valid},{"uvDepth",{x,y,z}}});
        }
        std::array<float,4> port{};static_assert(sizeof(common.port)==sizeof(port));
        std::memcpy(port.data(),&common.port,sizeof(port));
        out["camera"]={{"world",Transform(camera->world)},{"worldToCam",matrix},
            {"frustum",Frustum(common.viewFrustum)},{"eyeFrustums",{Frustum(data.viewFrustumArray[0]),Frustum(data.viewFrustumArray[1])}},
            {"viewport",port},
            {"projectedBoundCorners",projected}};
        const auto finite=[](const auto& self,const json& v)->bool {
            if(v.is_number_float())return std::isfinite(v.get<double>());
            if(v.is_array()||v.is_object())for(const auto& child:v)if(!self(self,child))return false;return true;
        };
        if(!finite(finite,out))throw ToolError(422,"Non-finite photography state");return out;
    },std::chrono::milliseconds(timeout));
}
}
void Register(ToolRegistry& registry) {
    ToolDescriptor descriptor;descriptor.name="photography_readback";descriptor.readOnly=true;
    descriptor.description="Native loaded actor AI/restraint/collision flag and measured primary VR camera/projection. Read-only; not renderer atomicity, pixel visibility, contact or provider-eye equivalence.";
    descriptor.inputSchema={{"type","object"},{"required",{"actor"}},{"properties",{
        {"actor",{{"type","string"}}},{"timeoutMs",{{"type","integer"}}}}}};
    registry.Register(std::move(descriptor),&Handle);
}
}
