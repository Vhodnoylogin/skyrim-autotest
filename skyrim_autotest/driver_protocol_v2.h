// Owned version2 adapter protocol. Driver-local steady leases; no wall clock.
#pragma once
#include <openvr_driver.h>
#include <windows.h>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <string>
#include <unordered_map>

namespace autotest {
using Clock=std::chrono::steady_clock;
struct Device {
    double x=0,y=0,z=0,w=1,qx=0,qy=0,qz=0;
    unsigned long long pressed=0,touched=0;
    double axes[10]={};
};
struct Frame {
    std::string owner,command;
    unsigned long long seq=0,tick=0,lease=0;
    bool valid=false;
    Device devices[3];
};
struct Seen { unsigned long long seq=0,tick=0; };
struct State {
    std::mutex lock;
    Frame cached;
    Clock::time_point expires{};
    std::unordered_map<std::string,Seen> seen;
    unsigned int applied=0,errors=0;
    bool expiryWritten=false;
};
inline State& Shared() { static State value;return value; }
inline std::string Directory() {
    char* root=nullptr;size_t n=0;_dupenv_s(&root,&n,"PROGRAMDATA");
    std::string path=std::string(root?root:"C:\\ProgramData")+"\\SkyrimVR Autotest\\";
    free(root);return path;
}
inline bool Token(const std::string& value) {
    if(value.size()!=32)return false;
    for(char c:value)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;
    return true;
}
inline bool SupportedComponents(const Device& device) {
    constexpr unsigned long long pressedMask=0xffULL|(1ULL<<32)|(1ULL<<33);
    if((device.pressed&~pressedMask)||(device.touched&~(1ULL<<32)))return false;
    for(int i=3;i<10;++i)if(device.axes[i]!=0)return false;
    return true;
}
inline std::string Instance() {
    FILETIME created,exited,kernel,user;
    if(!GetProcessTimes(GetCurrentProcess(),&created,&exited,&kernel,&user))return "unavailable";
    ULARGE_INTEGER birth;birth.LowPart=created.dwLowDateTime;birth.HighPart=created.dwHighDateTime;
    return std::to_string(GetCurrentProcessId())+"-"+std::to_string(birth.QuadPart);
}
inline void Ack(const State& state,bool expired=false) {
    const auto& f=state.cached;if(f.owner.empty())return;
    auto path=Directory()+"ack.txt",temp=Directory()+"ack.tmp";
    {std::ofstream out(temp,std::ios::trunc);if(!out)return;
     out<<"SKYRIM_AUTOTEST_ACK 2 "<<Instance()<<' '<<f.owner<<' '<<f.seq<<' '<<f.command<<' '
        <<GetTickCount64()<<' '<<f.tick+f.lease<<' '<<(expired?0:state.applied)<<' '
        <<state.errors<<' '<<(expired?1:0)<<'\n';if(!out)return;}
    MoveFileExA(temp.c_str(),path.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH);
}
inline bool Parse(std::istream& in,Frame& f) {
    std::string magic;unsigned int version=0;
    if(!(in>>magic>>version>>f.owner>>f.seq>>f.tick>>f.lease>>f.command)||
       magic!="SKYRIM_AUTOTEST"||version!=2||!Token(f.owner)||!Token(f.command)||
       f.seq==0||f.seq>=(1ULL<<63)||f.lease==0||f.lease>5000)return false;
    for(int i=0;i<3;++i){auto& d=f.devices[i];
        if(!(in>>d.x>>d.y>>d.z>>d.w>>d.qx>>d.qy>>d.qz))return false;
        for(double v:{d.x,d.y,d.z,d.w,d.qx,d.qy,d.qz})if(!std::isfinite(v))return false;
        double norm=d.w*d.w+d.qx*d.qx+d.qy*d.qy+d.qz*d.qz;
        if(std::abs(norm-1)>0.001)return false;
        if(i){if(!(in>>d.pressed>>d.touched))return false;
            for(auto& v:d.axes)if(!(in>>v)||!std::isfinite(v)||std::abs(v)>1)return false;}}
    std::string extra;if(in>>extra)return false;
    f.valid=true;return true;
}
inline bool Accept(State& state,const Frame& incoming,unsigned long long tick,Clock::time_point now) {
    if(!incoming.valid||tick<incoming.tick||tick-incoming.tick>=incoming.lease)return false;
    for(auto it=state.seen.begin();it!=state.seen.end();){
        if(tick>=it->second.tick&&tick-it->second.tick>10000)it=state.seen.erase(it);else ++it;}
    auto previous=state.seen.find(incoming.owner);
    if(previous!=state.seen.end()&&incoming.seq<=previous->second.seq)return false;
    if(state.cached.valid&&now<state.expires&&incoming.owner!=state.cached.owner)return false;
    if(previous==state.seen.end()&&state.seen.size()>=64)return false;
    state.cached=incoming;state.expires=now+std::chrono::milliseconds(incoming.lease-(tick-incoming.tick));
    state.seen[incoming.owner]={incoming.seq,tick};state.applied=state.errors=0;state.expiryWritten=false;
    return true;
}
inline Frame Current(State& state,Clock::time_point now){
    Frame frame=state.cached;
    if(!frame.valid){frame.devices[0].y=1.65;frame.devices[1].x=-.3;frame.devices[2].x=.3;
        frame.devices[1].y=frame.devices[2].y=1.2;frame.devices[1].z=frame.devices[2].z=-.35;}
    if(!frame.valid||now>=state.expires){frame.valid=false;
        for(int i=1;i<3;++i){frame.devices[i].pressed=frame.devices[i].touched=0;for(auto& v:frame.devices[i].axes)v=0;}}
    return frame;
}
inline Frame Read(){
    auto& state=Shared();std::lock_guard<std::mutex> guard(state.lock);
    const auto now=Clock::now();std::ifstream stream(Directory()+"frame.txt",std::ios::ate);Frame incoming;
    const auto size=stream.tellg();stream.seekg(0);
    if(size>0&&size<=8192&&Parse(stream,incoming)&&Accept(state,incoming,GetTickCount64(),now))Ack(state);
    auto frame=Current(state,now);
    if(!frame.valid&&!state.expiryWritten&&!state.cached.owner.empty()){Ack(state,true);state.expiryWritten=true;}
    return frame;
}
inline void Applied(const Frame& frame,int role,bool successful){
    auto& state=Shared();std::lock_guard<std::mutex> guard(state.lock);
    if(!frame.valid||Clock::now()>=state.expires||frame.owner!=state.cached.owner||
       frame.seq!=state.cached.seq||role<0||role>2)return;
    auto before=state.applied;auto errors=state.errors;
    if(successful)state.applied|=1U<<role;else state.errors|=1U<<role;
    if(before!=state.applied||errors!=state.errors)Ack(state);
}
inline vr::DriverPose_t PoseFor(const Frame& frame,int role){
    const auto& d=frame.devices[role];vr::DriverPose_t pose={};
    pose.poseIsValid=true;pose.deviceIsConnected=true;pose.result=vr::TrackingResult_Running_OK;
    pose.qWorldFromDriverRotation.w=1;pose.qDriverFromHeadRotation.w=1;
    pose.vecPosition[0]=d.x;pose.vecPosition[1]=d.y;pose.vecPosition[2]=d.z;
    pose.qRotation.w=d.w;pose.qRotation.x=d.qx;pose.qRotation.y=d.qy;pose.qRotation.z=d.qz;
    return pose;
}
inline vr::DriverPose_t Pose(int role){return PoseFor(Read(),role);}
}
