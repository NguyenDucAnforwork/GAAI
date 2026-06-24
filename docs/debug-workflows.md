# Debug Workflows — GAIA Level 1 Failure Analysis

> 📘 **For the distilled, reusable lessons** (system design, prompt engineering,
> model selection, evaluation methodology), read
> [`accuracy-playbook.md`](./accuracy-playbook.md). This file is the raw
> chronological log and per-question failure analysis that fed into it.
>
> This file documents **both logic-level failures** (wrong answers from correct
> code) **and code-level bugs** (crashes, wrong configs, missing handlers). See
> the "Code-level bugs" section near the bottom for the latter.

Test run: 2026-06-10, 20 questions (first 20 Level 1 from `test_data/metadata.jsonl`)
**Score: 6/20 (30.0%)** | Cost: ~$0.0004 (gpt-4o-mini throughout)
Results file: `results/full_test_*.json` | Test runner: `run_full_test.py`

---

## Failure Patterns

### Pattern 1 — File-based questions always fail (3 questions: Q8, Q10, Q17)

| Q | Task ID | File | Expected | Got |
|---|---------|------|----------|-----|
| 8 | cffe0e32 | .docx (Secret Santa list) | Fred | "missing employee" |
| 10 | 5cfb274c | .xlsx (land plots) | No | full-sentence explanation |
| 17 | cca530fc | .png (chess position) | Rd5 | Nf3# (hallucinated) |

**Root cause:** The workflow never downloads or reads attachments. The GAIA file
endpoint `https://agents-course-unit4-scoring.hf.space/files/{task_id}` returns
404 without auth, and `test_data/` only contains files for other tasks. The
agents answer blind, hallucinating plausible-looking answers.

**Impact:** 3 guaranteed losses (15% of the set).

---

### Pattern 2 — Video agent stubbed out (1 question: Q5)

| Q | Task ID | Expected | Got |
|---|---------|----------|-----|
| 5 | a1e91b78 | 3 | 7 |

**Root cause:** `video_agent_smolvlm.py` fails to import
(`AutoModelForImageTextToText` missing from installed transformers version), so
`workflow.py` falls back to a stub that returns no real analysis. The answer
comes from the LLM guessing about a video it never saw.

**Impact:** 1 guaranteed loss.

---

### Pattern 3 — Web agent finds wrong/no information (7 questions: Q4, Q6, Q13, Q14, Q16, Q18, Q20)

| Q | Task ID | Expected | Got | Failure mode |
|---|---------|----------|-----|--------------|
| 4 | 5d0080cb | 0.1777 | N/A | PDF (University of Leicester paper) never located/read |
| 6 | 46719c30 | Mapping Human Oriented... | wrong title | multi-hop lookup (paper → author → first paper) collapses to 1 hop |
| 13 | b816bfce | fluffy | monstrous | found article but extracted wrong word |
| 14 | 72e110e7 | Guatemala | unknown | BASE search UI not navigable via plain search |
| 16 | b415aba4 | diamond | graphene | plausible-but-wrong from snippets |
| 18 | 935e2cff | research | Reliable | answered from priors, not from the actual source |
| 20 | 5188369a | Annie Levin | Burlington Free Press | returned source name instead of quoted writer |

**Root causes (in order of severity):**
1. **Hard 2-step search limit** (`web_agent.py` `step_count >= 2`): multi-hop
   questions (Q6) need 3–5 sequential lookups; the agent is cut off and forced
   to a "direct answer" from whatever partial snippets it has.
2. **Answers from snippets instead of full pages:** observations are truncated
   to 1000 chars in `direct_answer` (`web_agent.py:291`), so the answer is
   often outside the window even when the right page was found (Q13, Q20).
3. **No "I don't know" discipline:** when search fails, the summarizer is told
   to "provide the best answer you can based on your knowledge" — which
   guarantees a hallucination instead of a retry (Q16, Q18).
4. **No specialized source handling:** PDFs (Q4) and database UIs like BASE
   (Q14) need `read_pdf` / targeted URL construction, but the agent rarely
   chooses those tools.

**Impact:** 7 losses — the single biggest bucket (35% of the set).

---

### Pattern 4 — Answer formatting mismatches (2 questions: Q7, Q10)

| Q | Expected | Got | Problem |
|---|----------|-----|---------|
| 7 | THE CASTLE | A CASTLE | wrong article kept (and articles should match exactly here) |
| 10 | No | "Earl can walk through every plot..." | full sentence instead of Yes/No |

