"""Provider layer — DeepSeek (all text) + Gemini (all multimodal). No OpenAI.

- DeepSeek is OpenAI-API-compatible, so we drive it through langchain's
  ChatOpenAI by overriding base_url + api_key. It has no per-minute rate limit,
  so text roles can run at high concurrency.
- Gemini (free tier) is the ONLY multimodal option (image/audio/video). It is
  rate-limited, so it is reserved for multimodal calls only, with key rotation.
"""
import os
import threading
from itertools import cycle

from dotenv import load_dotenv, find_dotenv
from langchain_openai import ChatOpenAI

load_dotenv(find_dotenv(), override=True)

# ── DeepSeek (text workhorse) ─────────────────────────────────────────────────
DEEPSEEK_BASE = "https://api.deepseek.com"
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")

def deepseek_chat(temperature: float = 0.0, max_tokens: int = 4000) -> ChatOpenAI:
    """DeepSeek-V3 (`deepseek-chat`): fast, supports tool/function calling."""
    return ChatOpenAI(
        model="deepseek-chat",
        api_key=DEEPSEEK_KEY,
        base_url=DEEPSEEK_BASE,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=2,
        request_timeout=120,
    )

def deepseek_reasoner(max_tokens: int = 8000) -> ChatOpenAI:
    """DeepSeek-R1 (`deepseek-reasoner`): deepest reasoning, slow, no tools.

    Temperature / top_p are ignored by the reasoner server-side; we don't rely
    on them. `.content` carries the final answer (reasoning trace is separate).
    """
    return ChatOpenAI(
        model="deepseek-reasoner",
        api_key=DEEPSEEK_KEY,
        base_url=DEEPSEEK_BASE,
        max_tokens=max_tokens,
        max_retries=1,
        request_timeout=300,
    )

# ── Gemini (multimodal only) ──────────────────────────────────────────────────
def _load_gemini_keys():
    keys = []
    for i in range(1, 13):
        v = os.getenv(f"GEMINI_API_KEY{i}")
        if v and v.strip():
            keys.append(v.strip())
    g = os.getenv("GOOGLE_API_KEY")
    if g and g.strip():
        keys.append(g.strip())
    return list(dict.fromkeys(keys))  # dedupe, keep order

GEMINI_KEYS = _load_gemini_keys()
_key_lock = threading.Lock()
_key_cycle = cycle(GEMINI_KEYS) if GEMINI_KEYS else None

def next_gemini_key():
    if _key_cycle is None:
        return None
    with _key_lock:
        return next(_key_cycle)

def gemini_text(model: str = "gemini-2.5-flash-lite", temperature: float = 0.0,
                max_tokens: int = 2048):
    """Gemini text model (used only as a fallback if DeepSeek is unavailable)."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=model, google_api_key=next_gemini_key(), temperature=temperature,
        max_output_tokens=max_tokens, thinking_budget=0, max_retries=1,
    )

def gemini_multimodal(parts, model: str = "gemini-2.5-flash", max_tokens: int = 2048) -> str:
    """Invoke Gemini with multimodal `parts` (list of content blocks), rotating
    through every unique key until one succeeds (free-tier quota is scarce).

    `parts` example:
        [{"type": "text", "text": "..."},
         {"type": "media", "mime_type": "image/png", "data": "<base64>"}]
    For YouTube: {"type": "media", "file_uri": url, "mime_type": "video/mp4"}
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage
    last_err = None
    for key in dict.fromkeys(GEMINI_KEYS):
        try:
            llm = ChatGoogleGenerativeAI(
                model=model, google_api_key=key, temperature=0.0,
                max_output_tokens=max_tokens, thinking_budget=0, max_retries=1,
            )
            return llm.invoke([HumanMessage(content=parts)]).content
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("No Gemini key succeeded")
