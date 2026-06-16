import os
from typing import Any, Dict, List, Optional
import litellm
from litellm import Router  # type: ignore[attr-defined]

from src.core.config import settings
from src.core.logging import logger

class LiteLLMClient:
    """Production-grade Wrapper for LiteLLM Router SDK.
    
    Provides in-process routing, automatic fallback handling, 
    token tracking, and cost calculation.
    """
    
    def __init__(self) -> None:
        # Set environment variables from settings so LiteLLM can pick them up
        if settings.GEMINI_API_KEY:
            os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY
        if settings.ANTHROPIC_API_KEY:
            os.environ["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY
        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
            
        # Initialize token and cost trackers
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_cost_usd: float = 0.0
        
        # Load configs
        litellm_cfg = settings.litellm_config
        model_list = litellm_cfg.get("model_list", [])
        fallbacks = litellm_cfg.get("fallbacks", [])
        
        # Clean/inject API keys into litellm params if present in settings
        self.cleaned_model_list = self._prepare_model_list(model_list)
        
        logger.info(
            "Initializing LiteLLM Router", 
            models=[m.get("model_name") for m in self.cleaned_model_list],
            fallbacks=fallbacks
        )
        
        try:
            self.router = Router(
                model_list=self.cleaned_model_list,
                fallbacks=fallbacks,
                num_retries=2,
                timeout=float(settings.guardrails.get("timeout_seconds", 30))
            )
        except Exception as e:
            logger.error("Failed to initialize LiteLLM Router", error=str(e))
            raise e

    def _prepare_model_list(self, model_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Ensures API keys are mapped correctly and environment variables resolved."""
        cleaned = []
        for entry in model_list:
            new_entry = entry.copy()
            params = new_entry.setdefault("litellm_params", {})
            
            # Map key using model names
            model_name = params.get("model", "")
            if "gemini" in model_name and settings.GEMINI_API_KEY:
                params["api_key"] = settings.GEMINI_API_KEY
            elif "claude" in model_name and settings.ANTHROPIC_API_KEY:
                params["api_key"] = settings.ANTHROPIC_API_KEY
            elif "gpt" in model_name and settings.OPENAI_API_KEY:
                params["api_key"] = settings.OPENAI_API_KEY
                
            cleaned.append(new_entry)
        return cleaned

    def completion(
        self, 
        model: str, 
        messages: List[Dict[str, str]], 
        **kwargs: Any
    ) -> Any:
        """Sends completion request using the router.
        
        Automatically handles fallback if the primary model fails.
        """
        logger.debug("Requesting LLM completion", model=model, message_count=len(messages))
        
        try:
            response = self.router.completion(
                model=model,
                messages=messages,
                **kwargs
            )
            
            # Extract usage and calculate cost
            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_tokens", 0)
                completion_tokens = getattr(usage, "completion_tokens", 0)
                
                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                
                try:
                    cost = litellm.completion_cost(completion_response=response) or 0.0
                    self.total_cost_usd += float(cost)
                    logger.debug(
                        "LLM execution success", 
                        model=model, 
                        prompt_tokens=prompt_tokens, 
                        completion_tokens=completion_tokens, 
                        cost_usd=cost
                    )
                except Exception:
                    logger.warning("Could not calculate completion cost", model=model)
            
            return response
            
        except Exception as e:
            logger.error("LLM completion request failed after retries and fallbacks", model=model, error=str(e))
            raise e

    def get_metrics(self) -> Dict[str, Any]:
        """Returns accumulated token and cost metrics."""
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "total_cost_usd": self.total_cost_usd
        }
