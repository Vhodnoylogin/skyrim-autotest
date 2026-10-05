#include <SKSE/Impl/PCH.h>
#include <RE/T/TypeInfo.h>
#include <cstdint>
#include <cstdio>

int main()
{
    using Type = RE::BSScript::TypeInfo;
    // Never dereference a fake object. Exercise the actual library decoder at
    // legal eight-byte alignments; clearing enum11 destroys address bit3.
    for (std::uintptr_t address : {0x1000ULL, 0x1008ULL, 0x1010ULL, 0x1018ULL}) {
        for (std::uintptr_t tag : {0ULL, 1ULL}) {
            Type info(static_cast<Type::RawType>(address | tag));
            if (reinterpret_cast<std::uintptr_t>(info.GetTypeInfo()) != address) {
                std::fprintf(stderr, "TypeInfo pointer mismatch address=%llx tag=%llu\n",
                    static_cast<unsigned long long>(address),static_cast<unsigned long long>(tag));
                return 1;
            }
        }
    }
    std::puts("TypeInfo actual decoder: all eight object/array alignment cases passed");
    return 0;
}
