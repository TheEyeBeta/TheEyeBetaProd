find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)

nanobind_add_module(_zinc_risk NB_MODULE _zinc_risk.cpp)

target_link_libraries(_zinc_risk PRIVATE zinc)
target_compile_options(
    _zinc_risk
    PRIVATE
        $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
        $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
)

set(ZINC_NATIVE_MODULE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../libs/zinc_native/zinc_native")

add_custom_command(
    TARGET _zinc_risk
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "${ZINC_NATIVE_MODULE_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:_zinc_risk>"
            "${ZINC_NATIVE_MODULE_DIR}/$<TARGET_FILE_NAME:_zinc_risk>"
    VERBATIM
)

install(
    TARGETS _zinc_risk
    LIBRARY DESTINATION "libs/zinc_native/zinc_native"
    RUNTIME DESTINATION "libs/zinc_native/zinc_native"
)

nanobind_add_module(_zinc_ta NB_MODULE _zinc_ta.cpp)

target_link_libraries(_zinc_ta PRIVATE zinc)
target_compile_options(
    _zinc_ta
    PRIVATE
        $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
        $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
)

add_custom_command(
    TARGET _zinc_ta
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "${ZINC_NATIVE_MODULE_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:_zinc_ta>"
            "${ZINC_NATIVE_MODULE_DIR}/$<TARGET_FILE_NAME:_zinc_ta>"
    VERBATIM
)

install(
    TARGETS _zinc_ta
    LIBRARY DESTINATION "libs/zinc_native/zinc_native"
    RUNTIME DESTINATION "libs/zinc_native/zinc_native"
)

nanobind_add_module(_zinc_opt NB_MODULE _zinc_opt.cpp)

target_link_libraries(_zinc_opt PRIVATE zinc)
target_compile_options(
    _zinc_opt
    PRIVATE
        $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
        $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
)

add_custom_command(
    TARGET _zinc_opt
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "${ZINC_NATIVE_MODULE_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:_zinc_opt>"
            "${ZINC_NATIVE_MODULE_DIR}/$<TARGET_FILE_NAME:_zinc_opt>"
    VERBATIM
)

install(
    TARGETS _zinc_opt
    LIBRARY DESTINATION "libs/zinc_native/zinc_native"
    RUNTIME DESTINATION "libs/zinc_native/zinc_native"
)

nanobind_add_module(_zinc_bt NB_MODULE _zinc_bt.cpp)

target_link_libraries(_zinc_bt PRIVATE zinc)
target_compile_options(
    _zinc_bt
    PRIVATE
        $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
        $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
)

add_custom_command(
    TARGET _zinc_bt
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "${ZINC_NATIVE_MODULE_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:_zinc_bt>"
            "${ZINC_NATIVE_MODULE_DIR}/$<TARGET_FILE_NAME:_zinc_bt>"
    VERBATIM
)

install(
    TARGETS _zinc_bt
    LIBRARY DESTINATION "libs/zinc_native/zinc_native"
    RUNTIME DESTINATION "libs/zinc_native/zinc_native"
)

nanobind_add_module(_zinc_oms NB_MODULE _zinc_oms.cpp)

target_link_libraries(_zinc_oms PRIVATE zinc)
target_compile_options(
    _zinc_oms
    PRIVATE
        $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
        $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
)

add_custom_command(
    TARGET _zinc_oms
    POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "${ZINC_NATIVE_MODULE_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<TARGET_FILE:_zinc_oms>"
            "${ZINC_NATIVE_MODULE_DIR}/$<TARGET_FILE_NAME:_zinc_oms>"
    VERBATIM
)

install(
    TARGETS _zinc_oms
    LIBRARY DESTINATION "libs/zinc_native/zinc_native"
    RUNTIME DESTINATION "libs/zinc_native/zinc_native"
)
