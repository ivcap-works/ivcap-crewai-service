"""
LLM Factory for CrewAI with LiteLLM Proxy Integration
Handles JWT token authentication and multi-tier fallback

Created: Fresh implementation for task context chaining feature
Changes:
- Replaces previous version - adds comprehensive JWT auth with 3-tier fallback
- Added create_embedder_config method for JWT-authenticated embeddings via LiteLLM proxy
- Added four behaviour-bound LLM profiles (low/medium/high thinking, fast writer)
  resolved through a profile registry
"""

import os
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Union
from crewai import LLM
from crewai.rag.embeddings.providers.openai import OpenAIProviderSpec
from ivcap_service import getLogger

logger = getLogger("app.llm_factory")


# Parameters accepted by CrewAI's LLM constructor. Caller-supplied params are
# validated against this set before instantiation so that typos or unsupported
# options are not silently forwarded to the provider. Keep this list in sync with
# CrewAI's LLM.__init__ signature if the library is upgraded.
SUPPORTED_LLM_PARAMS = frozenset({
    "model", "timeout", "temperature", "top_p", "n", "stop",
    "max_completion_tokens", "max_tokens", "presence_penalty",
    "frequency_penalty", "logit_bias", "response_format", "seed",
    "logprobs", "top_logprobs", "base_url", "api_base", "api_version",
    "api_key", "callbacks", "reasoning_effort", "stream",
})


def validate_supported_params(params: dict) -> dict:
    """
    Drop any caller-supplied parameters not accepted by the LLM constructor.

    Returns a new dict containing only supported parameters; a warning is logged
    for each dropped parameter. The input dict is left unmodified. Note: keys the
    factory injects itself (e.g. default_headers) are added after this check and
    are intentionally not validated here.
    """
    unsupported = [k for k in params if k not in SUPPORTED_LLM_PARAMS]
    if unsupported:
        logger.warning(
            "Dropping unsupported LLM parameter(s): %s. Supported parameters: %s",
            ", ".join(sorted(unsupported)),
            ", ".join(sorted(SUPPORTED_LLM_PARAMS)),
        )
        return {k: v for k, v in params.items() if k in SUPPORTED_LLM_PARAMS}
    return dict(params)


# Reasoning models reject the standard sampling parameters (temperature, top_p,
# etc.); including them in the request causes the provider API to error. They must
# be stripped before the LLM is constructed rather than relying on
# litellm.drop_params. Matched as a prefix against the (provider-stripped) model
# name so versioned/dated variants (e.g. "o3-mini-2025-01-31",
# "claude-sonnet-4-5-20250929") are covered.
#
# NOTE: Only OpenAI o-series models reject these params outright. Anthropic and
# Gemini reasoning models technically *accept* temperature in some modes - e.g.
# Anthropic requires temperature=1 (and disallows top_p) when extended thinking is
# enabled, rather than rejecting temperature entirely. We currently strip sampling
# params uniformly for all reasoning models below for simplicity. If finer-grained
# behaviour is needed in the future (e.g. forcing temperature=1 for Anthropic
# thinking instead of dropping it), split this into per-provider handling.
REASONING_MODELS = (
    # OpenAI o-series
    "o1",
    "o1-mini",
    "o1-preview",
    "o1-pro",
    "o3",
    "o3-mini",
    "o3-pro",
    "o4-mini",
    "gpt-5",
    "gpt-5.1",
    # Anthropic extended-thinking models
    "claude-3-7-sonnet",
    "claude-opus-4",
    "claude-sonnet-4",
    "claude-haiku-4-5",
    # Google Gemini thinking models
    "gemini-2.0-flash-thinking",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
)

# Sampling / penalty parameters that reasoning models do not support.
REASONING_UNSUPPORTED_PARAMS = (
    "temperature",
    "top_p",
    "presence_penalty",
    "frequency_penalty",
    "logprobs",
    "top_logprobs",
    "logit_bias",
)

# Parameters only reasoning models understand. A profile can declare a thinking
# depth while the deployment has pointed that profile at a non-reasoning model
# (e.g. LITELLM_HIGH_THINKING_MODEL=gpt-4.1); the provider rejects
# reasoning_effort there, so it is dropped.
REASONING_ONLY_PARAMS = (
    "reasoning_effort",
)


def _is_reasoning_model(model: Optional[str]) -> bool:
    """Return True for reasoning models from OpenAI, Anthropic, or Google Gemini."""
    if not model:
        return False
    # Strip any provider prefix (e.g. "openai/o3-mini" -> "o3-mini").
    name = model.lower().split("/")[-1]
    return any(name.startswith(m) for m in REASONING_MODELS)


