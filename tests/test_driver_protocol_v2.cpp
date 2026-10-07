// Real C++ state machine and atomic file handshake; isolated PROGRAMDATA only.
#include "autotest_protocol.h"
#include <filesystem>
#include <sstream>
#include <iostream>

void Write(std::ostream& out,const autotest::Frame& f){
    out.precision(17);out<<"SKYRIM_AUTOTEST 2 "<<f.owner<<' '<<f.seq<<' '<<f.tick<<' '<<f.lease<<' '<<f.command<<' ';
    for(int i=0;i<3;++i){const auto& d=f.devices[i];
        out<<d.x<<' '<<d.y<<' '<<d.z<<' '<<d.w<<' '<<d.qx<<' '<<d.qy<<' '<<d.qz<<' ';
        if(i){out<<d.pressed<<' '<<d.touched<<' ';for(auto v:d.axes)out<<v<<' ';}}
}
int main(){
    autotest::Device supported;
    supported.pressed=1ULL<<33;supported.touched=1ULL<<32;supported.axes[2]=.7;
    if(!autotest::SupportedComponents(supported))return 31;
    auto unsupported=supported;unsupported.pressed|=1ULL<<40;
    if(autotest::SupportedComponents(unsupported))return 32;
    unsupported=supported;unsupported.touched|=4;
    if(autotest::SupportedComponents(unsupported))return 33;
    unsupported=supported;unsupported.axes[9]=.1;
    if(autotest::SupportedComponents(unsupported))return 34;
    autotest::State state;autotest::Frame f;
    f.owner=std::string(32,'a');f.command=std::string(32,'b');f.seq=77;f.tick=1000;f.lease=500;f.valid=true;
    f.devices[2].pressed=4;f.devices[2].touched=4;f.devices[2].axes[0]=.5;
    auto t=autotest::Clock::time_point{};
    if(!autotest::Accept(state,f,1000,t))return 11;
    if(autotest::Accept(state,f,1300,t+std::chrono::milliseconds(300)))return 12; // Same seq never extends lease.
    auto future=f;future.seq=78;future.tick=2000;
    if(autotest::Accept(state,future,1300,t+std::chrono::milliseconds(300)))return 13;
    auto foreign=f;foreign.owner=std::string(32,'c');foreign.seq=90;
    if(autotest::Accept(state,foreign,1300,t+std::chrono::milliseconds(300)))return 14;
    if(autotest::Current(state,t+std::chrono::milliseconds(499)).devices[2].pressed!=4)return 15;
    auto expired=autotest::Current(state,t+std::chrono::milliseconds(500));
    if(expired.valid||expired.devices[2].pressed||expired.devices[2].touched||expired.devices[2].axes[0])return 16;
    if(autotest::Accept(state,f,1600,t+std::chrono::milliseconds(600)))return 17; // Stale file cannot reactivate.
    foreign.tick=1600;foreign.lease=50;
    if(!autotest::Accept(state,foreign,1600,t+std::chrono::milliseconds(600)))return 18;
    auto replay=f;replay.tick=1700;
    if(autotest::Accept(state,replay,1700,t+std::chrono::milliseconds(700)))return 19; // Previous owner high-water retained.
    replay.seq=78;
    if(!autotest::Accept(state,replay,1700,t+std::chrono::milliseconds(700)))return 20;
    {std::stringstream input;Write(input,f);autotest::Frame parsed;if(!autotest::Parse(input,parsed))return 21;}
    {std::stringstream input;Write(input,f);input<<" trailing";autotest::Frame parsed;if(autotest::Parse(input,parsed))return 22;}
    {std::stringstream input("77 123456");autotest::Frame parsed;if(autotest::Parse(input,parsed))return 23;}
    {auto bad=f;bad.lease=5001;std::stringstream input;Write(input,bad);autotest::Frame parsed;if(autotest::Parse(input,parsed))return 24;}
    auto directory=std::filesystem::path(autotest::Directory());std::filesystem::create_directories(directory);
    f.tick=GetTickCount64();f.lease=500;
    {std::ofstream file(directory/"frame.txt");Write(file,f);}
    auto accepted=autotest::Read();if(!accepted.valid||accepted.devices[2].pressed!=4)return 25;
    autotest::Applied(accepted,0,true);autotest::Applied(accepted,1,true);autotest::Applied(accepted,2,true);
    {std::ifstream ack(directory/"ack.txt");std::string magic,instance,owner,command;unsigned int version,roles,errors,isExpired;
     unsigned long long seq,at,until;ack>>magic>>version>>instance>>owner>>seq>>command>>at>>until>>roles>>errors>>isExpired;
     if(!ack||magic!="SKYRIM_AUTOTEST_ACK"||version!=2||owner!=f.owner||seq!=77||command!=f.command||roles!=7||errors||isExpired)return 26;}
    {std::ofstream truncated(directory/"frame.txt");truncated<<"SKYRIM_AUTOTEST 2 ";}
    if(autotest::Read().devices[2].pressed!=4)return 27;
    Sleep(600);expired=autotest::Read();
    if(expired.valid||expired.devices[2].pressed||expired.devices[2].touched||expired.devices[2].axes[0])return 28;
    std::cout<<"PASS: monotonic expiry, original lease on repeat/partial IO, owner exclusion/high-water, stale/future/version rejection and exact component ACK.\n";
    return 0;
}
