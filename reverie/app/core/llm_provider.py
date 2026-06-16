from typing import Optional, List, Any
from langchain_litellm import ChatLiteLLM
from .config import (
    get_llm_model,
    get_llm_api_key,
    get_llm_base_url,
    get_llm_rpm,
    llm_limiter
)

def get_llm(temperature: float = 0, tools: Optional[List[Any]] = None):
    """
    Returns a ChatLiteLLM instance based on the current configuration.
    Supports 100+ providers (Gemini, OpenAI, Anthropic, etc.) via LiteLLM.
    """
    # Update rate limiter based on JIT config
    llm_limiter.max_rate = get_llm_rpm()

    model = get_llm_model()
    api_key = get_llm_api_key()
    base_url = get_llm_base_url()

    # ChatLiteLLM will automatically use provider-specific env vars (like OPENAI_API_KEY)
    # if api_key is not explicitly passed, but we pass it for clarity from our JIT config.
    llm = ChatLiteLLM(
        model=model,
        api_key=api_key,
        api_base=base_url,
        temperature=temperature,
    )

    if tools:
        return llm.bind_tools(tools)
    
    return llm