def filter_unsupported_params(model: Optional[str], params: dict) -> dict:
    """
    Drop parameters a given model does not support before constructing the LLM.

    Reasoning models do not accept sampling parameters such as temperature and
    top_p; non-reasoning models in turn do not accept reasoning_effort. Returns a
    new dict; the input is left unmodified.
    """
    drop = (
        REASONING_UNSUPPORTED_PARAMS if _is_reasoning_model(model)
        else REASONING_ONLY_PARAMS
    )
    unsupported = [p for p in drop if p in params]
    if unsupported:
        logger.info(
            "Model '%s' does not support param(s) %s; dropping them",
            model,
            ", ".join(unsupported),
        )
        return {k: v for k, v in params.items() if k not in drop}
    return dict(params)


# ============================================================================
# LLM PROFILES
# ============================================================================
#
# A profile is a named capability tier: a model plus the behaviour it is
# configured for. The behaviour (thinking depth, creativity, output length) is
# declared once and the request parameters are derived from it, so the two cannot
# drift apart. Call sites name a tier instead of a model.


class Thinking(IntEnum):
    """Deliberation depth. Ordered: higher == more thinking, slower, dearer."""

    NONE = 0     # direct generation, no deliberation
    LOW = 1      # quick decisions, short chain of thought
    MEDIUM = 2   # multi-step reasoning, planning, tool orchestration
    HIGH = 3     # deep analysis, ambiguous problems, careful synthesis


# Thinking depth -> provider reasoning_effort. NONE has no entry: no
# reasoning_effort is sent at all for non-deliberating profiles.
_REASONING_EFFORT = {
    Thinking.LOW: "low",
    Thinking.MEDIUM: "medium",
    Thinking.HIGH: "high",
}


@dataclass(frozen=True)
class LLMProfile:
    """
    A named capability tier: a model plus the behaviour it is configured for.

    The model is resolved from `env_var` so a deployment can repoint a tier
    without code changes; the behaviour is fixed in code because it is the
    contract call sites rely on.

    Attributes:
        name: Profile identifier, e.g. "high_thinking_model".
        env_var: Environment variable overriding the model for this tier.
        default_model: Model used when `env_var` is unset.
        thinking: Deliberation depth, bound to reasoning_effort.
        creativity: 0.0 (deterministic) .. 1.0 (exploratory), bound to
            temperature. Ignored by reasoning models, which reject temperature.
        max_output_tokens: Bound to max_tokens.
        purpose: What this tier is for; documentation for call sites.
    """

    name: str
    env_var: str
    default_model: str
    thinking: Thinking

    def model(self) -> str:
        """Resolve the model: profile env var, else the coded default."""
        return os.getenv(self.env_var) or self.default_model

    def llm_params(self, **overrides) -> dict:
        """
        Bind this profile's behaviour to LLM parameters, caller overrides last.

        Params the resolved model rejects are stripped later by
        `filter_unsupported_params`, so behaviour can be declared freely here.
        """
        params= {}
        effort = _REASONING_EFFORT.get(self.thinking)
        if effort:
            params["reasoning_effort"] = effort
        params.update(overrides)
        return params

    def build(
        self,
        factory: "LLMFactory",
        jwt_token: Optional[str] = None,
        model: Optional[str] = None,
        **overrides,
    ) -> LLM:
        """Create this profile's LLM via `factory`."""
        resolved = model or self.model()
        params = self.llm_params(**overrides)
        logger.info(
            "Building '%s' profile: model=%s, params=%s", self.name, resolved, params
        )
        return factory.create_llm(jwt_token=jwt_token, model=resolved, **params)


# The four supported tiers. The thinking tiers share one reasoning model and are
# separated by reasoning_effort; the writer tier uses a chat model. Override the
# model per environment with the env var of each profile.
#
# Note: gpt-5 is a reasoning model, so its temperature/creativity is stripped by
# filter_unsupported_params, and reasoning tokens count against max_tokens -
# hence the larger output budgets on the deeper tiers.
LOW_THINKING_MODEL = LLMProfile(
    name="low_thinking_model",
    env_var="LITELLM_LOW_THINKING_MODEL",
    default_model="gpt-5",
    thinking=Thinking.LOW
)

MEDIUM_THINKING_MODEL = LLMProfile(
    name="medium_thinking_model",
    env_var="LITELLM_MEDIUM_THINKING_MODEL",
    default_model="gpt-5",
    thinking=Thinking.MEDIUM
)

