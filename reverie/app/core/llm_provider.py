from typing import Optional, List, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from .config import (
    get_llm_provider,
    get_gemini_api_key,
    get_gemini_model,
    get_openai_api_key,
    get_openai_model,
    get_openai_base_url,
    get_llm_rpm,
    llm_limiter
)

def get_llm(temperature: float = 0, tools: Optional[List[Any]] = None):
    """
    Returns an LLM instance based on the current configuration.
    Uses JIT getters to ensure environment variables are loaded.
    """
    provider = get_llm_provider()
    
    # Update rate limiter based on JIT config
    llm_limiter.max_rate = get_llm_rpm()

    if provider == "openai":
        api_key = get_openai_api_key()
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set.")
        
        llm = ChatOpenAI(
            model=get_openai_model(),
            openai_api_key=api_key,
            base_url=get_openai_base_url(),
            temperature=temperature,
        )
    else:
        # Default to Gemini
        api_key = get_gemini_api_key()
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set. Please check your .env files (./.reverie/.env or ~/.reverie/.env)")
        
        llm = ChatGoogleGenerativeAI(
            model=get_gemini_model(),
            google_api_key=api_key,
            temperature=temperature,
        )

    if tools:
        return llm.bind_tools(tools)
    
    return llm
