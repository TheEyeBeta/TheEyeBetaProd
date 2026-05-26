cmake_minimum_required(VERSION 3.27)

project(zinc CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

find_package(Eigen3 CONFIG REQUIRED)
find_package(absl CONFIG REQUIRED)
find_package(fmt CONFIG REQUIRED)
find_package(spdlog CONFIG REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(GTest CONFIG REQUIRED)
find_package(benchmark CONFIG REQUIRED)
find_package(Arrow CONFIG REQUIRED)
find_package(Parquet CONFIG REQUIRED)
find_package(protobuf CONFIG REQUIRED)
find_package(gRPC CONFIG REQUIRED)
find_package(QuantLib CONFIG REQUIRED)
find_package(nanobind CONFIG REQUIRED)

add_library(zinc STATIC)
target_sources(
    zinc
    PRIVATE
        src/risk/historical_var.cpp
        src/risk/cvar.cpp
        src/risk/max_drawdown.cpp
        src/risk/correlation_matrix.cpp
        src/ta/atr.cpp
        src/ta/adx.cpp
        src/ta/rsi.cpp
        src/ta/zscore.cpp
        src/ta/bollinger.cpp
        src/ta/hmm_regime.cpp
        src/ta/snapshot_technicals.cpp
        src/opt/mvo.cpp
        src/opt/black_litterman.cpp
        src/opt/hrp.cpp
        src/bt/slippage_model.cpp
        src/bt/engine.cpp
        src/bt/detail/parquet_dataset.cpp
        src/oms/order.cpp
        src/oms/state_machine.cpp
        src/oms/position_tracker.cpp
)
target_include_directories(zinc PUBLIC include)
target_include_directories(zinc PRIVATE src/bt)
target_compile_options(
    zinc
    PRIVATE
        $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall -Wextra -Wpedantic>
        $<$<CXX_COMPILER_ID:MSVC>:/W4 /permissive->
)
target_link_libraries(
    zinc
    PUBLIC
        Eigen3::Eigen
        absl::base
        fmt::fmt
        spdlog::spdlog
        nlohmann_json::nlohmann_json
        Arrow::arrow_static
        Parquet::parquet_static
        protobuf::libprotobuf
        gRPC::grpc++
        QuantLib::QuantLib
        nanobind::nanobind
)
# GTest and benchmark are resolved for tests/ and bench/ subdirectories.

enable_testing()
add_subdirectory(tests)
add_subdirectory(bench)
add_subdirectory(bindings)
