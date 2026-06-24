"""Specialist agents. All async so the orchestrator can run them concurrently.

Text agents → DeepSeek; multimodal agents → Gemini; math/code → DeepSeek + sandbox.
"""
import re
import asyncio
import base64

from langchain_core.messages import SystemMessage, HumanMessage

from .providers import deepseek_chat, deepseek_reasoner, gemini_multimodal
from .formatter import extract_marker
from .sandbox import run_python
from .files import mime_for

# Reuse the existing, battle-tested web tools (search + read with Wayback fallback).
from langgraph_ver.tools.web_tools import search_web, read_webpage, read_pdf, search_and_read_web

_REASON_SYS = (
    "Solve the problem with careful, explicit step-by-step reasoning.\n"
    "1) Restate exactly what is asked and the required answer format.\n"
    "2) Extract all rules, constraints and given quantities.\n"
    "3) Work through the logic/arithmetic step by step; double-check units, "
    "wording, edge cases and off-by-one.\n"
    "4) For list answers: use each item's EXACT wording as it appears in the "
    "question (do not drop modifiers like 'fresh'); if asked to alphabetize, sort "
    "alphabetically; comma-separated.\n"
    "5) End with a single line: 'FINAL ANSWER: your_answer' — ONLY the answer, "
    "in the exact form requested, no tags or markup."
)


def _norm(ans: str) -> str:
    a = re.sub(r"[^\w\s.]", "", (ans or "").lower())
    return re.sub(r"\s+", " ", a).strip()


