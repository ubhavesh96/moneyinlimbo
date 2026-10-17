from mil_agent import settings
from mil_agent.agents.config import model_for
from mil_agent.agents.scripted_llm import ScriptedLlm


def test_offline_mode_without_key():
    assert settings.has_api_key() is False


def test_model_for_returns_scripted_model_offline():
    assert isinstance(model_for("policy_rights"), ScriptedLlm)
