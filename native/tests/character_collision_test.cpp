// Production adapter with fake engine dispatch; CFilter.cpp is the real pinned SDK source.
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <utility>
#include "RE/C/CFilter.h"

namespace RE {
struct Lock {unsigned depth{}, entries{};};
struct bhkWorld {Lock worldLock;};
struct BSWriteLockGuard {
    Lock& lock;
    explicit BSWriteLockGuard(Lock& value):lock(value){++lock.depth;++lock.entries;}
    ~BSWriteLockGuard(){--lock.depth;}
};
template<class T> class NiPointer {
    T* value{};
public:
    NiPointer()=default;
    explicit NiPointer(T* pointer):value(pointer){}
    void reset(T* pointer){value=pointer;}
    T* get()const{return value;}
    T* operator->()const{return value;}
    explicit operator bool()const{return value!=nullptr;}
};
struct bhkCharacterController {
    virtual ~bhkCharacterController()=default;
    virtual void Slot01(){} virtual void Slot02(){} virtual void Slot03(){}
    virtual void Slot04(){} virtual void Slot05(){} virtual void Slot06(){} virtual void Slot07(){}
    virtual void GetCollisionFilterInfo(CFilter& value)const {
        if(!world||!world->worldLock.depth)throw std::runtime_error("getter outside world lock");
        value.filter=filter;
    }
    virtual void SetFilter(std::uint32_t value) {
        if(!world||!world->worldLock.depth)throw std::runtime_error("setter outside world lock");
        ++writes;
        if(throwAfterWrite){filter=value;throw std::runtime_error("lost setter return");}
        if(!ignoreWrite)filter=value^(changeOtherBit?2u:0u);
    }
    bhkWorld* GetHavokWorld()const{return world;}
    bhkWorld* world{};
    std::uint32_t filter=136445982;
    unsigned writes{};
    bool ignoreWrite{},throwAfterWrite{},changeOtherBit{};
};
struct Proxy:bhkCharacterController {void SetFilter(std::uint32_t value)override{bhkCharacterController::SetFilter(value);}};
struct Rigid:bhkCharacterController {void SetFilter(std::uint32_t value)override{bhkCharacterController::SetFilter(value);}};
struct Foreign:bhkCharacterController {void SetFilter(std::uint32_t value)override{bhkCharacterController::SetFilter(value);}};
inline std::array<std::uintptr_t,2> VTABLE_bhkCharProxyController{},VTABLE_bhkCharRigidBodyController{};
}
namespace REL {
inline std::array<std::uintptr_t,2> setterTargets{};
struct ID {std::uint64_t value;explicit ID(std::uint64_t number):value(number){}};
struct Version {int a,b,c,d;bool operator==(const Version&)const=default;};
struct Module {
    Version current{1,7,104,0};
    static Module& get(){static Module value;return value;}
    Version version()const{return current;}
};
template<class T> struct Relocation {
    T value;
    explicit Relocation(T address):value(address){}
    explicit Relocation(ID id):value(setterTargets.at(id.value==79148?0:1)){}
    T address()const{return value;}
};
}
namespace dvb {struct ToolError:std::runtime_error {int status;ToolError(int code,const char* text):std::runtime_error(text),status(code){}};}
#include "CharacterCollision.h"

