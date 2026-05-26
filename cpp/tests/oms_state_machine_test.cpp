/**
 * @file   oms_state_machine_test.cpp
 * @brief  Unit tests for zinc::oms::StateMachine.
 */

#include "zinc/oms/state_machine.hpp"

#include <cstdint>
#include <random>
#include <vector>

#include <gtest/gtest.h>

namespace {

zinc::oms::Order make_order(const int64_t quantity = 100) {
    return zinc::oms::Order{.order_id = "ORD-1", .quantity = quantity};
}

void expect_success(const zinc::oms::expected<zinc::oms::Order, zinc::oms::TransitionError>& result,
                    const zinc::oms::OrderStatus expected_status) {
    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(result->status, expected_status);
}

void expect_failure(const zinc::oms::expected<zinc::oms::Order, zinc::oms::TransitionError>& result,
                    const zinc::oms::TransitionErrorCode expected_code) {
    ASSERT_FALSE(result.has_value());
    EXPECT_EQ(result.error().code, expected_code);
}

}  // namespace

TEST(OmsStateMachineTest, HappyPathHandComputedPartialFills) {
    zinc::oms::Order order = make_order(100);

    expect_success(zinc::oms::StateMachine::transition(order, zinc::oms::Event::Approve),
                   zinc::oms::OrderStatus::Approved);
    expect_success(zinc::oms::StateMachine::transition(order, zinc::oms::Event::Submit),
                   zinc::oms::OrderStatus::Submitted);
    expect_success(zinc::oms::StateMachine::transition(order, zinc::oms::Event::Accept),
                   zinc::oms::OrderStatus::Accepted);

    expect_success(
        zinc::oms::StateMachine::transition(order, zinc::oms::Event::PartialFill, 40),
        zinc::oms::OrderStatus::PartiallyFilled);
    EXPECT_EQ(order.filled_quantity, 40);

    expect_success(
        zinc::oms::StateMachine::transition(order, zinc::oms::Event::PartialFill, 60),
        zinc::oms::OrderStatus::Filled);
    EXPECT_EQ(order.filled_quantity, 100);
}

TEST(OmsStateMachineTest, EmptyAndInvalidInputReturnsError) {
    zinc::oms::Order empty_id;
    empty_id.quantity = 10;
    expect_failure(zinc::oms::StateMachine::transition(empty_id, zinc::oms::Event::Approve),
                   zinc::oms::TransitionErrorCode::IllegalTransition);

    zinc::oms::Order zero_qty{.order_id = "ORD-2", .quantity = 0};
    expect_failure(zinc::oms::StateMachine::transition(zero_qty, zinc::oms::Event::Approve),
                   zinc::oms::TransitionErrorCode::IllegalTransition);

    zinc::oms::Order terminal = make_order();
    terminal.status = zinc::oms::OrderStatus::Filled;
    expect_failure(zinc::oms::StateMachine::transition(terminal, zinc::oms::Event::Cancel),
                   zinc::oms::TransitionErrorCode::TerminalState);
}

