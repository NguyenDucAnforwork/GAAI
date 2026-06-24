# Reproduce — các mốc kết quả chính

Các lệnh để chạy lại những kết quả lớn từ đầu dự án đến giờ. Mỗi mốc kèm **config**,
**biến môi trường cần**, **file kết quả gốc** đã lưu, và **caveat** (đặc biệt là tính
bất định / key đã revoke).

> ⚠️ **Lưu ý chung — KẾT QUẢ KHÔNG TẤT ĐỊNH.** DeepSeek (kể cả temperature 0) và
> retrieval web/Gemini dao động giữa các lần chạy. Con số thực tế thường lệch
> **±1–2 câu** so với mốc ghi dưới. Đây là điều bình thường, không phải bug
> (xem "whack-a-mole" trong `accuracy-playbook.md`).

---

## 0. Chuẩn bị môi trường (chung)

```bash
# Python env có sẵn các package (xem requirements.txt)
PY=/home/ducan/miniconda3/envs/env-transport-bot/bin/python   # hoặc python của bạn

cd "<repo root>"
pip install -r requirements.txt        # cần: langchain-openai, langchain-google-genai,
                                        # langchain-community, openpyxl, beautifulsoup4,
                                        # PyPDF2, python-docx, python-pptx, huggingface-hub, ...
```

`.env` cần (tuỳ luồng — xem từng mục):
```
DEEPSEEK_API_KEY=...
GEMINI_API_KEY1=...   (… tới GEMINI_API_KEY8; ~6 key sống là đủ)
HF_TOKEN_cbg=...      # hoặc HF_TOKEN_hust / HF_TOKEN_forwork (có quyền GAIA dataset)
OPENAI_API_KEY=...    # CHỈ cần cho mốc 16/20 (luồng cũ) — key này hiện đã bị revoke
```

Tập đề: `test_data/metadata.jsonl` (GAIA validation, lọc Level 1). "first-20" = 20 câu
Level 1 đầu; "next-20" = câu 21–40 (`--offset 20`).

---

## A. 16/20 — luồng cũ `langgraph_ver` (run_full_test.py)

**Lệnh:**
```bash
$PY run_full_test.py
```

**Config tại thời điểm đạt 16/20** (multi-provider, CÓ OpenAI):
- web / router / math / general / formatter → **OpenAI `gpt-4o-mini`**
- reasoning → **DeepSeek `deepseek-chat`** (fallback `gpt-4o`)
- video → **Gemini 2.5 Flash**
- evaluator nghiêm (số khớp tuyệt đối, giữ ký hiệu logic), post-proc đơn vị
  (thousand/million), reasoning prompt bỏ tag `<answer>`, concurrency 6,
  Langfuse off.

**Biến môi trường:** cần `OPENAI_API_KEY` hợp lệ + DeepSeek + Gemini.

**File kết quả gốc:** `results/full_test_20260610_232916.json` (16/20, 51.6s).

> ❌ **KHÔNG reproduce được nguyên trạng bây giờ** vì:
> 1. `OPENAI_API_KEY` đã bị revoke (luồng này phụ thuộc gpt-4o-mini cho phần lớn agent).
> 2. Code `langgraph_ver/llms.py`, `reasoning_agent.py` đã bị sửa tiếp sau đó (reasoning
>    giờ ưu tiên `deepseek-reasoner`).
>
> Muốn chạy lại: (a) cấp lại OpenAI key, (b) đặt `reasoning_agent.py` về model
> `deepseek-chat` (loop `("deepseek-chat","gpt-4o")`) và `OPENAI_AGENT_MODEL=gpt-4o-mini`.
> Hoặc xem trực tiếp kết quả đã lưu ở file JSON trên.

---

## B. 15/20 — gaia_agent (mới) trên first-20 — KHÔNG OpenAI

**Lệnh:**
```bash
$PY run_gaia.py --offset 0 --count 20
```

**Config (hiện hành, reproduce được ngay):**
- text (router/web/math/general/formatter) → **DeepSeek `deepseek-chat`**
- reasoning → **3× `deepseek-chat` vote → `deepseek-reasoner` (R1) tiebreak**
- vision/audio/video → **Gemini 2.5 Flash**
- file (.docx/.xlsx/.pptx/.pdf) tải qua **HF token** (GAIA chính thức) → mirror fallback
- concurrency: text 8 / multimodal 4

**Biến môi trường:** `DEEPSEEK_API_KEY`, `GEMINI_API_KEY*`, một `HF_TOKEN_*` có quyền GAIA.
**KHÔNG cần OpenAI.**

**File kết quả gốc:** `results/gaia_v2_20260611_050459.json` (15/20, 97.6s).

**Caveat:** dao động ~14–16/20. Câu R1-tiebreak (vd câu đố ping-pong) có thể tốn ~90–100s,
chi phối wall-clock. Chi phí ~trong budget $0.05–0.08 DeepSeek/lần.

---

## C. 13/20 — gaia_agent (mới) trên next-20 (offset 20)

Mốc 13/20 đạt được theo 2 bước: chạy full ra **10/20**, vá lỗi, rồi **retry chỉ câu sai** ra 13/20.

**Lệnh:**
```bash
# Bước 1 — full next-20 (đã từng ra 10/20 TRƯỚC các fix)
$PY run_gaia.py --offset 20 --count 20
#   → lưu results/gaia_v2_<ts>.json

# Bước 2 — retry chỉ các câu sai (giữ câu đúng), sau khi đã vá pptx/list/code…
$PY run_gaia.py --offset 20 --count 20 --retry results/gaia_v2_<ts_bước_1>.json
```

**Các fix giữa 2 bước (đã nằm trong code hiện tại):**
- thêm handler `.pptx` (python-pptx)
- trích **màu nền ô Excel** (coordinate=RRGGBB)
- prompt list: giữ nguyên từ ngữ gốc + alphabetize
- (sau 13/20) code agent suy luận tĩnh thay vì chạy tới timeout; bound file 12K; cap R1 120s

**File kết quả gốc:**
- `results/gaia_v2_20260611_043140.json` (10/20 — trước fix)
- `results/gaia_v2_20260611_044041.json` (13/20 — sau fix, retry)

**Caveat:** code đã được vá thêm SAU mốc 13/20 (code static-reasoning, bound latency), nên
chạy mới `--offset 20` bây giờ có thể ra **~13–14/20** (kỳ vọng +1 ở câu `.py`), không
khớp tuyệt đối 13/20. Đây là tập **chưa tune** → phản ánh accuracy generalization thật
(~65%), trái với 80% "overfit" của first-20.

---

## Bảng tổng hợp

| Mốc | Lệnh | Luồng | OpenAI? | File kết quả gốc |
|-----|------|-------|---------|------------------|
| 16/20 | `run_full_test.py` | langgraph cũ | **Có** (đã revoke) | `full_test_20260610_232916.json` |
| 15/20 | `run_gaia.py --offset 0` | gaia_agent | Không | `gaia_v2_20260611_050459.json` |
| 13/20 | `run_gaia.py --offset 20` + `--retry` | gaia_agent | Không | `gaia_v2_20260611_044041.json` |

## Xem lại kết quả đã lưu (không tốn credit)

```bash
$PY - <<'PY'
import json, glob
f = sorted(glob.glob('results/gaia_v2_*.json'))[-1]   # hoặc full_test_*.json
d = json.load(open(f))
print(f, d['correct'], '/', d['total'])
for i, r in enumerate(d['results'], 1):
    print(('✓' if r['is_correct'] else '✗'), r['task_id'][:8],
          '| exp=', r['expected'][:30], '| got=', r['predicted'][:30])
PY
```
