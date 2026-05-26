find_package(benchmark CONFIG REQUIRED)

function(zinc_add_bench executable_name)
    add_executable(${executable_name} ${executable_name}.cpp)
    target_link_libraries(${executable_name} PRIVATE zinc benchmark::benchmark)
    target_include_directories(
        ${executable_name}
        PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}
            ${CMAKE_CURRENT_SOURCE_DIR}/../tests
    )
    target_compile_options(
        ${executable_name}
        PRIVATE
            $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
            $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
    )
endfunction()

zinc_add_bench(risk_bench)
zinc_add_bench(ta_bench)
zinc_add_bench(opt_bench)
zinc_add_bench(bt_bench)
zinc_add_bench(oms_bench)
