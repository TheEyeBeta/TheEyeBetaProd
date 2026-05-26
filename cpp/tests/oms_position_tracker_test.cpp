/**
 * @file   oms_position_tracker_test.cpp
 * @brief  Unit tests for zinc::oms::PositionTracker.
 */

#include "zinc/oms/position_tracker.hpp"

#include <cstdint>
#include <thread>
#include <vector>

#include <gtest/gtest.h>

namespace {

constexpr int64_t kConcurrentFillCount = 1000;
constexpr int kConcurrentThreads = 10;
constexpr int64_t kReferenceNetPosition = 10000;  // 10 * 1000 * +1

}  // namespace

TEST(OmsPositionTrackerTest, HappyPathHandComputedNetPosition) {
    zinc::oms::PositionTracker tracker;
    ASSERT_TRUE(tracker.apply_fill("SPY", 4000));
    ASSERT_TRUE(tracker.apply_fill("SPY", 6000));
    EXPECT_EQ(tracker.leg_position("SPY"), 10000);
    EXPECT_EQ(tracker.net_position(), 10000);
}

TEST(OmsPositionTrackerTest, EmptyLegIdRejected) {
    zinc::oms::PositionTracker tracker(5);
    EXPECT_FALSE(tracker.apply_fill("", 100));
    EXPECT_EQ(tracker.net_position(), 5);
}

TEST(OmsPositionTrackerTest, SingleFillUpdatesPosition) {
    zinc::oms::PositionTracker tracker;
    ASSERT_TRUE(tracker.apply_fill("LEG-A", 1));
    EXPECT_EQ(tracker.leg_position("LEG-A"), 1);
    EXPECT_EQ(tracker.net_position(), 1);
}

TEST(OmsPositionTrackerTest, ConcurrentFillsProduceDeterministicPosition) {
    zinc::oms::PositionTracker tracker;
    std::vector<std::thread> workers;
    workers.reserve(static_cast<std::size_t>(kConcurrentThreads));

    for (int worker = 0; worker < kConcurrentThreads; ++worker) {
        workers.emplace_back([&tracker]() {
            for (int fill = 0; fill < kConcurrentFillCount; ++fill) {
                ASSERT_TRUE(tracker.apply_fill("SPY", 1));
            }
        });
    }

    for (std::thread& worker : workers) {
        worker.join();
    }

    EXPECT_EQ(tracker.leg_position("SPY"), kReferenceNetPosition);
    EXPECT_EQ(tracker.net_position(), kReferenceNetPosition);
}

TEST(OmsPositionTrackerTest, NumericalStabilityAgainstReferenceLiteral) {
    constexpr int64_t kLiteralPosition = kReferenceNetPosition;
    zinc::oms::PositionTracker tracker;

    for (int64_t index = 0; index < kLiteralPosition; ++index) {
        ASSERT_TRUE(tracker.apply_fill("LIT", 1));
    }

    EXPECT_EQ(tracker.leg_position("LIT"), kLiteralPosition);
    EXPECT_EQ(tracker.net_position(), kLiteralPosition);
}
