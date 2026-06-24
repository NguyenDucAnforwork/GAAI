import os
import threading
from itertools import cycle
from dotenv import load_dotenv, find_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

load_dotenv(find_dotenv(), override=True)

# ── Configuration ───────────────────────────────────────────────────────────
# Primary model for all specialist agents: Gemini 2.5 Flash (free tier, fast).
# The final answer formatter stays on gpt-4o-mini for a reliable output contract.
# gemini-2.5-flash gives the best accuracy and, with 6 keys (≈5 RPM each =
# 30 RPM) plus low concurrency, completes a 20-question batch within free-tier
# limits. Override with GEMINI_MODEL if needed.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
FORMATTER_MODEL = os.getenv("FORMATTER_MODEL", "gpt-4o-mini")

# Collect every GEMINI_API_KEY{n} present in the environment. Dead keys
# (suspended / access denied) simply fail at call time and rotation moves on.
def _load_gemini_keys():
    keys = []
    # Numbered keys first (GEMINI_API_KEY1 .. GEMINI_API_KEY12)
    for i in range(1, 13):
        v = os.getenv(f"GEMINI_API_KEY{i}")
        if v and v.strip():
            keys.append(v.strip())
    # Plain GOOGLE_API_KEY as a fallback member
    g = os.getenv("GOOGLE_API_KEY")
    if g and g.strip() and g.strip() not in keys:
        keys.append(g.strip())
    return keys

def _validate_gemini_keys(keys):
    """Ping each unique key once and keep only the working ones.

    Gated behind GEMINI_VALIDATE=true (batch eval sets it) so the interactive
    app isn't slowed by startup pings. Dead keys (suspended / access denied)
    are dropped so round-robin never lands on them.
    """
    import concurrent.futures
    from langchain_google_genai import ChatGoogleGenerativeAI

    uniq = list(dict.fromkeys(keys))  # dedupe, preserve order

    def _ok(k):
        try:
            llm = ChatGoogleGenerativeAI(
                model=GEMINI_MODEL, google_api_key=k,
                temperature=0.0, max_output_tokens=8, thinking_budget=0, max_retries=0,
            )
            llm.invoke("ok")
            return k
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(uniq) or 1) as ex:
        good = [k for k in ex.map(_ok, uniq) if k]
    return good or uniq  # if all fail, fall back to the full set

GEMINI_KEYS = _load_gemini_keys()
if GEMINI_KEYS and os.getenv("GEMINI_VALIDATE", "").lower() == "true":
    GEMINI_KEYS = _validate_gemini_keys(GEMINI_KEYS)
    print(f"[llms] Validated Gemini keys: {len(GEMINI_KEYS)} working")

# Round-robin key picker (thread-safe for concurrent question runs).
_key_lock = threading.Lock()
_key_cycle = cycle(GEMINI_KEYS) if GEMINI_KEYS else None

def _next_gemini_key():
    if _key_cycle is None:
        return None
    with _key_lock:
        return next(_key_cycle)

# ── OpenAI (formatter / fallback) ─────────────────────────────────────────────
openai_llm = ChatOpenAI(
    model=FORMATTER_MODEL,
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0.0,
    streaming=False,
    max_retries=2,
    request_timeout=60,
)

# ── Gemini (primary specialist LLM) ───────────────────────────────────────────
def get_gemini_llm(temperature: float = 0.0, max_output_tokens: int = 4096,
                   model: str = None) -> BaseChatModel:
    """Return a Gemini chat model using the next key in rotation.

    thinking_budget=0 disables the model's internal reasoning tokens, which
    makes responses ~1s and avoids the empty-output failure mode where thinking
    consumes the whole token budget. Pass `model` to override the default
    (e.g. full gemini-2.5-flash for harder reasoning).
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    key = _next_gemini_key()
    return ChatGoogleGenerativeAI(
        model=model or GEMINI_MODEL,
        google_api_key=key,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        thinking_budget=0,
        max_retries=3,  # backoff helps ride out brief free-tier RPM spikes
    )

OPENAI_AGENT_MODEL = os.getenv("OPENAI_AGENT_MODEL", "gpt-4o-mini")

def _openai(model: str, temperature: float, max_tokens: int = None) -> BaseChatModel:
    kw = dict(model=model, api_key=os.getenv("OPENAI_API_KEY"),
              temperature=temperature, max_retries=2, request_timeout=90)
    if max_tokens:
        kw["max_tokens"] = max_tokens
    return ChatOpenAI(**kw)

def _deepseek(model: str, temperature: float, max_tokens: int = None) -> BaseChatModel:
    kw = dict(model=model, api_key=os.getenv("DEEPSEEK_API_KEY"),
              base_url="https://api.deepseek.com", temperature=temperature,
              max_retries=2, request_timeout=120)
    if max_tokens:
        kw["max_tokens"] = max_tokens
    return ChatOpenAI(**kw)

def get_chat_llm(temperature: float = 0.0, max_output_tokens: int = 4096,
                 model: str = None) -> BaseChatModel:
    """Primary chat LLM for agents.

    Provider is chosen by the `model` prefix so callers can opt into a specific
    backend without rate-limit surprises:
      - model starts with 'deepseek' → DeepSeek (strong reasoning, no RPM cap)
      - model starts with 'gemini'   → Gemini (free tier, rate-limited)
      - model starts with 'gpt'/'o'   → that OpenAI model
      - model is None                → default OpenAI agent model (no rate limits,
                                       enables high concurrency)
    """
    if model and model.startswith("deepseek"):
        try:
            return _deepseek(model, temperature, max_tokens=max_output_tokens)
        except Exception as e:
            print(f"[llms] DeepSeek unavailable, falling back to OpenAI: {e}")
            return _openai("gpt-4o", temperature)
    if model and model.startswith("gemini"):
        if GEMINI_KEYS:
            try:
                return get_gemini_llm(temperature=temperature,
                                      max_output_tokens=max_output_tokens, model=model)
            except Exception as e:
                print(f"[llms] Gemini unavailable, falling back to OpenAI: {e}")
        return _openai(OPENAI_AGENT_MODEL, temperature)
    return _openai(model or OPENAI_AGENT_MODEL, temperature, max_tokens=max_output_tokens)

def get_formatter_llm() -> BaseChatModel:
    """Dedicated LLM for the final-answer formatter (reliable, cheap)."""
    return openai_llm

# ── Backward-compatible shims ─────────────────────────────────────────────────
# Existing code imports get_llm / get_smart_llm / get_fast_llm / gemini_llm.
def get_fast_llm():
    return get_chat_llm()

def get_smart_llm():
    return get_chat_llm()

def get_llm(provider: str = "gemini") -> BaseChatModel:
    """Default LLM for agents. Routes everything to Gemini for speed/cost.

    The 'openai' provider hint is intentionally ignored for agents so the whole
    pipeline runs on the free Gemini tier; the formatter calls get_formatter_llm
    directly when it needs the OpenAI output contract.
    """
    return get_chat_llm()

# Module-level Gemini handle some modules import directly.
try:
    gemini_llm = get_gemini_llm() if GEMINI_KEYS else None
except Exception:
    gemini_llm = None

def call_llm(state, llm=None):
    """Call the LLM with the current state's messages."""
    if llm is None:
        llm = get_chat_llm()
    messages = state.get("messages", [])
    try:
        response = llm.invoke(messages)
        return {"messages": messages + [response]}
    except Exception as e:
        print(f"Error calling LLM: {str(e)}")
        error_msg = AIMessage(content=f"Sorry, I encountered an error: {str(e)}")
        return {"messages": messages + [error_msg]}