HIGH_THINKING_MODEL = LLMProfile(
    name="high_thinking_model",
    env_var="LITELLM_HIGH_THINKING_MODEL",
    default_model="gpt-5",
    thinking=Thinking.HIGH,
)

FAST_WRITER_MODEL = LLMProfile(
    name="fast_writer_model",
    env_var="LITELLM_FAST_WRITER_MODEL",
    default_model=os.getenv("LITELLM_DEFAULT_MODEL", "gpt-4.1"),
    thinking=Thinking.NONE
)

PROFILES: dict[str, LLMProfile] = {
    p.name: p for p in (
        LOW_THINKING_MODEL,
        MEDIUM_THINKING_MODEL,
        HIGH_THINKING_MODEL,
        FAST_WRITER_MODEL,
    )
}

# Anything accepted where a profile is expected.
ProfileRef = Union[str, LLMProfile]


def get_profile(profile: ProfileRef) -> LLMProfile:
    """
    Resolve a profile reference to a profile.

    Accepts a profile instance, its name ("high_thinking_model"), or the
    shorthand ("high_thinking").

    Raises:
        ValueError: If the name is not a known profile. Callers holding a value
            that may be either a profile name or a plain model name (e.g. an
            agent's `llm` field) should catch this and fall back to the model.
    """
    if isinstance(profile, LLMProfile):
        return profile
    key = str(profile).strip().lower()
    found = PROFILES.get(key) or PROFILES.get(f"{key}_model")
    if found is None:
        raise ValueError(
            f"Unknown LLM profile '{profile}'. Available: {', '.join(PROFILES)}"
        )
    return found


