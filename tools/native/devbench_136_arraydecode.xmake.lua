-- Owned regression targets; the production plugin/SDK source stays unchanged by tests.
for _, variant in ipairs({{ "debug", 1 }, { "ndebug", 0 }}) do
    target("devbench-typeinfo-" .. variant[1])
        set_kind("binary")
        set_default(false)
        add_deps("commonlibsse-ng")
        add_files("tests/regressions/TypeInfoArrayDecode.cpp", "lib/commonlibsse-ng/src/RE/T/TypeInfo.cpp")
        set_pcxxheader("tests/regressions/TypeInfoPCH.h")
        add_defines("DEV_BENCH_EXPECT_ASSERTIONS=" .. variant[2])
        if variant[2] == 1 then add_undefines("NDEBUG") else add_defines("NDEBUG") end
        add_cxflags("/utf-8", "/EHsc", { force = true })
    target_end()
end
-- Compile the original captured TU separately; never swap/rebuild the positive SDK.
for _, variant in ipairs({{ "debug", 1 }, { "ndebug", 0 }}) do
    target("devbench-typeinfo-before-" .. variant[1])
        set_kind("binary")
        set_default(false)
        add_deps("commonlibsse-ng")
        add_files("tests/regressions/TypeInfoArrayDecode.cpp", "../TypeInfo-before.cpp")
        set_pcxxheader("tests/regressions/TypeInfoPCH.h")
        add_defines("DEV_BENCH_EXPECT_ASSERTIONS=" .. variant[2])
        if variant[2] == 1 then add_undefines("NDEBUG") else add_defines("NDEBUG") end
        add_cxflags("/utf-8", "/EHsc", { force = true })
    target_end()
end
target("devbench-typeinfo-regressions")
    set_kind("phony")
    set_default(false)
    add_deps("devbench-typeinfo-debug", "devbench-typeinfo-ndebug", "devbench-typeinfo-before-debug", "devbench-typeinfo-before-ndebug")
target_end()
