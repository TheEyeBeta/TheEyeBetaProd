/**
 * @file   expected.hpp
 * @brief  std::expected-compatible result type for C++20 builds.
 */

#pragma once

#include <utility>
#include <variant>

namespace zinc::oms::detail {

template <typename E>
class Unexpected {
  public:
    explicit Unexpected(E error) : error_(std::move(error)) {}

    [[nodiscard]] const E& error() const& { return error_; }
    [[nodiscard]] E& error() & { return error_; }
    [[nodiscard]] E&& error() && { return std::move(error_); }

  private:
    E error_;
};

template <typename E>
Unexpected(E) -> Unexpected<E>;

template <typename T, typename E>
class Expected {
  public:
    Expected(const Expected&) = default;
    Expected(Expected&&) = default;
    Expected& operator=(const Expected&) = default;
    Expected& operator=(Expected&&) = default;
    ~Expected() = default;

    Expected(const T& value) : storage_(value) {}  // NOLINT
    Expected(T&& value) : storage_(std::move(value)) {}  // NOLINT
    Expected(Unexpected<E> error) : storage_(std::move(error.error())) {}  // NOLINT

    [[nodiscard]] bool has_value() const noexcept { return storage_.index() == 0; }
    [[nodiscard]] explicit operator bool() const noexcept { return has_value(); }

    [[nodiscard]] T& value() & { return std::get<0>(storage_); }
    [[nodiscard]] const T& value() const& { return std::get<0>(storage_); }
    [[nodiscard]] T&& value() && { return std::get<0>(std::move(storage_)); }

    [[nodiscard]] E& error() & { return std::get<1>(storage_); }
    [[nodiscard]] const E& error() const& { return std::get<1>(storage_); }
    [[nodiscard]] E&& error() && { return std::get<1>(std::move(storage_)); }

  private:
    std::variant<T, E> storage_;
};

template <typename E>
Unexpected<std::decay_t<E>> unexpected(E&& error) {
    return Unexpected<std::decay_t<E>>(std::forward<E>(error));
}

}  // namespace zinc::oms::detail

#if defined(__cpp_lib_expected) && __cpp_lib_expected >= 202211L

#include <expected>

namespace zinc::oms {
template <typename T, typename E>
using expected = std::expected<T, E>;
using std::unexpected;
}  // namespace zinc::oms

#else

namespace zinc::oms {
template <typename T, typename E>
using expected = detail::Expected<T, E>;
using detail::unexpected;
}  // namespace zinc::oms

#endif
