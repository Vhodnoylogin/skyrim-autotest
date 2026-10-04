// Our lease regression harness; compile with the separately downloaded SDK.
// PROGRAMDATA must point to a temporary test directory, never the real frame.
#include "autotest_protocol.h"
#include <filesystem>
#include <iostream>

int main() {
    char* root=nullptr; size_t count=0;
    _dupenv_s(&root, &count, "PROGRAMDATA");
    if (!root) return 10;
    auto path=std::filesystem::path(root)/"SkyrimVR Autotest"/"frame.txt";
    free(root);
    std::filesystem::create_directories(path.parent_path());
    autotest::Frame frame;
    frame.seq=77;
    frame.expiry=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count()+0.5;
    frame.devices[2].pressed=4;
    {
        std::ofstream out(path);
        out.precision(17);
        out << frame.seq << ' ' << frame.expiry << ' ';
        for (int i=0; i<3; ++i) {
            auto &d=frame.devices[i];
            out << d.x << ' ' << d.y << ' ' << d.z << ' ' << d.w << ' ' << d.qx << ' ' << d.qy << ' ' << d.qz << ' ';
            if (i) {
                out << d.pressed << ' ' << d.touched << ' ';
                for (auto v:d.axes) out << v << ' ';
            }
        }
    }
    if (autotest::Read().devices[2].pressed != 4) return 11;
    { std::ofstream truncated(path); truncated << "77 "; }
    if (autotest::Read().devices[2].pressed != 4) return 12;
    Sleep(650);
    auto released=autotest::Read();
    if (released.devices[2].pressed || released.devices[2].touched) return 13;
    for (auto v:released.devices[2].axes) if (v != 0) return 14;
    std::cout << "Complete frame survives partial read; original lease expiry releases input.\n";
    return 0;
}