TEST(OmsStateMachineTest, AllLegalTransitionsSucceed) {
    struct TransitionCase {
        zinc::oms::OrderStatus from;
        zinc::oms::Event event;
        zinc::oms::OrderStatus to;
        int64_t fill_quantity;
    };

    const std::vector<TransitionCase> legal = {
        {zinc::oms::OrderStatus::PendingApproval, zinc::oms::Event::Approve,
         zinc::oms::OrderStatus::Approved, 0},
        {zinc::oms::OrderStatus::PendingApproval, zinc::oms::Event::Reject,
         zinc::oms::OrderStatus::Rejected, 0},
        {zinc::oms::OrderStatus::Approved, zinc::oms::Event::Submit,
         zinc::oms::OrderStatus::Submitted, 0},
        {zinc::oms::OrderStatus::Approved, zinc::oms::Event::Reject,
         zinc::oms::OrderStatus::Rejected, 0},
        {zinc::oms::OrderStatus::Submitted, zinc::oms::Event::Accept,
         zinc::oms::OrderStatus::Accepted, 0},
        {zinc::oms::OrderStatus::Submitted, zinc::oms::Event::Reject,
         zinc::oms::OrderStatus::Rejected, 0},
        {zinc::oms::OrderStatus::Submitted, zinc::oms::Event::Cancel,
         zinc::oms::OrderStatus::Cancelled, 0},
        {zinc::oms::OrderStatus::Submitted, zinc::oms::Event::Expire,
         zinc::oms::OrderStatus::Expired, 0},
        {zinc::oms::OrderStatus::Accepted, zinc::oms::Event::Cancel,
         zinc::oms::OrderStatus::Cancelled, 0},
        {zinc::oms::OrderStatus::Accepted, zinc::oms::Event::Expire,
         zinc::oms::OrderStatus::Expired, 0},
        {zinc::oms::OrderStatus::Accepted, zinc::oms::Event::Reject,
         zinc::oms::OrderStatus::Rejected, 0},
        {zinc::oms::OrderStatus::PartiallyFilled, zinc::oms::Event::Cancel,
         zinc::oms::OrderStatus::Cancelled, 0},
        {zinc::oms::OrderStatus::PartiallyFilled, zinc::oms::Event::Expire,
         zinc::oms::OrderStatus::Expired, 0},
    };

    for (const TransitionCase& transition_case : legal) {
        zinc::oms::Order order = make_order();
        order.status = transition_case.from;
        const auto result = zinc::oms::StateMachine::transition(
            order, transition_case.event, transition_case.fill_quantity);
        ASSERT_TRUE(result.has_value());
        EXPECT_EQ(order.status, transition_case.to);
    }
}

TEST(OmsStateMachineTest, IllegalTransitionsAlwaysFail) {
    const std::vector<std::pair<zinc::oms::OrderStatus, zinc::oms::Event>> illegal = {
        {zinc::oms::OrderStatus::PendingApproval, zinc::oms::Event::Submit},
        {zinc::oms::OrderStatus::PendingApproval, zinc::oms::Event::Accept},
        {zinc::oms::OrderStatus::Approved, zinc::oms::Event::Approve},
        {zinc::oms::OrderStatus::Submitted, zinc::oms::Event::Approve},
        {zinc::oms::OrderStatus::Submitted, zinc::oms::Event::PartialFill},
        {zinc::oms::OrderStatus::Accepted, zinc::oms::Event::Approve},
        {zinc::oms::OrderStatus::PartiallyFilled, zinc::oms::Event::Submit},
    };

    for (const auto& [status, event] : illegal) {
        zinc::oms::Order order = make_order();
        order.status = status;
        const auto result = zinc::oms::StateMachine::transition(order, event, 10);
        ASSERT_FALSE(result.has_value()) << "status=" << static_cast<int>(status)
                                         << " event=" << static_cast<int>(event);
        EXPECT_EQ(result.error().code, zinc::oms::TransitionErrorCode::IllegalTransition);
    }

    std::mt19937_64 rng(0x0A5342ULL);
    std::uniform_int_distribution<int> event_dist(0, 7);
    const std::vector<zinc::oms::OrderStatus> terminal_states = {
        zinc::oms::OrderStatus::Filled, zinc::oms::OrderStatus::Cancelled,
        zinc::oms::OrderStatus::Rejected, zinc::oms::OrderStatus::Expired};

    for (int trial = 0; trial < 200; ++trial) {
        zinc::oms::Order order = make_order(50);
        order.status = terminal_states[static_cast<std::size_t>(trial % terminal_states.size())];
        const auto event = static_cast<zinc::oms::Event>(event_dist(rng));
        const auto result = zinc::oms::StateMachine::transition(order, event, 1);
        ASSERT_FALSE(result.has_value());
        EXPECT_EQ(result.error().code, zinc::oms::TransitionErrorCode::TerminalState);
    }
}

TEST(OmsStateMachineTest, NumericalStabilityAgainstReferenceLiteral) {
    constexpr int64_t kReferenceFilledQuantity = 42;
    zinc::oms::Order order = make_order(100);
    order.status = zinc::oms::OrderStatus::Accepted;

    const auto result = zinc::oms::StateMachine::transition(
        order, zinc::oms::Event::PartialFill, kReferenceFilledQuantity);
    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(order.filled_quantity, kReferenceFilledQuantity);
    EXPECT_EQ(result->filled_quantity, kReferenceFilledQuantity);
    EXPECT_EQ(order.status, zinc::oms::OrderStatus::PartiallyFilled);
}
