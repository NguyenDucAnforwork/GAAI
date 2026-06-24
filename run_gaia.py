"""GAIA v2 runner — DeepSeek + Gemini, no OpenAI.

Two-tier concurrency: text questions (DeepSeek, no RPM) run at high concurrency;
multimodal questions (Gemini, rate-limited) run throttled. Per-task results are
cached so a retry can re-run only the failures.

Usage:
  python run_gaia.py                  # first 20 Level 1 (metadata.jsonl)
  python run_gaia.py --offset 20      # the "next 20"
  python run_gaia.py --count 40
  python run_gaia.py --retry results/gaia_v2_XXatest.json   # re-run only failures
"""
import os
import re
import sys
import json
import time
import asyncio
import argparse
import datetime

os.environ.setdefault("LANGFUSE_DISABLED", "true")
os.environ.setdefault("GEMINI_VALIDATE", "false")

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)
sys.path.insert(0, os.path.dirname(__file__))

from gaia_agent.orchestrator import solve

TEXT_CONC = 8   # DeepSeek: no per-minute cap
MM_CONC   = 4   # Gemini: throttled to stay within free-tier RPM
PER_Q_TIMEOUT = 220.0  # allows R1 tiebreak / video analysis

YT = re.compile(r"(youtube\.com|youtu\.be)")
IMG_AUDIO = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
             ".mp3", ".wav", ".m4a", ".flac", ".ogg")


def load_level1(path, offset, count):
    data = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return [x for x in data if x.get("Level") == 1][offset:offset + count]


def is_multimodal(q):
    fn = (q.get("file_name") or "").lower()
    return fn.endswith(IMG_AUDIO) or bool(YT.search(q.get("Question", "")))


def extract_pred(answer_line):
    m = re.search(r"final answer:\s*(.*)", answer_line, re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip().splitlines()[0].strip() if m else answer_line.strip())


def evaluate(predicted, expected):
    def norm(t):
        t = re.sub(r"[\"'.,;:!?]", "", (t or "").lower())
        return re.sub(r"\s+", " ", t).strip()
    p, e = norm(predicted), norm(expected)
    if not p:
        return False
    if p == e:
        return True
    e_nums = re.findall(r"-?\d+\.?\d*", e)
    if e_nums and re.fullmatch(r"-?\d+\.?\d*", e.replace(",", "")):
        try:
            target = float(e_nums[0])
            for x in re.findall(r"-?\d+\.?\d*", p.replace(",", "")):
                if abs(float(x) - target) < 1e-9:
                    return True
        except ValueError:
            pass
        return False
    return e in p


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--retry", type=str, default=None,
                    help="results json to re-run only the failed tasks from")
    args = ap.parse_args()

    questions = load_level1("test_data/metadata.jsonl", args.offset, args.count)

    prior = {}
    if args.retry and os.path.exists(args.retry):
        for r in json.load(open(args.retry)).get("results", []):
            prior[r["task_id"]] = r
        # keep already-correct, only re-solve failures
        questions = [q for q in questions if not prior.get(q["task_id"], {}).get("is_correct")]
        print(f"Retry mode: re-running {len(questions)} previously-failed tasks")

    text_sem = asyncio.Semaphore(TEXT_CONC)
    mm_sem = asyncio.Semaphore(MM_CONC)
    print(f"Running {len(questions)} questions | text_conc={TEXT_CONC} mm_conc={MM_CONC}\n")

    async def run_one(idx, q):
        sem = mm_sem if is_multimodal(q) else text_sem
        async with sem:
            t0 = time.time()
            raw = ""
            try:
                res = await asyncio.wait_for(
                    solve(q["Question"], q.get("file_name", ""), q["task_id"]),
                    timeout=PER_Q_TIMEOUT)
                answer_line, route, raw = res["answer"], res["route"], res.get("raw", "")
            except asyncio.TimeoutError:
                answer_line, route = "FINAL ANSWER: TIMEOUT", "timeout"
            except Exception as e:
                answer_line, route = f"FINAL ANSWER: ERROR ({e})", "error"
            elapsed = time.time() - t0
            pred = extract_pred(answer_line)
            ok = evaluate(pred, str(q["Final answer"]))
            print(f"  {'✓' if ok else '✗'} Q{args.offset+idx+1:02d} [{(route or '?'):9s}] "
                  f"({elapsed:5.1f}s) exp={str(q['Final answer'])[:24]!r} got={pred[:34]!r}")
            return {"task_id": q["task_id"], "question": q["Question"],
                    "file_name": q.get("file_name", ""), "route": route,
                    "expected": str(q["Final answer"]), "predicted": pred,
                    "raw": raw,
                    "elapsed_time": round(elapsed, 1), "is_correct": ok}

    t_start = time.time()
    results = await asyncio.gather(*[run_one(i, q) for i, q in enumerate(questions)])
    wall = time.time() - t_start

    # Merge with prior (kept-correct) results when retrying.
    merged = dict(prior)
    for r in results:
        merged[r["task_id"]] = r
    final = list(merged.values())
    correct = sum(1 for r in final if r["is_correct"])
    total = len(final)

    print(f"\n{'='*56}")
    print(f"RESULTS: {correct}/{total} = {correct/total*100:.1f}%  |  wall {wall:.1f}s")
    print(f"{'='*56}")

    os.makedirs("results", exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = f"results/gaia_v2_{ts}.json"
    json.dump({"accuracy": correct / total if total else 0, "correct": correct,
               "total": total, "wall_seconds": round(wall, 1), "results": final},
              open(out, "w"), indent=2, ensure_ascii=False)
    print(f"Saved → {out}")


if __name__ == "__main__":
    asyncio.run(main())