**Root cause:** The formatter node (`workflow.py format_response`) prompt says
"no articles" for text answers, yet emitted "A CASTLE"; and it doesn't detect
yes/no questions. The formatter is also fed a raw response that may itself be
wrong-shaped, and it never re-reads the question's format constraints
("Give the answer in exact wording", "Answer Yes or No").

**Impact:** 1–2 losses that were otherwise "almost right".

---

### Pattern 5 — Reasoning agent logic errors (2 questions: Q3, Q15)

| Q | Expected | Got | Problem |
|---|----------|-----|---------|
| 3 | 3 | 1 | ping-pong ball probability computed wrong |
| 15 | Maktay mato apple | Maktay Zapple Pa | Tizin grammar rules misapplied |

**Root causes:**
1. `reasoning_agent.py strategic_analysis` contains a **hardcoded prompt block
   for one specific ping-pong problem** (lines ~144–154) with pre-baked
   probabilities — it pollutes reasoning for every other puzzle and even for
   the actual ping-pong question (Q3 still got it wrong).
2. A tool-calling crash (`unexpected '{' in field name` — unescaped braces in
   the f-string prompt template) silently dropped the agent to `direct_solve`
   fallback, skipping the calculation phase entirely.
3. gpt-4o-mini is weak on careful symbolic reasoning (Q15's subject/object
   case rules).

**Impact:** 2 losses.

---

## Loss accounting

| Pattern | Questions lost | Fixable for ~free? |
|---------|---------------|--------------------|
| 3. Web agent precision | 7 | mostly (code/prompt changes) |
| 1. File attachments | 3 | yes (file download + parse, no LLM cost for docx/xlsx) |
| 4. Formatting | 2 | yes (prompt change, zero extra cost) |
| 5. Reasoning errors | 2 | partially (bug fixes free; model quality costs) |
| 2. Video | 1 | hard locally (model install, no API cost but heavy) |

Ceiling if all cheap fixes land: roughly **14–16/20**.

---

## Suggested Fixes (budget-aware, ordered by ROI)

Pricing assumptions: gpt-4o-mini $0.15/M in, $0.60/M out; Gemini 2.0 Flash free
tier (8 keys available); DeepSeek chat ~$0.14/M in (off-peak cheaper). A full
20-question run currently costs well under $0.01, so there is enormous headroom
inside $0.10.

### Fix 1 — Formatter hardening (cost: $0, gain: +1–2)
- In `format_response`, add to the system prompt:
  - "If the question asks Yes/No, answer exactly `Yes` or `No`."
  - "If the question demands exact wording or 'in caps', copy the exact words
    from the source/response."
  - Pass the question FIRST and instruct the formatter to obey any explicit
    format instruction inside it (GAIA questions usually state the format).
- This is a pure prompt edit — zero added tokens per call.

### Fix 2 — File attachment pipeline (cost: ≈$0, gain: +2–3)
- Add a pre-processing step in the test runner / `app.py`:
  1. Try `GET {api}/files/{task_id}` **with the HF token** (the 404 is likely
     missing auth — when running as the HF Space with OAuth it should work).
  2. Parse locally at zero LLM cost: `python-docx` for .docx, `openpyxl` for
     .xlsx → inline the extracted text/table into the question text.
  3. For images (.png chess board): pass to **Gemini 2.0 Flash vision (free
     tier)** — no OpenAI cost. One image call per question.
- Even if only docx/xlsx work, that's +2.

### Fix 3 — Web agent rework (cost: <$0.02/run, gain: +3–5)
Biggest bucket, biggest gain:
- **Raise the step limit from 2 to 5** for multi-hop questions. Each extra hop
  is one search (Tavily is free-tier) + one short LLM call (~2K tokens ≈
  $0.0005). Worst case +$0.01 across the whole run.
- **Stop truncating observations at 1000 chars** — raise to ~8K chars for the
  final answer synthesis. At gpt-4o-mini input pricing, 8K chars ≈ 2K tokens ≈
  $0.0003 per question. Negligible.
- **Ban knowledge-based fallback:** replace "provide the best answer you can
  based on your knowledge" with "if the sources don't contain the answer,
  output `RETRY: <better query>`" and loop once. Hallucinated answers are
  guaranteed zeros; a retry at least has a chance.
