// Authored debugger fixture. Build/output/CDB/dumps remain outside Git.
#include <Windows.h>

static void mark(const char* path) {
    HANDLE f = CreateFileA(path, GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f != INVALID_HANDLE_VALUE) {
        DWORD written;
        WriteFile(f, "actual fixture event\n", 21, &written, nullptr);
        CloseHandle(f);
    }
}

__declspec(noinline) static void fault() {
    *static_cast<volatile int*>(nullptr) = 123;
}

static void handled_fault() {
    __try {
        fault();
    } __except(GetExceptionCode() == EXCEPTION_ACCESS_VIOLATION ?
               EXCEPTION_EXECUTE_HANDLER : EXCEPTION_CONTINUE_SEARCH) {
        mark("handled.flag");
    }
}

static bool wait_for(const char* name) {
    const ULONGLONG end = GetTickCount64() + 20000;
    while (GetTickCount64() < end) {
        if (GetFileAttributesA(name) != INVALID_FILE_ATTRIBUTES) return true;
        Sleep(10);
    }
    return false;
}

int main() {
    mark("fixture-ready.flag");
    if (!wait_for("go.flag")) return 3;
    handled_fault();
    if (GetFileAttributesA("survive.flag") != INVALID_FILE_ATTRIBUTES) {
        mark("still-alive.flag");
        return wait_for("exit.flag") ? 0 : 4;
    }
    Sleep(100);
    fault();  // The unhandled second chance must remain a C0000005 exit.
    return 5;
}
