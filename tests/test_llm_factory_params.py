"""
Tests for LLMFactory parameter handling (llm_factory.py).

The factory must construct each LLM with only the parameters the target model
supports. In particular, reasoning models (OpenAI o-series, Anthropic
extended-thinking, Google Gemini thinking models) reject sampling parameters
such as temperature and top_p, so those must NOT appear in the config passed to
the LLM constructor.

These tests patch llm_factory.LLM with a MagicMock and inspect the kwargs it is
constructed with, so they assert on exactly what gets sent in the LLM config
without any network/auth or dependence on the real LLM internals.
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
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def factory():
    """
    An LLMFactory pinned to the LiteLLM-proxy + JWT path (Tier 1) so tests are
    deterministic regardless of the ambient environment.
    """
    from llm_factory import LLMFactory

    f = LLMFactory()
    f.litellm_proxy_url = "http://litellm-proxy.test"
    return f


def build_config(factory, **kwargs):
    """
    Call create_llm with a patched LLM and return the kwargs the LLM constructor
    received (i.e. the actual config sent to the LLM).
    """
    with patch("llm_factory.LLM") as mock_llm:
        factory.create_llm(jwt_token="jwt-123", **kwargs)
        assert mock_llm.call_count == 1, "LLM should be constructed exactly once"
        _, call_kwargs = mock_llm.call_args
        return call_kwargs


# ---------------------------------------------------------------------------
# Reasoning models: sampling params must be stripped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "o3",
        "o3-mini",
        "o3-mini-2025-01-31",          # dated variant
        "openai/o1-preview",           # provider-prefixed
        "claude-3-7-sonnet",
        "claude-sonnet-4-5-20250929",  # dated variant
        "gemini-2.5-pro",
        "gemini-2.0-flash-thinking",
    ],
)
def test_reasoning_models_drop_sampling_params(factory, model):
    """temperature/top_p (and other sampling params) must not reach the LLM config."""
    config = build_config(
        factory,
        model=model,
        temperature=0.7,
        top_p=0.9,
        presence_penalty=0.1,
        frequency_penalty=0.2,
        max_tokens=1000,
    )

    assert "temperature" not in config
    assert "top_p" not in config
    assert "presence_penalty" not in config
    assert "frequency_penalty" not in config
    # The model and unrelated params must still be forwarded.
    assert config["model"] == model
    assert config["max_tokens"] == 1000


def test_reasoning_model_with_no_sampling_params_is_unaffected(factory):
    """A reasoning model called without sampling params still builds normally."""
    config = build_config(factory, model="o3", max_tokens=500)

    assert config["model"] == "o3"
    assert config["max_tokens"] == 500
    assert "temperature" not in config


# ---------------------------------------------------------------------------
# Non-reasoning models: sampling params must be preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    [
        "gpt-4o",          # note: ends in 'o' but is NOT an o-series reasoning model
        "gpt-4.1",
        "claude-3-5-sonnet-20241022",
        "gemini-1.5-pro",
    ],
)
def test_standard_models_keep_sampling_params(factory, model):
    """Standard chat models must receive temperature/top_p unchanged."""
    config = build_config(factory, model=model, temperature=0.7, top_p=0.9)

    assert config["model"] == model
    assert config["temperature"] == 0.7
    assert config["top_p"] == 0.9


# ---------------------------------------------------------------------------
# Auth wiring is preserved alongside param filtering
# ---------------------------------------------------------------------------


def test_jwt_auth_config_present_for_reasoning_model(factory):
    """Dropping sampling params must not disturb the proxy + JWT auth wiring."""
    config = build_config(factory, model="o3", temperature=0.5)

    assert config["base_url"] == "http://litellm-proxy.test"
    assert config["api_key"] == "jwt-123"
    assert config["default_headers"]["Authorization"] == "Bearer jwt-123"
    assert "temperature" not in config


# ---------------------------------------------------------------------------
# Unit-level checks on the helpers
# ---------------------------------------------------------------------------


def test_filter_unsupported_params_does_not_mutate_input():
    """filter_unsupported_params returns a new dict and leaves the original intact."""
    from llm_factory import filter_unsupported_params

    original = {"temperature": 0.7, "max_tokens": 100}
    result = filter_unsupported_params("o3", original)

    assert original == {"temperature": 0.7, "max_tokens": 100}  # unchanged
    assert result == {"max_tokens": 100}


# ---------------------------------------------------------------------------
# Only supported parameters are passed through
# ---------------------------------------------------------------------------


def test_unsupported_params_are_dropped(factory):
    """Caller-supplied params not accepted by the LLM constructor must be dropped."""
    config = build_config(
        factory,
        model="gpt-4o",
        temperature=0.7,          # supported
        max_tokens=1000,          # supported
        made_up_param=123,        # unsupported
        verbose=True,             # unsupported (crew/agent option, not an LLM param)
    )

    assert "made_up_param" not in config
    assert "verbose" not in config
    # Supported params (and the factory-injected auth keys) still come through.
    assert config["temperature"] == 0.7
    assert config["max_tokens"] == 1000
    assert config["model"] == "gpt-4o"
    assert config["api_key"] == "jwt-123"


def test_supported_params_all_pass_through(factory):
    """A spread of valid LLM params must all reach the config unchanged."""
    config = build_config(
        factory,
        model="gpt-4o",
        temperature=0.3,
        top_p=0.8,
        max_tokens=2000,
        seed=42,
        reasoning_effort="high",
    )

    for key, value in {
        "temperature": 0.3,
        "top_p": 0.8,
        "max_tokens": 2000,
        "seed": 42,
        "reasoning_effort": "high",
    }.items():
        assert config[key] == value


def test_validate_supported_params_does_not_mutate_input():
    """validate_supported_params returns a new dict and leaves the original intact."""
    from llm_factory import validate_supported_params

    original = {"temperature": 0.7, "bogus": 1}
    result = validate_supported_params(original)

    assert original == {"temperature": 0.7, "bogus": 1}  # unchanged
    assert result == {"temperature": 0.7}


def test_is_reasoning_model_detection():
    """Provider prefixes and dated variants are recognised; standard models are not."""
    from llm_factory import _is_reasoning_model

    assert _is_reasoning_model("o3-mini-2025-01-31")
    assert _is_reasoning_model("openai/o1")
    assert _is_reasoning_model("claude-sonnet-4-5-20250929")
    assert _is_reasoning_model("gemini-2.5-flash")

    assert not _is_reasoning_model("gpt-4o")
    assert not _is_reasoning_model("claude-3-5-sonnet-20241022")
    assert not _is_reasoning_model(None)
