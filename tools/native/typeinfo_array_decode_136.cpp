#include <SKSE/Impl/PCH.h>
#include <RE/T/TypeInfo.h>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <string_view>

int main()
{
    using Type = RE::BSScript::TypeInfo;
    unsigned checks = 0;
#ifdef NDEBUG
    static_assert(DEV_BENCH_EXPECT_ASSERTIONS == 0);
#else
    static_assert(DEV_BENCH_EXPECT_ASSERTIONS == 1);
#endif
    // Backed addresses include both legal eight- and sixteen-byte alignments.
    // Never dereference a synthetic game object or invoke an engine singleton.
    alignas(16) std::array<std::byte, 64> storage{};
    for (std::size_t offset : {0u, 8u, 16u, 24u}) {
        const auto address = reinterpret_cast<std::uintptr_t>(storage.data() + offset);
        for (std::uintptr_t tag : {0u, 1u}) {
            Type type(static_cast<Type::RawType>(address | tag));
            if (reinterpret_cast<std::uintptr_t>(type.GetTypeInfo()) != address) {
                std::fprintf(stderr, "actual TypeInfo decoder mismatch: lowbits=%llu tag=%llu\n",
                    static_cast<unsigned long long>(address & 15), static_cast<unsigned long long>(tag));
                return 1;
            }
            ++checks;
        }
    }
    for (const auto raw : {Type::RawType::kObject, Type::RawType::kObjectArray}) {
        Type type(raw);
        if (type.GetTypeInfo() != nullptr || type.TypeAsString() != "none") {
            std::fputs("untyped object placeholder was not null/none\n", stderr);
            return 2;
        }
        ++checks;
    }
    constexpr std::array<std::pair<Type::RawType, std::string_view>, 10> literals{{
        {Type::RawType::kNone, "none"}, {Type::RawType::kString, "string"},
        {Type::RawType::kInt, "int"}, {Type::RawType::kFloat, "float"},
        {Type::RawType::kBool, "bool"}, {Type::RawType::kNoneArray, "none"},
        {Type::RawType::kStringArray, "string[]"}, {Type::RawType::kIntArray, "int[]"},
        {Type::RawType::kFloatArray, "float[]"}, {Type::RawType::kBoolArray, "bool[]"}}};
    for (const auto& [raw, expected] : literals) {
        if (Type(raw).TypeAsString() != expected) {
            std::fputs("primitive/literal-array formatting changed\n", stderr);
            return 3;
        }
        ++checks;
    }
    std::printf("actual production TypeInfo.cpp: %u checks passed; assertions=%d\n", checks, DEV_BENCH_EXPECT_ASSERTIONS);
    return 0;
}
