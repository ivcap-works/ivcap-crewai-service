"""
LLM Factory for CrewAI with LiteLLM Proxy Integration
Handles JWT token authentication and multi-tier fallback

Created: Fresh implementation for task context chaining feature
Changes: 
- Replaces previous version - adds comprehensive JWT auth with 3-tier fallback
- Added create_embedder_config method for JWT-authenticated embeddings via LiteLLM proxy
"""

import os
from typing import Optional
from crewai import LLM
from ivcap_service import getLogger

logger = getLogger("app.llm_factory")


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
    """
    
    def __init__(self, litellm_proxy_url: Optional[str] = None):
        """
        Initialize LLM factory.
        
        Args:
            litellm_proxy_url: Override proxy URL (defaults to env var)
        """
        self.litellm_proxy_url = (
            litellm_proxy_url or os.getenv("LITELLM_PROXY")
        )
        self.default_model = os.getenv("LITELLM_DEFAULT_MODEL", "gpt-4.1")
        self.fallback_model = os.getenv("LITELLM_FALLBACK_MODEL", "gpt-3.5-turbo")
        
        logger.info(
            f"LLMFactory initialized: "
            f"proxy={self.litellm_proxy_url}, "
            f"default_model={self.default_model}"
        )
    
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
        
        # TIER 1: LiteLLM Proxy with JWT (PREFERRED)
        if self.litellm_proxy_url and jwt_token:
            logger.info(f"Creating LLM with LiteLLM proxy + JWT: {model}")
            
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
                logger.info(f"✓ LLM created: {model} via proxy with JWT")
                return llm
            except Exception as e:
                logger.warning(f"Failed to create LLM with proxy+JWT: {e}")
                # Fall through to next tier
        
        # TIER 2: LiteLLM Proxy without JWT
        if self.litellm_proxy_url:
            logger.info(f"Creating LLM with LiteLLM proxy (no JWT): {model}")
            
            llm_config = {
                "model": model,
                "base_url": self.litellm_proxy_url,
                **kwargs
            }
            
            try:
                llm = LLM(**llm_config)
                logger.info(f"✓ LLM created: {model} via proxy without JWT")
                return llm
            except Exception as e:
                logger.warning(f"Failed to create LLM with proxy: {e}")
                # Fall through to next tier
        
        # TIER 3: Direct OpenAI API (FALLBACK)
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            logger.info(f"Falling back to direct OpenAI API: {self.fallback_model}")
            
            llm_config = {
                "model": self.fallback_model,
                "api_key": openai_key,
                **kwargs
            }
            
            try:
                llm = LLM(**llm_config)
                logger.warning(
                    f"⚠ LLM created via direct OpenAI (not proxy): "
                    f"{self.fallback_model}"
                )
                return llm
            except Exception as e:
                logger.error(f"Failed to create LLM via OpenAI: {e}")
        
        # NO VALID CONFIGURATION
        raise ValueError(
            "No valid LLM configuration available. Please set:\n"
            "  1. LITELLM_PROXY with JWT authentication (preferred), OR\n"
            "  2. OPENAI_API_KEY for direct API access (fallback)\n"
            f"Current state: proxy={self.litellm_proxy_url}, "
            f"jwt={'present' if jwt_token else 'missing'}, "
            f"openai_key={'present' if openai_key else 'missing'}"
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
        
        embedding_model = "text-embedding-3-small"
        
        embedder_config = {
            "provider": "openai",
            "config": {
                "model": embedding_model,
                "api_key": jwt_token,
                "api_base": self.litellm_proxy_url,
                "default_headers": {
                    "Authorization": f"Bearer {jwt_token}"
                }
            }
        }
        
        logger.info(f"Created embedder config: model={embedding_model}, proxy={self.litellm_proxy_url}")
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


