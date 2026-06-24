"""Final-answer formatter + verifier (one DeepSeek call) + deterministic fixes.

GAIA grades exact strings, so formatting *is* correctness. The LLM enforces the
GAIA answer conventions; a deterministic post-process then guarantees the unit
conversions / yes-no normalisation the LLM tends to miss.
"""
import re

from langchain_core.messages import SystemMessage, HumanMessage

from .providers import deepseek_chat

_SYSTEM = (
    "You are a strict GAIA answer formatter and verifier.\n"
    "Given the question and a raw answer, output EXACTLY one line:\n"
    "FINAL ANSWER: <value>\n"
    "Rules:\n"
    "1) Only the answer after the marker — no explanation, no markup, no tags.\n"
    "2) Numbers: no thousands separators; no units unless the question asks for them.\n"
    "3) Text: minimal words; drop leading articles (a/an/the) UNLESS the question "
    "asks for exact/verbatim wording or all-caps — then reproduce it exactly.\n"
    "4) Lists: comma-separated, no extra words.\n"
    "5) Yes/No questions: answer exactly 'Yes' or 'No'.\n"
    "6) OBEY any explicit format instruction inside the question (e.g. 'city only', "
    "'round to 2 decimals', 'in caps') — it overrides the defaults.\n"
    "7) Verify the raw answer actually addresses the question; if it is an error/"
    "refusal, give your single best concrete answer instead.\n"
    "Output ONLY the one required line."
)


def _deterministic_units(question: str, value: str) -> str:
    """Convert base-unit numbers to the unit the question asks for (thousand/million)."""
    ql = (question or "").lower()
    bare = value.replace(",", "").replace(" ", "")
    if re.fullmatch(r"-?\d+(\.\d+)?", bare):
        num = float(bare)
        conv = None
        if "thousand" in ql and abs(num) >= 1000:
            conv = num / 1000.0
        elif "million" in ql and abs(num) >= 1_000_000:
            conv = num / 1_000_000.0
        elif "billion" in ql and abs(num) >= 1_000_000_000:
            conv = num / 1_000_000_000.0
        if conv is not None:
            return str(int(conv)) if conv == int(conv) else str(conv)
    return value


def extract_marker(text: str) -> str:
    m = re.search(r"final answer:\s*(.*)", text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip().splitlines()[0].strip()
    return (text or "").strip().splitlines()[-1].strip() if text else ""


async def format_answer(question: str, raw: str) -> str:
    """Return a clean 'FINAL ANSWER: <value>' string."""
    llm = deepseek_chat(temperature=0.0, max_tokens=400)
    user = HumanMessage(content=f"Question:\n{question}\n\nRaw answer:\n{raw}\n\n"
                                "Apply the rules and respond with exactly one line.")
    try:
        out = (await llm.ainvoke([SystemMessage(content=_SYSTEM), user])).content or ""
    except Exception:
        out = raw or ""
    value = extract_marker(out) or extract_marker(raw)
    value = _deterministic_units(question, value)
    return f"FINAL ANSWER: {value}"