- **Question decomposition for multi-hop:** one cheap LLM call to split
  "authors of paper X → which had prior papers → their first paper" into
  ordered sub-queries, then search each. ~$0.001 extra per complex question.
- **Use `read_pdf` proactively:** if a result URL ends in `.pdf` or the
  question mentions a paper, call the existing `read_pdf` tool.

### Fix 4 — Reasoning agent repairs (cost: $0–0.01, gain: +1–2)
- **Delete the hardcoded ping-pong block** in `strategic_analysis` — it's
  prompt pollution for every other puzzle.
- **Fix the f-string brace crash** (`unexpected '{' in field name`): escape
  literal `{}` in the prompt template (`{{` / `}}`) so the tool-calling phase
  actually runs instead of silently degrading to `direct_solve`.
- Optionally route REASONING to **DeepSeek-chat** (strong at reasoning,
  ~$0.001/question) or **Gemini 2.0 Flash (free)** instead of gpt-4o-mini, with
  a self-check pass ("re-derive and verify your answer") — doubles reasoning
  cost but it's still <$0.005/run.

### Fix 5 — Video agent (cost: $0 API, gain: +1, effort: high)
- Local SmolVLM requires fixing the transformers version and downloading the
  model (~1GB) — no API cost but slow and fragile on this machine.
- Cheaper path: **Gemini 2.0 Flash accepts YouTube URLs directly** via the
  Files/video API on free tier. One call per video question. Recommended over
  fixing SmolVLM.
- If neither lands: hard-skip video questions instead of returning a stubbed
  guess (a wrong guess and a skip both score 0, but the log stays honest).

### Fix 6 — Cheap accuracy multiplier: model rotation (cost: ≈$0)
With 8 free Gemini keys, run the **router and all specialist agents on Gemini
2.0 Flash** (rotating keys to dodge rate limits) and keep gpt-4o-mini ONLY for
the final formatter. This makes the entire run ~$0.001 and frees budget for:
- **Self-consistency on hard questions:** sample the agent 3× and majority-vote
  the final answer. 3× free-tier calls = still $0.

### Suggested execution order

| Step | Fix | Est. cost/run | Cumulative expected score |
|------|-----|---------------|---------------------------|
| 1 | Formatter (Fix 1) | $0.001 | 7–8/20 |
| 2 | Reasoning bugs (Fix 4, free parts) | $0.001 | 8–10/20 |
| 3 | Web agent (Fix 3) | $0.01–0.02 | 11–14/20 |
| 4 | Files (Fix 2) | $0.01 | 13–16/20 |
| 5 | Video via Gemini (Fix 5) | $0 | 14–17/20 |

Total estimated cost for a full re-run after all fixes: **< $0.03**, leaving
room for 2–3 full validation runs inside the $0.10 budget.

---

## Post-Fix Results (2026-06-10)

Fixes implemented:
- **Model switch:** all specialist agents + router now run on **Gemini 2.5
  Flash** (free tier) with 6-key round-robin rotation + startup key validation
  (`llms.py`). Formatter stays on gpt-4o-mini. → near-zero cost.
- **Reasoning agent:** replaced the brittle 4-phase tool pipeline (brace crash +
  hardcoded ping-pong block) with a single careful chain-of-thought call on full
  `gemini-2.5-flash`.
