# Architecture

High-level architecture of the two GAIA solver implementations. Diagrams are
Mermaid — paste into [mermaid.live](https://mermaid.live) to export a PNG/SVG for
slides. Only the load-bearing components are shown.

---

## 1. `gaia_agent/` — current system (DeepSeek + Gemini, no OpenAI)

A question is routed by a **deterministic file-extension rule** (or a one-call
DeepSeek classifier for text), handled by one **specialist agent**, then passed
through a **formatter** that enforces the GAIA answer format. Text agents run on
**DeepSeek** (no rate limit → concurrency); multimodal agents on **Gemini**
(the only multimodal provider).

```mermaid
flowchart TD
    Q["Question + file_name + task_id"] --> D{"Dispatcher<br/>file-extension rule · else DeepSeek text classifier"}

    %% file-based routes
    D -->|".png / .jpg"| VIS
    D -->|".mp3 / .wav"| AUD
    D -->|"YouTube URL"| VID
    D -->|".py"| CODE
    D -->|".docx / .xlsx / .pptx / .pdf"| DOC["Extract text"]
    %% text routes
    D -->|"needs lookup"| WEB
    D -->|"logic / puzzle"| REAS
    D -->|"calculation"| MATH
    D -->|"other"| GEN
    DOC --> REAS

    subgraph MM["Multimodal agents · Gemini 2.5 Flash"]
        VIS["Vision"]
        AUD["Audio"]
        VID["Video"]
    end

    subgraph TX["Text agents · DeepSeek (V3 / R1)"]
        WEB["Web<br/>search + read + Wayback fallback"]
        REAS["Reasoning<br/>3× V3 vote + R1 tiebreak"]
        MATH["Math<br/>+ Python sandbox"]
        CODE["Code<br/>run + reason"]
        GEN["General"]
    end

    FILES["File layer<br/>HF token → public mirror"] -. fetch bytes .-> VIS & AUD & CODE & DOC

    MM --> FMT
    TX --> FMT
    FMT["Formatter · DeepSeek<br/>+ deterministic normalize<br/>(units · yes/no · exact wording)"] --> ANS(["FINAL ANSWER: …"])
```

**Key ideas:** capability-based provider split (DeepSeek=text, Gemini=multimodal);
reasoning uses a self-consistency **vote** to fight LLM non-determinism; two-tier
async concurrency (text 8 / multimodal 4) keeps latency low and stays inside the
Gemini free-tier RPM.

---

## 2. `langgraph_ver/` — original system (LangGraph StateGraph)

A **LangGraph state machine**: an LLM **router** picks one agent type via
conditional edges; the chosen specialist runs; `format_response` emits the final
answer. A separate **LLM layer** (`llms.py`) chooses the backend per call, and a
**tools layer** (`web_tools.py`) provides search/read utilities.

```mermaid
flowchart TD
    Q["Question"] --> R{"Router · LLM<br/>pick agent type"}

    subgraph SG["LangGraph StateGraph"]
        R -->|web| WEB["Web agent"]
        R -->|video| VID["Video agent"]
        R -->|reasoning| REAS["Reasoning agent"]
        R -->|math| MATH["Math agent"]
        R -->|creative| CRE["Creative agent"]
        R -->|general| GEN["General agent"]
        WEB & VID & REAS & MATH & CRE & GEN --> FMT["format_response<br/>→ FINAL ANSWER"]
    end
    FMT --> E(["END"])

    LLMS["LLM layer · llms.py<br/>get_chat_llm routes by model prefix<br/>→ DeepSeek / Gemini / OpenAI"] -. provides LLM .-> R
    TOOLS["Tools · web_tools.py<br/>Tavily / SerpAPI search · read_webpage · read_pdf (+Wayback)"] -. tools .-> WEB
```

**Key ideas:** declarative graph with one router and a fan-out of specialist
nodes; provider chosen centrally by model-name prefix; reusable web tools. This
is the codebase the new system grew out of (and still reuses `web_tools.py`).

---

## 3. What changed (old → new)

| Aspect | `langgraph_ver` (old) | `gaia_agent` (new) |
|--------|----------------------|--------------------|
| Orchestration | LangGraph StateGraph | plain async (lighter, easier concurrency) |
| Input | text query only | text **+ file/attachment + task_id** |
| Routing | LLM router only | **file-extension rule first**, LLM classifier for text |
| Modalities | web / reasoning / math / video | **+ vision, audio, code, document QA** (7 total) |
| Reasoning | single call | **3× self-consistency vote + R1 tiebreak** |
| Providers | OpenAI + DeepSeek + Gemini | **DeepSeek + Gemini only (no OpenAI)** |
| Concurrency | sequential per question | **two-tier async** (text / multimodal) |

Both feed the same downstream contract: a single `FINAL ANSWER: …` line. The new
system is wired into `app.py` (the HF Space submission entry point).
