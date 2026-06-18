/**
 * @file   oms_bench.cpp
 * @brief  Google Benchmark suite for zinc::oms kernels.
 */

#include "zinc/oms/order.hpp"
#include "zinc/oms/state_machine.hpp"

#include <benchmark/benchmark.h>

namespace {

zinc::oms::Order make_accepted_order() {
    zinc::oms::Order order{.order_id = "BENCH-1", .quantity = 1'000'000};
    (void)zinc::oms::StateMachine::transition(order, zinc::oms::Event::Approve);
    (void)zinc::oms::StateMachine::transition(order, zinc::oms::Event::Submit);
    (void)zinc::oms::StateMachine::transition(order, zinc::oms::Event::Accept);
    return order;
}

} // namespace

static void BM_state_machine_transition_throughput(benchmark::State& state) {
    for (auto _ : state) {
        zinc::oms::Order order = make_accepted_order();
        const auto result =
            zinc::oms::StateMachine::transition(order, zinc::oms::Event::PartialFill, 1);
        benchmark::DoNotOptimize(result);
    }
}
BENCHMARK(BM_state_machine_transition_throughput);

BENCHMARK_MAIN();
