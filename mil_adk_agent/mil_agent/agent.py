"""Entry point for `adk web` / `adk run`: ADK looks for `root_agent` in `<package>.agent`."""

from mil_agent.agents.routers import root_agent

__all__ = ["root_agent"]