unsigned checks{};
void Check(bool value){++checks;if(!value)throw std::runtime_error("check failed");}
template<class F> void Refuses(F call,int status){try{call();}catch(const dvb::ToolError& error){Check(error.status==status);return;}throw std::runtime_error("missing refusal");}
int main(){try {
    using dvb::NPCPersistence::CharacterCollision;
    RE::bhkWorld world,otherWorld;
    RE::Proxy proxy;RE::Rigid rigid;RE::Foreign foreign;
    proxy.world=rigid.world=foreign.world=&world;
    RE::VTABLE_bhkCharProxyController[1]=*reinterpret_cast<std::uintptr_t*>(&proxy);
    RE::VTABLE_bhkCharRigidBodyController[0]=*reinterpret_cast<std::uintptr_t*>(&rigid);
    REL::setterTargets[0]=reinterpret_cast<std::uintptr_t*>(RE::VTABLE_bhkCharProxyController[1])[9];
    REL::setterTargets[1]=reinterpret_cast<std::uintptr_t*>(RE::VTABLE_bhkCharRigidBodyController[0])[9];
    for(RE::bhkCharacterController* actor:{static_cast<RE::bhkCharacterController*>(&proxy),static_cast<RE::bhkCharacterController*>(&rigid)}) {
        for(const std::uint32_t filter:{136445982u,0u,0xffffffffu,0x80000001u}) {
            actor->filter=filter;const auto writes=actor->writes;
            CharacterCollision adapter(actor);const auto receipt=adapter.Disable(actor);
            Check(receipt.before==filter&&receipt.requested==(filter|0x4000u)&&receipt.after==(filter|0x4000u));
            Check(receipt.setterIssued==!(filter&0x4000u));
            Check(actor->writes==writes+unsigned(!(filter&0x4000u)));
            Check(world.worldLock.depth==0);
            const auto repeat=adapter.Disable(actor);Check(!repeat.setterIssued&&repeat.after==receipt.after);
        }
    }
    Check(proxy.filter==0x80004001u&&rigid.filter==0x80004001u&&foreign.filter==136445982);
    Refuses([&]{CharacterCollision value(nullptr);},422);
    Refuses([&]{CharacterCollision value(&foreign);},422);
    ++REL::setterTargets[0];Refuses([&]{CharacterCollision value(&proxy);},422);--REL::setterTargets[0];
    REL::Module::get().current={1,6,1170,0};Refuses([&]{CharacterCollision value(&proxy);},422);
    REL::Module::get().current={1,7,104,0};
    proxy.world=nullptr;Refuses([&]{CharacterCollision value(&proxy);},422);proxy.world=&world;
    CharacterCollision adapter(&proxy);
    const auto writes=proxy.writes;
    Refuses([&]{adapter.Disable(&rigid);},409);Refuses([&]{adapter.Disable(nullptr);},409);
    proxy.world=&otherWorld;Refuses([&]{adapter.Disable(&proxy);},409);proxy.world=&world;
    Check(proxy.writes==writes);
    {
        auto* original=*reinterpret_cast<std::uintptr_t**>(&proxy);
        std::array<std::uintptr_t,11> replaced{};
        for(std::size_t i=0;i<replaced.size();++i)replaced[i]=original[i];
        struct RestoreTable {
            RE::Proxy& actor;std::uintptr_t* original;
            ~RestoreTable(){*reinterpret_cast<std::uintptr_t**>(&actor)=original;RE::VTABLE_bhkCharProxyController[1]=reinterpret_cast<std::uintptr_t>(original);}
        } restore{proxy,original};
        *reinterpret_cast<std::uintptr_t**>(&proxy)=replaced.data();
        RE::VTABLE_bhkCharProxyController[1]=reinterpret_cast<std::uintptr_t>(replaced.data());
        CharacterCollision checked(&proxy);
        replaced[9]=REL::setterTargets[0]+1;
        Refuses([&]{checked.Disable(&proxy);},409);
        Check(proxy.writes==writes&&world.worldLock.depth==0);
    }
    proxy.filter=136445982;proxy.ignoreWrite=true;Refuses([&]{adapter.Disable(&proxy);},409);
    Check(proxy.filter==136445982&&proxy.writes==writes+1&&world.worldLock.depth==0);
    proxy.ignoreWrite=false;proxy.changeOtherBit=true;Refuses([&]{adapter.Disable(&proxy);},409);
    Check(world.worldLock.depth==0);
    proxy.changeOtherBit=false;proxy.filter=136445982;proxy.throwAfterWrite=true;
    try{adapter.Disable(&proxy);throw std::logic_error("missing exception");}catch(const std::runtime_error& e){Check(std::string(e.what())=="lost setter return");}
    Check(proxy.filter==136462366&&world.worldLock.depth==0);
    std::cout<<checks<<" checks passed; production adapter/fake dispatch + real CFilter; no engine qualification\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
