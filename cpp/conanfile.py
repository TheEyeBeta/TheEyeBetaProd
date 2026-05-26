"""Conan 2 recipe for the zinc C++ stack.

Pinned versions match ``docs/architecture.md`` where Conan Center still hosts the
recipe. Substitutes (noted inline) apply when upstream recipes were removed from
center2 but a compatible replacement exists.
"""

from conan import ConanFile


class ZincCppConan(ConanFile):
    """Third-party dependencies for zinc (CMake + CMakeDeps)."""

    name = "zinc-cpp"
    version = "0.1.0"
    license = "Proprietary"
    settings = "os", "compiler", "build_type", "arch"
    generators = "CMakeDeps", "CMakeToolchain"

    default_options = {
        "arrow/*:shared": False,
        "arrow/*:parquet": True,
        "arrow/*:with_flight_rpc": False,
        "arrow/*:with_gcs": False,
        "arrow/*:with_s3": False,
        "arrow/*:compute": False,
        "grpc/*:shared": False,
        "grpc/*:csharp_plugin": False,
        "grpc/*:node_plugin": False,
        "grpc/*:php_plugin": False,
        "grpc/*:python_plugin": False,
        "grpc/*:ruby_plugin": False,
        "protobuf/*:shared": False,
        "quantlib/*:shared": False,
    }

    def requirements(self) -> None:
        """Declare runtime and test dependencies from Conan Center."""
        self.requires("eigen/3.4.0")
        self.requires("abseil/20240722.0")
        self.requires("fmt/10.2.1")
        self.requires("spdlog/1.14.1")
        self.requires("nlohmann_json/3.11.3")
        self.requires("gtest/1.16.0")  # spec: 1.15.2 (removed from Conan Center)
        self.requires("benchmark/1.9.0")
        self.requires("arrow/19.0.1")  # spec: 17.0.0 (removed from Conan Center)
        self.requires("protobuf/5.29.6")  # spec: 3.21.12; required by grpc/1.69.0
        self.requires("grpc/1.69.0")  # spec: 1.65.4 (removed from Conan Center)
        self.requires("quantlib/1.30")  # spec: 1.36 (removed from Conan Center)
        self.requires("nanobind/2.12.0")

    def configure(self) -> None:
        """Align with project C++20 requirement."""
        self.settings.compiler.set_safe("cppstd", "20")
