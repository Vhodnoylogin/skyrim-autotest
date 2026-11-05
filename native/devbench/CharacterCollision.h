#pragma once
#include <cstddef>
#include <cstdint>

namespace dvb::NPCPersistence {

// Slot09 is verified in both controller implementations of SE1.7.104.
// CommonLib0c95630 still declares it Unk_09(void); do not call that signature.
class CharacterCollision {
public:
    struct Receipt {
        bool setterIssued{};
        std::uint32_t before{}, requested{}, after{};
    };

    explicit CharacterCollision(RE::bhkCharacterController* controller) {
        if(REL::Module::get().version()!=REL::Version{1,7,104,0})
            throw ToolError(422,"Controller collision setter requires verified SE1.7.104");
        if(!controller)throw ToolError(422,"Loaded character controller required before freeze");
        table_=*reinterpret_cast<std::uintptr_t**>(controller);
        const REL::Relocation<std::uintptr_t> proxy{RE::VTABLE_bhkCharProxyController[1]};
        const REL::Relocation<std::uintptr_t> rigid{RE::VTABLE_bhkCharRigidBodyController[0]};
        if(reinterpret_cast<std::uintptr_t>(table_)!=proxy.address()&&
           reinterpret_cast<std::uintptr_t>(table_)!=rigid.address())
            throw ToolError(422,"Unverified character-controller vtable; no freeze mutation");
        const REL::Relocation<std::uintptr_t> setter{REL::ID(
            reinterpret_cast<std::uintptr_t>(table_)==proxy.address()?79148:79200)};
        setter_=setter.address();
        if(table_[SetterSlot]!=setter_)
            throw ToolError(422,"Replaced controller collision setter; no freeze mutation");
        auto* world=controller->GetHavokWorld();
        if(!world)throw ToolError(422,"Character-controller Havok world unavailable before freeze");
        controller_.reset(controller);world_.reset(world);
    }

    Receipt Disable(RE::bhkCharacterController* current) const {
        if(current!=controller_.get()||*reinterpret_cast<std::uintptr_t**>(current)!=table_||
           current->GetHavokWorld()!=world_.get())
            throw ToolError(409,"Character controller/world changed before filter mutation");
        RE::BSWriteLockGuard lock(world_->worldLock);
        const auto target=table_[SetterSlot];
        if(target!=setter_)throw ToolError(409,"Controller collision setter changed before mutation");
        RE::CFilter before{};current->GetCollisionFilterInfo(before);
        auto desired=before;desired.SetNoCollision(true);
        const bool issued=!before.QNoCollision();
        if(issued) {
            using Setter=void (*)(RE::bhkCharacterController*,std::uint32_t);
            const auto setter=reinterpret_cast<Setter>(target);
            setter(current,desired.filter);
        }
        RE::CFilter after{};current->GetCollisionFilterInfo(after);
        if(after.filter!=desired.filter)
            throw ToolError(409,"Character-controller filter setter did not preserve requested state");
        return {issued,before.filter,desired.filter,after.filter};
    }

private:
    static constexpr std::size_t SetterSlot=0x09;
    RE::NiPointer<RE::bhkCharacterController> controller_;
    RE::NiPointer<RE::bhkWorld> world_;
    std::uintptr_t* table_{};
    std::uintptr_t setter_{};
};
}
