"""
Tests for PubMedSubjectSearchBuilderTool (tools/mesh.py).

The tool translates a clinical scenario into a PubMed Simple Subject Search by
prompting an LLM. These tests mock the LLM factory so no network/auth is needed,
and verify:
1. The tool builds its LLM through the shared llm_factory (inheriting the
   service's LiteLLM-proxy + JWT authentication) rather than a hard-coded client.
2. _run() forwards the clinical scenario into the prompt and returns the LLM's
   response unchanged.
3. _run() degrades gracefully, returning an error string instead of raising when
   the LLM call fails.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Must set env vars before importing any crewai / ivcap modules.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("IVCAP_BASE_URL", "http://localhost:8077")

# Ensure project root is on sys.path so imports resolve correctly.
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    """A stand-in LLM whose .call() returns a canned PubMed search response."""
    llm = MagicMock()
    llm.call.return_value = (
        "### 4. Simple Subject Search Query\n"
        "high blood pressure patient education exercise"
    )
    return llm


@pytest.fixture
def patched_factory(mock_llm):
    """
    Patch tools.mesh.get_llm_factory so the tool's __init__ builds the mock LLM
    instead of reaching out to the real LiteLLM proxy. Yields the factory mock so
    tests can assert on how create_llm() was invoked.
    """
    factory = MagicMock()
    factory.create_llm.return_value = mock_llm
    with patch("tools.mesh.get_llm_factory", return_value=factory):
        yield factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tool_metadata(patched_factory):
    """Tool exposes a stable name and the expected input schema."""
    from tools.mesh import PubMedSubjectSearchBuilderInput, PubMedSubjectSearchBuilderTool

    tool = PubMedSubjectSearchBuilderTool()

    assert tool.name == "PubMed EBP Search Builder"
    assert tool.args_schema is PubMedSubjectSearchBuilderInput


def test_init_builds_llm_through_factory(patched_factory, mock_llm):
    """
    The tool must construct its LLM via the shared llm_factory, passing the JWT
    so the call authenticates through the LiteLLM proxy like the rest of the
    service, with a deterministic temperature of 0.
    """
    from tools.mesh import PubMedSubjectSearchBuilderTool

    tool = PubMedSubjectSearchBuilderTool(jwt_token="test-jwt-123")

    patched_factory.create_llm.assert_called_once()
    _, kwargs = patched_factory.create_llm.call_args
    assert kwargs["jwt_token"] == "test-jwt-123"
    assert kwargs["temperature"] == 0
    assert kwargs["model"]  # model resolved from env (LITELLM_DEFAULT_MODEL / default)
    assert tool._llm is mock_llm


def test_run_returns_llm_response_and_embeds_scenario(patched_factory, mock_llm):
    """
    _run() returns the LLM response verbatim and embeds the clinical scenario in
    the prompt sent to the LLM.
    """
    from tools.mesh import PubMedSubjectSearchBuilderTool

    tool = PubMedSubjectSearchBuilderTool()
    scenario = "Does patient education reduce blood pressure in hypertensive adults?"

    result = tool._run(scenario=scenario)

    assert result == mock_llm.call.return_value

    # The scenario text must be passed through into the prompt.
    _, call_kwargs = mock_llm.call.call_args
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "user"
    assert scenario in messages[0]["content"]


def test_run_returns_error_string_on_llm_failure(patched_factory, mock_llm):
    """
    If the LLM call raises, _run() returns a descriptive error string rather than
    propagating the exception (so the agent run isn't crashed by a tool error).
    """
    from tools.mesh import PubMedSubjectSearchBuilderTool

    mock_llm.call.side_effect = RuntimeError("proxy unreachable")
    tool = PubMedSubjectSearchBuilderTool()

    result = tool._run(scenario="any scenario")

    assert "Error building PubMed search" in result
    assert "proxy unreachable" in result
