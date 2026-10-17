"""Shared configuration for all agents."""

from google.genai import types

from mil_agent import settings
from mil_agent.agents.fallback_llm import FallbackLlm
from mil_agent.agents.scripted_llm import ScriptedLlm

# Agent configuration: deterministic, we never want creative arithmetic
agent_config = types.GenerateContentConfig(temperature=0.0)

# Prompt directory
AGENT_PROMPTS_DIR = "agents"

# Prompt template names
ROOT_AGENT_PROMPT = "root_agent.jinja2"
TIMELINE_RECONSTRUCTOR_PROMPT = "timeline_reconstructor_agent.jinja2"
FAILURE_DIAGNOSER_PROMPT = "failure_diagnoser_agent.jinja2"
POLICY_RIGHTS_PROMPT = "policy_rights_agent.jinja2"
EVIDENCE_COMPLAINT_PROMPT = "evidence_complaint_agent.jinja2"
CASE_TRACKER_PROMPT = "case_tracker_agent.jinja2"
ESCALATION_PROMPT = "escalation_agent.jinja2"


def model_for(role: str):
    """Real Gemini when a key is set, otherwise the offline scripted model for that role."""
    if settings.has_api_key():
        # Gemini first; falls back to the offline helper if the key's quota runs out.
        return FallbackLlm(model=f"fallback-{role}", role=role)
    return ScriptedLlm(model=f"scripted-{role}", role=role)