# ── Reasoning: 3×V3 self-consistency vote, R1 tiebreak ────────────────────────
async def reasoning_solve(question: str, n_votes: int = 3, hard: bool = False) -> str:
    """Run n_votes diverse V3 samples, majority-vote; on a split, R1 decides."""
    async def one(temp):
        llm = deepseek_chat(temperature=temp, max_tokens=4000)
        try:
            r = await llm.ainvoke([SystemMessage(content=_REASON_SYS),
                                   HumanMessage(content=question)])
            return r.content or ""
        except Exception as e:
            return f"(error: {e})"

    # Diverse temperatures so the votes aren't identical (self-consistency).
    temps = [0.2, 0.6, 0.9, 0.4, 0.7][:n_votes]
    samples = await asyncio.gather(*[one(t) for t in temps])
    answers = [extract_marker(s) for s in samples if s and "error" not in s[:8].lower()]

    tally = {}
    for a in answers:
        if a:
            tally.setdefault(_norm(a), []).append(a)
    best = max(tally.values(), key=len) if tally else []

    # Clear majority → done. Otherwise let R1 arbitrate (with V3 fallback).
    if best and len(best) >= (len(answers) // 2 + 1):
        return f"FINAL ANSWER: {best[0]}"

    try:
        r1 = deepseek_reasoner(max_tokens=8000)
        opts = "; ".join(sorted(tally.keys())) or "none"
        prompt = (f"{question}\n\nCandidate answers from other solvers: {opts}\n"
                  "Reason independently and decide the correct one.")
        out = await asyncio.wait_for(
            r1.ainvoke([SystemMessage(content=_REASON_SYS), HumanMessage(content=prompt)]),
            timeout=120.0)  # cap R1 latency
        val = extract_marker(out.content or "")
        if val:
            return f"FINAL ANSWER: {val}"
    except Exception as e:
        print(f"[reasoning] R1 tiebreak failed: {e}")

    return f"FINAL ANSWER: {best[0] if best else (answers[0] if answers else '')}"


# ── Web: multi-source search + read, commit-to-answer synthesis ───────────────
async def web_solve(question: str) -> str:
    def gather():
        chunks = []
        try:
            snippets = search_web.invoke(question) or []
            s = ""
            for r in snippets[:6]:
                if isinstance(r, dict):
                    s += f"- {r.get('title','')}: {r.get('content','')} ({r.get('url','')})\n"
            if s:
                chunks.append("Search snippets:\n" + s)
        except Exception as e:
            print(f"[web] search failed: {e}")
        try:
            page = search_and_read_web.invoke(question)
            if page and len(page) > 100:
                chunks.append("Top source content:\n" + page[:8000])
        except Exception as e:
            print(f"[web] read failed: {e}")
        return "\n\n".join(chunks) or "No results."

    context = await asyncio.to_thread(gather)
    llm = deepseek_chat(temperature=0.0, max_tokens=1500)
    prompt = (
        f"Question: {question}\n\nWeb evidence:\n{context}\n\n"
        "Determine the precise answer using the evidence as primary support; "
        "read numbers and proper nouns carefully. If the evidence is insufficient, "
        "give the single most likely specific answer from your knowledge — never "
        "refuse, always commit to one concrete answer. Output only the specific "
        "thing asked for, then 'FINAL ANSWER: <answer>'."
    )
    out = await llm.ainvoke([HumanMessage(content=prompt)])
    return out.content or ""


# ── Math / code: write Python, execute, answer from real output ───────────────
async def math_solve(question: str, code_file: tuple = None) -> str:
    """code_file: optional (filename, text) of an attached .py to incorporate."""
    llm = deepseek_chat(temperature=0.0, max_tokens=2000)
    extra = ""
    if code_file:
        extra = (f"\n\nAn attached file '{code_file[0]}' contains:\n```\n"
                 f"{code_file[1][:6000]}\n```")
    gen = await llm.ainvoke([HumanMessage(content=(
        f"{question}{extra}\n\nWrite a self-contained Python script that computes "
        "and prints ONLY the final answer (no extra text). Output just the code in "
        "a ```python block."))])
    m = re.search(r"```(?:python)?\s*(.*?)```", gen.content or "", re.DOTALL)
    code = m.group(1) if m else (gen.content or "")
    result = await asyncio.to_thread(run_python, code, 12)

    if result.startswith(("[timeout", "[no output", "[no stdout", "[exec error")):
        # Execution failed → fall back to pure reasoning.
        return await reasoning_solve(question)
    return f"Computed result: {result}\nFINAL ANSWER: {result}"


# ── Code: run the attached .py and interpret what the question asks ───────────
async def code_solve(question: str, file_name: str, content: bytes) -> str:
    code = content.decode("utf-8", "ignore")
    # Short run as a hint only — some scripts loop on randomness/sleep and never
    # finish in time, yet their output is logically determined. So we ALWAYS let
    # the model reason about the code, using the run output only as a hint.
    output = await asyncio.to_thread(run_python, code, 10)
    incomplete = output.startswith(("[timeout", "[no output", "[exec error"))
    hint = (f"(execution did not finish cleanly: {output} — reason from the code "
            "logic instead)" if incomplete else f"actual run output: {output}")
    llm = deepseek_chat(temperature=0.0, max_tokens=1500)
    out = await llm.ainvoke([HumanMessage(content=(
        f"{question}\n\nAttached Python file '{file_name}':\n```\n{code[:6000]}\n```\n\n"
        f"Execution hint: {hint}\n\n"
        "Determine the program's final printed output. If the run was incomplete "
        "(e.g. random retry loops or sleeps), REASON about the control flow to "
        "find what value it must ultimately print. End with 'FINAL ANSWER: <answer>'."))])
    return out.content or ""


# ── Vision / Audio / Video (Gemini multimodal) ────────────────────────────────
async def vision_solve(question: str, file_name: str, content: bytes) -> str:
    b64 = base64.b64encode(content).decode()
    parts = [
        {"type": "text", "text": question + "\n\nAnalyze the image carefully and end "
         "with 'FINAL ANSWER: <answer>'."},
        {"type": "media", "mime_type": mime_for(file_name), "data": b64},
    ]
    return await asyncio.to_thread(gemini_multimodal, parts, "gemini-2.5-flash", 1800)


async def audio_solve(question: str, file_name: str, content: bytes) -> str:
    b64 = base64.b64encode(content).decode()
    parts = [
        {"type": "text", "text": question + "\n\nListen to the audio and answer "
         "precisely. End with 'FINAL ANSWER: <answer>'."},
        {"type": "media", "mime_type": mime_for(file_name), "data": b64},
    ]
    return await asyncio.to_thread(gemini_multimodal, parts, "gemini-2.5-flash", 1800)


async def video_solve(question: str) -> str:
    m = re.search(r"(https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w-]+)", question)
    if not m:
        return "FINAL ANSWER: "
    parts = [
        {"type": "media", "file_uri": m.group(1), "mime_type": "video/mp4"},
        {"type": "text", "text": question + "\n\nWatch the video and answer precisely. "
         "End with 'FINAL ANSWER: <answer>'."},
    ]
    return await asyncio.to_thread(gemini_multimodal, parts, "gemini-2.5-flash", 1800)


# ── General fallback ──────────────────────────────────────────────────────────
async def general_solve(question: str) -> str:
    llm = deepseek_chat(temperature=0.0, max_tokens=2000)
    out = await llm.ainvoke([
        SystemMessage(content="Answer concisely and end with 'FINAL ANSWER: <answer>'."),
        HumanMessage(content=question)])
    return out.content or ""
