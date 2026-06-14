from typing import Optional, List, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from .config import (
    LLM_PROVIDER,
    GEMINI_API_KEY,
    GEMINI_MODEL_TYPE,
    OPENAI_API_KEY,
    OPENAI_MODEL_NAME,
    OPENAI_BASE_URL,
)


def get_llm(temperature: float = 0, tools: Optional[List[Any]] = None):
    """
    Returns an LLM instance based on the LLM_PROVIDER configuration.
    Supports Gemini and OpenAI-compatible providers (DeepSeek, etc.).
    """
    print("USing provider:", LLM_PROVIDER)
    if LLM_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set.")

        llm = ChatOpenAI(
            model=OPENAI_MODEL_NAME,
            openai_api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            temperature=temperature,
        )
    else:
        # Default to Gemini
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not set.")

        llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL_TYPE,
            google_api_key=GEMINI_API_KEY,
            temperature=temperature,
        )

    if tools:
        return llm.bind_tools(tools)

    return llm
