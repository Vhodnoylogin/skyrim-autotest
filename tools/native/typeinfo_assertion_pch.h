#pragma once
#include <SKSE/Impl/PCH.h>
// Windows/SDK headers can define NDEBUG themselves. Establish the declared
// assertion mode after those headers, identically for the test and actual TU.
#undef NDEBUG
#if !DEV_BENCH_EXPECT_ASSERTIONS
#    define NDEBUG
#endif
#include <assert.h>
