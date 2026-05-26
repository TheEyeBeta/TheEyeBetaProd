"""agent_runtime — run agents against market snapshots."""

__all__ = ["AgentRunner", "SnapshotLoader", "run_agent"]


def __getattr__(name: str) -> type:  # noqa: ANN401
    """Lazy exports to avoid importing zinc_native at package import time."""
    if name == "AgentRunner":
        from agent_runtime.runner import AgentRunner

        return AgentRunner
    if name == "run_agent":
        from agent_runtime.runner import run_agent

        return run_agent
    if name == "SnapshotLoader":
        from agent_runtime.snapshot_loader import SnapshotLoader

        return SnapshotLoader
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
