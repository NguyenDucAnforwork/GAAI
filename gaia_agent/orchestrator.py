"""Top-level orchestrator: solve(question, file_name, task_id) → 'FINAL ANSWER: ...'.

Flow: resolve attachment → route → run specialist agent → format+verify.
"""
import asyncio

from . import agents
from . import dispatch
from .files import fetch_file, extract_text
from .formatter import format_answer


async def solve(question: str, file_name: str = "", task_id: str = "") -> dict:
    """Solve one GAIA question. Returns {route, raw, answer}."""
    file_name = (file_name or "").strip()
    route = None
    raw = ""
    file_bytes = None
    file_text = ""

    # 1) Resolve attachment if present.
    if file_name:
        route = dispatch.route_by_file(file_name)
        try:
            file_bytes = await asyncio.to_thread(fetch_file, file_name, task_id)
        except Exception as e:
            print(f"[orchestrator] file fetch failed ({file_name}): {e}")
            route = None  # fall back to text routing

    # 2) Route + run the specialist agent.
    try:
        if route == "vision":
            raw = await agents.vision_solve(question, file_name, file_bytes)
        elif route == "audio":
            raw = await agents.audio_solve(question, file_name, file_bytes)
        elif route == "code":
            raw = await agents.code_solve(question, file_name, file_bytes)
        elif route == "file_text":
            file_text = extract_text(file_name, file_bytes) if file_bytes else ""
            # Bound size to keep reasoning latency in check on huge sheets/decks.
            if len(file_text) > 12000:
                file_text = file_text[:12000] + "\n...[truncated]"
            q = question + (f"\n\n[Attached document contents]\n{file_text}" if file_text else "")
            # A document usually contains the answer → reason over it (web only if it
            # explicitly needs external lookup, which the classifier decides).
            sub = await dispatch.classify_text(question)
            if sub == "web":
                raw = await agents.web_solve(q)
            else:
                raw = await agents.reasoning_solve(q)
        else:
            # Fileless text question.
            route = await dispatch.classify_text(question)
            if route == "video":
                raw = await agents.video_solve(question)
            elif route == "web":
                raw = await agents.web_solve(question)
            elif route == "math":
                raw = await agents.math_solve(question)
            elif route == "reasoning":
                raw = await agents.reasoning_solve(question)
            else:
                raw = await agents.general_solve(question)
    except Exception as e:
        print(f"[orchestrator] agent error ({route}): {e}")
        raw = f"FINAL ANSWER: ERROR ({e})"

    # 3) Format + verify.
    answer_line = await format_answer(question, raw)
    return {"route": route, "raw": raw, "answer": answer_line}


class GaiaAgent:
    """Adapter for app.py — replaces the old OptimizedGAAIWorkflow.

    Same spirit as the old `process_query`, but the signature now carries the
    attachment metadata (file_name, task_id) so the file/multimodal pipeline can
    run. Returns the 'FINAL ANSWER: <value>' string.
    """

    def __init__(self):
        print("GaiaAgent initialized (DeepSeek text + Gemini multimodal, no OpenAI).")

    async def process_query(self, question: str, file_name: str = "", task_id: str = "") -> str:
        res = await solve(question, file_name, task_id)
        return res["answer"]
