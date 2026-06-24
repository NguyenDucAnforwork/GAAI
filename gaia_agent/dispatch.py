"""Routing: deterministic file-extension routing first, then a 1-call V3
classifier for fileless text questions."""
import re

from langchain_core.messages import SystemMessage, HumanMessage

from .providers import deepseek_chat
from .files import IMAGE_EXT, AUDIO_EXT

_YT = re.compile(r"(youtube\.com|youtu\.be)")

_CLASSIFY_SYS = (
    "Classify the question into ONE category. Reply with ONE word only.\n\n"
    "Decision rule: if the question contains ALL information needed to solve it "
    "(a puzzle, riddle, game scenario, logic problem, wordplay, or a math word "
    "problem) → it is SELF-CONTAINED → REASONING or MATH. If it refers to "
    "real-world facts, named entities, publications, websites, or events that "
    "must be looked up → WEB.\n\n"
    "WEB  — needs external/real-world lookup (e.g. 'how many albums did X release', "
    "'who nominated …', 'according to Wikipedia …', dates/figures about real things).\n"
    "MATH — a self-contained numeric calculation / equation / counting problem.\n"
    "REASONING — a self-contained logic puzzle, riddle, game, deduction, or "
    "wordplay (even if long and even if it mentions numbers or prizes).\n"
    "GENERAL — simple knowledge/explanation not fitting the above.\n\n"
    "Examples:\n"
    "'Pick That Ping-Pong … which ball maximizes odds …' → REASONING\n"
    "'opposite of the word left, reversed sentence' → REASONING\n"
    "'How many studio albums did Mercedes Sosa release 2000-2009' → WEB\n"
    "'Who nominated the only Featured Article about …' → WEB\n"
    "Reply with exactly one word: WEB, MATH, REASONING, or GENERAL."
)


def route_by_file(file_name: str) -> str:
    """Return a route for a file attachment, or None if not file-routable."""
    fn = (file_name or "").lower()
    if not fn:
        return None
    if fn.endswith(IMAGE_EXT):
        return "vision"
    if fn.endswith(AUDIO_EXT):
        return "audio"
    if fn.endswith(".py"):
        return "code"
    # docx / xlsx / pdf / txt / csv... → extract text then reason over it
    return "file_text"


async def classify_text(question: str) -> str:
    """Classify a fileless text question. Cheap single V3 call + heuristics."""
    if _YT.search(question):
        return "video"
    llm = deepseek_chat(temperature=0.0, max_tokens=4)
    try:
        out = (await llm.ainvoke([SystemMessage(content=_CLASSIFY_SYS),
                                  HumanMessage(content=question)])).content.upper()
    except Exception:
        out = "WEB"
    for cat in ("WEB", "MATH", "REASONING", "GENERAL"):
        if cat in out:
            return cat.lower()
    return "web"