- **Web agent:** Gemini LLM, observation window 1000→8000 chars, step limit
  2→3, anti-hallucination synthesis prompt ("answer from sources or say NOT
  FOUND").
- **Formatter:** yes/no rule, exact-wording rule, obeys in-question format
  instructions.
- **Video agent:** SmolVLM (broken import) replaced with Gemini native YouTube
  understanding.
- **Test runner:** concurrent (`asyncio.gather` + semaphore), Langfuse disabled
  for batch eval.

**Best clean run: 7/20 (35%), 3.3 min wall-clock, ~$0 Gemini + <$0.01 formatter.**
(Baseline was 6/20.)

Recovered by the reasoning fix: Q3 (riddle), Q9 (reversed text), Q10
(spreadsheet logic), Q15 (Tizin grammar). Video Q5 and math Q12 verified correct
in earlier runs.

### Key operational constraint discovered
The **Gemini free-tier per-minute quota is the binding limit**: `gemini-2.5-flash`
≈ 5 RPM/key, `gemini-2.5-flash-lite` ≈ 15 RPM/key. With 6 working keys (2 of the
8 supplied are suspended/denied) that's ~30 RPM. Concurrent batch runs burst past
this, and repeated test iterations exhaust the daily allowance. In the final run,
6 questions (Q5, Q7, Q12, Q17, Q18, Q20) returned `]` — these are **rate-limit
casualties** (the formatter received 429 error text), not logic failures; Q5/Q12
are known-correct. True achievable score once quota is fresh is ~**10–12/20**.

### Remaining real failures (not quota)
- **Web retrieval (Q4, Q6, Q13, Q14, Q16):** single search+read doesn't surface
  the answer; multi-hop (Q6) and specific-source (Q14 BASE) questions need
  iterative/decomposed retrieval. Now honest ("NOT FOUND") instead of
  hallucinating.
- **File questions (Q8, Q17):** attachments 404 in this environment (no auth);
  fixable only on the live HF Space.
- **Q1 unit conversion:** formatter output 1000 instead of 17 ("thousand hours").
- **Q11 false positive:** the evaluator strips logic symbols (¬ → ↔ ∨ ∧), so a
  wrong formula scores as correct — evaluator limitation, not a model win.

### Recommended next steps
1. Use `gemini-2.5-flash-lite` primary + `flash` only for reasoning, run at
   concurrency 2, and add **retry-with-next-key on 429** (not same-key backoff)
   to eliminate the `]` casualties.
2. Iterative web retrieval (decompose multi-hop, read top-3 results not just 1).
3. Tighten the evaluator to not strip logic symbols (fix Q11 false positive).

---

## Final Multi-Provider Config — 16/20 (80%), 51.6 s, < $0.20

Goal: ≥14/20 in <7 min, ≤$0.20. **Achieved 16/20 in 51.6 s.**

Provider routing (chosen per `model` prefix in `get_chat_llm`, `llms.py`):
| Role | Provider/model | Why |
|------|----------------|-----|
| Web / router / math / general / formatter | **OpenAI gpt-4o-mini** | no rate limits → concurrency 6 → fast; cheap |
| Reasoning | **DeepSeek-chat (V3)**, gpt-4o fallback | gets the logic/wordplay puzzles (Q3, Q9, Q11, Q15) gpt-4o & Gemini missed; fast, no RPM cap |
| Video (YouTube) | **Gemini 2.5 Flash** | only provider with native YouTube understanding; iterates all keys |

Other fixes that mattered (exact locations):
- **Stricter evaluator** — `run_full_test.py:evaluate` (L98-122): exact numeric
  equality (17000 ≠ 17), logic symbols preserved.
- **Deterministic thousand/million conversion** — `langgraph_ver/workflow.py`
  `format_response` (L431-446) → Q1 (17).
- **Cleaned reasoning prompt** (no `<answer>` tags) — `langgraph_ver/agents/reasoning_agent.py:343`.
- **Concurrency** — `run_full_test.py:CONCURRENCY`; Langfuse off — `langgraph_ver/workflow.py:27-34`.
- **Provider routing** — `langgraph_ver/llms.py:get_chat_llm` (L125-156, dispatch
  by model prefix); reasoning model order `langgraph_ver/agents/reasoning_agent.py:351`.

Genuine result (strict evaluator, no false positives): **16/20**.
- ✓ Q1, Q2, Q3, Q4, Q6, Q9, Q10, Q11, Q12, Q13, Q14, Q15, Q16, Q18, Q19, Q20
- ✗ Q5 (video — Gemini free-tier quota exhausted by repeated testing today;
  succeeded in earlier runs, recoverable once quota resets)
- ✗ Q7 (web returned the episode title "HEAVEN SENT" instead of "THE CASTLE")
- ✗ Q8 (.docx) and Q17 (.png chess) — attachments 404 without auth in this env;
  solvable only on the live HF Space.

Cost: DeepSeek reasoning ≈ $0.003/run, OpenAI mini ≈ $0.01/run, Gemini free.
Total for all iterations today comfortably under the $0.20 budget.

---

## Push toward 20/20 — what was unlocked, and the hard ceiling

Additional work to attack the 4 misses (Q5, Q7, Q8, Q17):

**Unlocked / solved (exact locations):**
- **File access** — official gated GAIA via HF token → mirror fallback:
  `gaia_agent/files.py:fetch_file` (L33-67, `hf_hub_download` L40); old runner
  variant in `run_full_test.py:fetch_gaia_file`.
- **Q8 (.docx Secret Santa)** → **solved (Fred)** — extract `gaia_agent/files.py:extract_text`
  (docx branch L73-79) + reasoning `gaia_agent/agents.py:reasoning_solve`.
- **Q5 (video)** → **solved (3)** — `gaia_agent/agents.py:video_solve L181-192`
  (Gemini YouTube via `providers.py:gemini_multimodal`).
- **Wayback Machine fallback** — `langgraph_ver/tools/web_tools.py:_wayback_snapshot`
  (L17-33) + `_fetch` (L35-49); direct PDF-result read `web_tools.py:374-376`.

**Genuine blockers to a reliable 20/20:**
- **Q17 (chess .png)** — file obtained, but vision-to-FEN transcription is
  unreliable (gpt-4o reads a slightly different board each call → wrong move
  Qd1#/Qb1+ instead of Rd5). Beyond current reliable capability without a
  dedicated board-recognition tool + engine.
- **Q7 (THE CASTLE)** — answer verified by reading the official BBC script
  ("INT. THE CASTLE - DAY"), but the search engine never surfaces that script
  PDF for the question text, so the agent answers with the episode title.
- **Model nondeterminism** — Q3/Q8 (DeepSeek), Q15 (reasoner-dependent: Gemini
  & V3 get "Maktay mato apple", R1 misses it), Q16/Q18 (web retrieval ordering)
  flip between runs. No single reasoner wins all of Q3/Q8/Q11/Q15 at once.

**Result range across runs: 14–16/20.** Best **16/20**. A guaranteed 20/20 is
not attainable with this free/cheap stack: Q17 needs reliable chess-vision, Q7
needs the search engine to surface a specific script, and the rest is variance.
Realistic stable ceiling ≈ 16–18/20 with per-question model selection + an
ensemble vote (not implemented — diminishing returns vs. the $0.20 budget).

---

# Code-level bugs found & fixed (not just logic errors)

These are *implementation* defects — crashes, wrong configs, missing handlers,
silent fallbacks — distinct from "right code, wrong answer". Many of the early
"the agent is dumb" symptoms were actually one of these.

Columns: **Bug site** = where the defect was; **Fix site** = exact location of
the fix (read those for the actual change). `lg` = `langgraph_ver/`,
`ga` = `gaia_agent/`. Line numbers are current as of 2026-06-11.

| # | Bug | Bug site | Fix site |
|---|-----|----------|----------|
| 1 | Dead OpenAI key (401 on every call) | `.env` `OPENAI_API_KEY` | OpenAI removed from new stack — `ga/providers.py` (no OpenAI import; DeepSeek via `_deepseek` / `deepseek_chat` L23-46) |
| 2 | Hardcoded non-existent `gpt-5` | `lg/agents/web_agent.py` (old L54, agent creation) | `lg/agents/web_agent.py:50-52` (`get_chat_llm`) + `lg/agents/web_agent.py:332-333`; new: `ga/agents.py:web_solve` L83,L107 (`get_chat_llm`) |
| 3 | Hardcoded expensive `gpt-4o` | `lg/agents/reasoning_agent.py` (old L31), `lg/agents/math_agent.py` (old L40) | `lg/agents/reasoning_agent.py:get_reasoning_llm L28-30` + model loop `L351`; `lg/agents/math_agent.py:38`; new: `ga/agents.py:reasoning_solve L39-81` |
| 4 | Import crash of video agent | `lg/agents/video_agent_smolvlm.py:11` (`AutoModelForImageTextToText`) | `lg/workflow.py:11-19` (try/except + stub `extract_youtube_url`) |
| 5 | Missing dependencies (ImportError chain) | env / `requirements.txt` | `requirements.txt` (added `langchain-openai`, `langchain-google-genai`, `langchain-community`, `langchain-core`, `openpyxl`, `beautifulsoup4`, `PyPDF2`, `huggingface-hub`) |
| 6 | `.model_name` AttributeError on Gemini | `lg/workflow.py:router` (old `llm.model_name`) | `lg/workflow.py:160` (`getattr(llm,"model",…) or getattr(llm,"model_name",…)`) |
| 7 | f-string brace crash (`unexpected '{' in field name`) | `lg/agents/reasoning_agent.py:strategic_analysis` (old `ChatPromptTemplate.from_messages` with literal `{}`) | `lg/agents/reasoning_agent.py:run_reasoning_agent L323-359` (single CoT, no template); new: `ga/agents.py:reasoning_solve L39` |
| 8 | Literal `<answer>` tag emitted | reasoning prompt (`FINAL ANSWER: <answer>`) | `lg/agents/reasoning_agent.py:343` + `ga/agents.py:_REASON_SYS L28` (`FINAL ANSWER: your_answer`) |
| 9 | `'str' object has no attribute 'get'` | `lg/tools/web_tools.py:search_web` fallbacks return strings | guard in callers: `ga/agents.py:web_solve L88-90` (`isinstance(r, dict)`) |
| 10 | Langfuse hard-coupled at import | `lg/workflow.py` (old top-level `CallbackHandler()`) | `lg/workflow.py:27-34` (`LANGFUSE_DISABLED` gate); runner sets it: `run_gaia.py:20`, `run_full_test.py` header |
| 11 | Lenient evaluator → false positives | `run_full_test.py:evaluate` (old substring + symbol-strip) | `run_full_test.py:evaluate L98-122`; new: `run_gaia.py:evaluate L55-78` (exact numeric eq, keep `¬→↔∨∧`) |
| 12 | `res` referenced before assignment on error path | `run_gaia.py:run_one` / `run_full_test.py:run_one` | `run_gaia.py:103` (`raw=""` before try) + `:108`; same pattern in `run_full_test.py` |
| 13 | Missing `.pptx` handler | `ga/files.py:extract_text` (returned `""`) | `ga/files.py:108-119` (python-pptx, text+tables per slide) |
| 14 | Excel read values only, not colours | `ga/files.py:extract_text` (openpyxl `data_only`) | `ga/files.py:93-106` (emit `coordinate=RRGGBB` fill colours); old equiv `lg/workflow.py` |
| 15 | Code-exec timeout on random/sleep loops | `ga/agents.py:code_solve` (relied on completion) | `ga/agents.py:code_solve L141-159` (run as hint @ L146, LLM reasons about control flow); sandbox `ga/sandbox.py:run_python` |
| 16 | Web context truncated to 1000 chars | `lg/agents/web_agent.py:direct_answer` (old `[:1000]`) | `lg/agents/web_agent.py:286-287` (`[:8000]`); new: `ga/agents.py:web_solve L99` (`page[:8000]`) |
| 17 | R1 latency hog (no cap, 217s) | reasoning tiebreak / file input | `ga/agents.py:reasoning_solve L70-72` (`wait_for … timeout=120`) + `ga/orchestrator.py:41-42` (bound file_text to 12K) |
| 18 | Round-robin hit dead Gemini keys | `lg/llms.py` / `ga/providers.py` key cycle | validation `lg/llms.py:_validate_gemini_keys L35-58`; new: `ga/providers.py:gemini_multimodal L80-95` (try every unique key); video also `ga/agents.py:video_solve L181` |

**Meta-lesson:** before blaming the model, check for (a) a dead key/wrong model
id, (b) an import that silently fell to a fallback, (c) a missing file-type
handler, (d) a template that ate a literal brace. Roughly half of the early
"low accuracy" was code, not reasoning.

---

# Integration — `app.py` now runs the new `gaia_agent` system

As of 2026-06-11, `app.py` (the HF Space submission entry point) imports
`GaiaAgent` from `gaia_agent.orchestrator` instead of the old
`langgraph_ver.workflow.OptimizedGAAIWorkflow`.

- The per-question loop now passes `file_name` + `task_id` (from the scoring
  API's `/questions` payload) into `agent.process_query(question, file_name,
  task_id)`, so the file/multimodal pipeline actually runs on the live Space.
- `langgraph_ver/` is kept as reference; only `tools/web_tools.py` from it is
  reused by `gaia_agent`.
- **Space secrets required:** `DEEPSEEK_API_KEY`, `GEMINI_API_KEY1..N`, and at
  least one GAIA-authorised `HF_TOKEN_*` (cbg/hust/forwork work; geminipro is
  403). Without these the agent can't run.
- **Note:** the submission loop is still sequential (`asyncio.run` per
  question). On the live set this can be slow when R1 tiebreaks fire; making it
  concurrent (like `run_gaia.py`) is a worthwhile follow-up.

Validation: `gaia_agent` scores **15/20 on the first-20** (vs the old system's
16/20) — comparable accuracy, but with **no OpenAI** and lower cost. The 1-point
gap is run-to-run nondeterminism (Q5 video, Q15 Tizin), not a capability loss;
and `gaia_agent` newly solves Q8 (.docx) which the old system could not fetch.
