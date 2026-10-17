"""Root agent: the orchestrator delegating to the six specialists as AgentTools."""

import logging

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from mil_agent.agents.config import AGENT_PROMPTS_DIR, ROOT_AGENT_PROMPT, agent_config, model_for
from mil_agent.agents.subagents import SUB_AGENTS
from mil_agent.prompts import Prompt
from mil_agent.tools import tracker

_root_instruction = Prompt(f"{AGENT_PROMPTS_DIR}/{ROOT_AGENT_PROMPT}").render(
    {"specialists": [{"name": a.name, "description": a.description} for a in SUB_AGENTS]}
)

root_agent = Agent(
    name="investigation_orchestrator",
    model=model_for("orchestrator"),
    description="Routes a failed-payment complaint through six specialist agents and enforces the officer's approval.",
    instruction=_root_instruction,
    tools=[*(AgentTool(agent=a) for a in SUB_AGENTS), tracker.get_case],
    generate_content_config=agent_config,
)

logging.info("Root agent loaded. Specialists: %s", [a.name for a in SUB_AGENTS])
