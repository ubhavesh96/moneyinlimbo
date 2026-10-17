import pytest

from mil_agent.agents import config
from mil_agent.prompts import Prompt

TEMPLATES = [config.TIMELINE_RECONSTRUCTOR_PROMPT, config.FAILURE_DIAGNOSER_PROMPT,
             config.POLICY_RIGHTS_PROMPT, config.EVIDENCE_COMPLAINT_PROMPT,
             config.CASE_TRACKER_PROMPT, config.ESCALATION_PROMPT]


@pytest.mark.parametrize("name", TEMPLATES)
def test_specialist_prompts_render_with_shared_rules(name):
    text = Prompt(f"agents/{name}").render({})
    assert "case_id" in text and "officer" in text.lower() and "arithmetic" in text
    # ADK treats {name} in an instruction as a state variable, so braces must not appear.
    assert "{" not in text and "}" not in text


def test_root_prompt_lists_every_specialist():
    from mil_agent.agents.subagents import SUB_AGENTS

    text = Prompt(f"agents/{config.ROOT_AGENT_PROMPT}").render(
        {"specialists": [{"name": a.name, "description": a.description} for a in SUB_AGENTS]})
    assert all(a.name in text for a in SUB_AGENTS)
    assert "RouteDecision" in text and "{" not in text


def test_missing_template_fails_loudly():
    with pytest.raises(RuntimeError):
        Prompt("agents/does_not_exist.jinja2")