class LLMFactory:
    """
    Factory for creating LLM instances with authentication.
    
    Authentication Tiers:
        1. LiteLLM Proxy + JWT (preferred) → centralized auth, cost tracking
        2. LiteLLM Proxy without JWT → development/testing
        3. Direct OpenAI API → fallback for local dev
    
    LiteLLM Proxy Benefits:
        - Single JWT authenticates to all models (OpenAI, Anthropic, Google)
        - Per-user cost tracking and quotas
        - Model aliasing (e.g., "gpt-5" → actual model)
        - Centralized rate limiting
        - No API keys in service (stored in proxy)
    
    Usage:
        factory = LLMFactory()
        
        # With JWT (production)
        llm = factory.create_llm(jwt_token="eyJ...", model="gpt-4o")
        
        # Without JWT (development)
        llm = factory.create_llm(model="gpt-3.5-turbo")

        # By profile - model and params come from the profile's behaviour
        llm = factory.create_llm_for_profile("high_thinking", jwt_token="eyJ...")
    """
    litellm_proxy_url = os.getenv("LITELLM_PROXY")
    default_model = os.getenv("LITELLM_DEFAULT_MODEL", "gpt-4.1")
    fallback_model = os.getenv("LITELLM_FALLBACK_MODEL", "gpt-3.5-turbo")
    
    def create_llm(
        self,
        jwt_token: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> LLM:
        """
        Create LLM instance with proper authentication.
        
        Args:
            jwt_token: JWT token for LiteLLM proxy authentication
            model: Model name override (defaults to LITELLM_DEFAULT_MODEL)
            **kwargs: Additional LLM parameters (temperature, max_tokens, etc.)
        
        Returns:
            Configured LLM instance
        
        Raises:
            ValueError: If no valid configuration available
        
        Example:
            # Crew-level LLM
            crew_llm = factory.create_llm(
                jwt_token="eyJ...",
                model="gpt-4o",
                temperature=0.7,
                max_tokens=4000
            )
            
            # Agent-specific LLM
            agent_llm = factory.create_llm(
                jwt_token="eyJ...",
                model="claude-3-opus-20240229",  # Different model!
                temperature=0.5
            )
        """
        model = model or self.default_model

        # Validate caller-supplied params against the set the LLM constructor
        # accepts, then strip params the target model does not support (e.g.
        # temperature/top_p for reasoning models), so only supported parameters
        # are ever sent in the LLM config.
        kwargs = validate_supported_params(kwargs)
        kwargs = filter_unsupported_params(model, kwargs)

        # TIER 1: LiteLLM Proxy with JWT (PREFERRED)
        if self.litellm_proxy_url and jwt_token:
            logger.info("Creating LLM with LiteLLM proxy + JWT: %s", model)
            
            llm_config = {
                "model": model,
                "base_url": self.litellm_proxy_url,
                "api_key": jwt_token,  # JWT as API key (LiteLLM convention)
                "default_headers": {
                    "Authorization": f"Bearer {jwt_token}"  # Standard OAuth2
                },
                **kwargs
            }               
            try:
                llm = LLM(**llm_config)
                logger.info("✓ LLM created: %s via proxy with JWT", model)
                return llm
            except Exception as e:
                logger.warning("Failed to create LLM with proxy+JWT: %s", e)
                # Fall through to next tier
        
        # TIER 2: LiteLLM Proxy without JWT
        if self.litellm_proxy_url:
            logger.info("Creating LLM with LiteLLM proxy (no JWT): %s", model)
            
            llm_config = {
                "model": model,
                "base_url": self.litellm_proxy_url,
                **kwargs
            }
            
            try:
                llm = LLM(**llm_config)
                logger.info("✓ LLM created: %s via proxy without JWT", model)
                return llm
            except Exception as e:
                logger.warning("Failed to create LLM with proxy: %s", e)
                # Fall through to next tier
        
        # TIER 3: Direct OpenAI API (FALLBACK)
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            logger.info("Falling back to direct OpenAI API: %s", self.fallback_model)
            
            llm_config = {
                "model": self.fallback_model,
                "api_key": openai_key,
                **kwargs
            }
            
            try:
                llm = LLM(**llm_config)
                logger.warning(
                    "⚠ LLM created via direct OpenAI (not proxy): %s",
                    self.fallback_model,
                )
                return llm
            except Exception as e:
                logger.error("Failed to create LLM via OpenAI: %s", e)
        
        # NO VALID CONFIGURATION
        raise ValueError(
            "No valid LLM configuration available. Please set:\n"
            "  1. LITELLM_PROXY with JWT authentication (preferred), OR\n"
            "  2. OPENAI_API_KEY for direct API access (fallback)\n"
            f"Current state: proxy={self.litellm_proxy_url}, "
            f"jwt={'present' if jwt_token else 'missing'}, "
            f"openai_key={'present' if openai_key else 'missing'}"
        )

    def create_llm_for_profile(
        self,
        profile: ProfileRef,
        jwt_token: Optional[str] = None,
        model: Optional[str] = None,
        **overrides,
    ) -> LLM:
        """
        Create an LLM from one of the named profiles.

        Args:
            profile: Profile instance, name ("fast_writer_model") or shorthand
                ("fast_writer").
            jwt_token: JWT token for LiteLLM proxy authentication.
            model: Explicit model override, bypassing the profile's env var/default.
            **overrides: LLM parameter overrides applied over the profile behaviour.

        Returns:
            Configured LLM instance for that tier.

        Example:
            llm = factory.create_llm_for_profile(HIGH_THINKING_MODEL, jwt_token=jwt)
            llm = factory.create_llm_for_profile("low_thinking", jwt_token=jwt)
        """
        return get_profile(profile).build(
            self, jwt_token=jwt_token, model=model, **overrides
        )

    def create_embedder_config(self, jwt_token: str) -> dict:
        """
        Create embedder configuration for CrewAI embeddings.
        
        Uses the same LiteLLM proxy and JWT authentication as LLM calls.
        
        Args:
            jwt_token: JWT token for authentication
        
        Returns:
            Embedder configuration dictionary for CrewAI
        
        Example:
            embedder = factory.create_embedder_config("eyJ...")
            crew = Crew(..., embedder=embedder)
        """
        if not self.litellm_proxy_url:
            logger.warning("No litellm proxy URL configured, cannot create embedder")
            return None
        
        embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
        
        embedder_config : OpenAIProviderSpec = {
            "provider": "openai",
            "config": {
                "model_name": embedding_model,
                "api_key": jwt_token,
                "api_base": self.litellm_proxy_url,
                "default_headers": {
                    "Authorization": f"Bearer {jwt_token}"
                }
            }
        }
        
        logger.info("Created embedder config: model=%s, proxy=%s", embedding_model, self.litellm_proxy_url)
        return embedder_config


# Singleton instance
_llm_factory_instance = None


def get_llm_factory() -> LLMFactory:
    """
    Get or create singleton LLM factory instance.
    
    Returns:
        Shared LLMFactory instance
    
    Usage:
        factory = get_llm_factory()
        llm = factory.create_llm(jwt_token="...")
    """
    global _llm_factory_instance
    if _llm_factory_instance is None:
        _llm_factory_instance = LLMFactory()
    return _llm_factory_instance


