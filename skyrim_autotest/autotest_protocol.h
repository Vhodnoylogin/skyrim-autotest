// Own adapter for a pinned external OpenVR sample driver.
// One atomic file describes the whole tracked set. Expired leases release buttons.
#pragma once
#include <openvr_driver.h>
#include <windows.h>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <string>

namespace autotest {
struct Device {
    double x=0, y=0, z=0, w=1, qx=0, qy=0, qz=0;
    unsigned long long pressed=0, touched=0;
    double axes[10] = {};
};
struct Frame {
    unsigned long long seq=1;
    double expiry=0;
    Device devices[3];
};
inline Frame Read() {
    // A transient sharing failure must not create a false release edge. Retain
    // the last complete frame only until its ORIGINAL lease expires.
    static std::mutex lock;
    std::lock_guard<std::mutex> guard(lock);
    static Frame cached;
    Frame frame;
    frame.devices[0].y=1.65;
    frame.devices[1].x=-0.3; frame.devices[1].y=1.2; frame.devices[1].z=-0.35;
    frame.devices[2].x=0.3; frame.devices[2].y=1.2; frame.devices[2].z=-0.35;
    char *programData=nullptr; size_t n=0;
    _dupenv_s(&programData, &n, "PROGRAMDATA");
    std::string path=std::string(programData ? programData : "C:\\ProgramData")+"\\SkyrimVR Autotest\\frame.txt";
    free(programData);
    double now=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count();
    if (cached.expiry >= now) frame=cached;
    std::ifstream stream(path);
    Frame incoming;
    if (!(stream >> incoming.seq >> incoming.expiry)) return frame;
    for (int i=0; i<3; ++i) {
        auto &d=incoming.devices[i];
        if (!(stream >> d.x >> d.y >> d.z >> d.w >> d.qx >> d.qy >> d.qz)) return frame;
        if (i) {
            if (!(stream >> d.pressed >> d.touched)) return frame;
            for (auto &v:d.axes) if (!(stream >> v)) return frame;
        }
    }
    if (incoming.expiry < now) return frame;
    cached=incoming;
    return incoming;
}
inline vr::DriverPose_t Pose(int role) {
    auto frame=Read(); auto &d=frame.devices[role];
    vr::DriverPose_t pose={};
    pose.poseIsValid=true; pose.deviceIsConnected=true;
    pose.result=vr::TrackingResult_Running_OK;
    pose.qWorldFromDriverRotation.w=1; pose.qDriverFromHeadRotation.w=1;
    pose.vecPosition[0]=d.x; pose.vecPosition[1]=d.y; pose.vecPosition[2]=d.z;
    pose.qRotation.w=d.w; pose.qRotation.x=d.qx; pose.qRotation.y=d.qy; pose.qRotation.z=d.qz;
    return pose;
}
}
