include(GoogleTest)

enable_testing()

function(zinc_add_risk_test test_name)
    add_executable(${test_name} ${test_name}.cpp)
    target_link_libraries(${test_name} PRIVATE GTest::gtest_main zinc)
    target_link_options(${test_name} PRIVATE $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wl,--as-needed>)
    target_compile_options(
        ${test_name}
        PRIVATE
            $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
            $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
    )
    gtest_discover_tests(${test_name})
endfunction()

zinc_add_risk_test(risk_historical_var_test)
zinc_add_risk_test(risk_cvar_test)
zinc_add_risk_test(risk_max_drawdown_test)
zinc_add_risk_test(risk_correlation_matrix_test)

function(zinc_add_ta_test test_name)
    add_executable(${test_name} ${test_name}.cpp)
    target_link_libraries(${test_name} PRIVATE GTest::gtest_main zinc)
    target_link_options(${test_name} PRIVATE $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wl,--as-needed>)
    target_compile_options(
        ${test_name}
        PRIVATE
            $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
            $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
    )
    gtest_discover_tests(${test_name})
endfunction()

zinc_add_ta_test(ta_atr_test)
zinc_add_ta_test(ta_adx_test)
zinc_add_ta_test(ta_zscore_test)
zinc_add_ta_test(ta_bollinger_test)
zinc_add_ta_test(ta_hmm_regime_test)

function(zinc_add_opt_test test_name)
    add_executable(${test_name} ${test_name}.cpp)
    target_link_libraries(${test_name} PRIVATE GTest::gtest_main zinc)
    target_link_options(${test_name} PRIVATE $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wl,--as-needed>)
    target_compile_options(
        ${test_name}
        PRIVATE
            $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
            $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
    )
    gtest_discover_tests(${test_name})
endfunction()

zinc_add_opt_test(opt_mvo_test)
zinc_add_opt_test(opt_black_litterman_test)
zinc_add_opt_test(opt_hrp_test)

function(zinc_add_bt_test test_name)
    add_executable(${test_name} ${test_name}.cpp)
    target_link_libraries(${test_name} PRIVATE GTest::gtest_main zinc)
    target_link_options(${test_name} PRIVATE $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wl,--as-needed>)
    target_compile_options(
        ${test_name}
        PRIVATE
            $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
            $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
    )
    gtest_discover_tests(${test_name})
endfunction()

zinc_add_bt_test(bt_engine_test)

function(zinc_add_oms_test test_name)
    add_executable(${test_name} ${test_name}.cpp)
    target_link_libraries(${test_name} PRIVATE GTest::gtest_main zinc)
    target_link_options(${test_name} PRIVATE $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wl,--as-needed>)
    target_compile_options(
        ${test_name}
        PRIVATE
            $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
            $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
    )
    gtest_discover_tests(${test_name})
endfunction()

zinc_add_oms_test(oms_state_machine_test)
zinc_add_oms_test(oms_position_tracker_test)
