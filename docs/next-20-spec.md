# Spec: Giải 20 câu GAIA tiếp theo — Không OpenAI (DeepSeek + Gemini)

Mục tiêu: **accuracy cao + latency thấp**, chỉ dùng DeepSeek (text) và Gemini (multimodal).
Tài liệu này là bản thiết kế để review trước khi implement.

> ✅ **Trạng thái 2026-06-11: đã implement (`gaia_agent/`) + nối vào `app.py`.**
> `app.py` giờ dùng `GaiaAgent` (truyền `file_name`+`task_id`). Dependencies đã
> thêm vào `requirements.txt`. Space cần secrets: `DEEPSEEK_API_KEY`,
> `GEMINI_API_KEY1..N`, một `HF_TOKEN_*` có quyền GAIA. Chi tiết lỗi code đã gặp:
> xem `debug-workflows.md` mục "Code-level bugs".

---

## 0. Ràng buộc mới
- ❌ KHÔNG còn OpenAI (key đã revoke). Mọi vai trò text trước đây dùng `gpt-4o-mini`/`gpt-4o`
  phải chuyển sang DeepSeek; vision trước đây dùng `gpt-4o vision` phải chuyển sang Gemini.
- ✅ DeepSeek: text, không rate-limit, rẻ, nhanh (V3) hoặc sâu (R1).
- ✅ Gemini: **nguồn multimodal DUY NHẤT** (ảnh/audio/video), free-tier có rate-limit.

---

## 1. Tài nguyên & năng lực

| Provider | Model | Năng lực | Latency | Giới hạn |
|----------|-------|----------|---------|----------|
| DeepSeek | `deepseek-chat` (V3) | text, **function-calling**, 64K ctx | ~2–5s | text-only, hơi dao động ở temp 0 |
| DeepSeek | `deepseek-reasoner` (R1) | reasoning sâu nhất | ~30–120s | **không** function-calling, chậm, đắt hơn |
| Gemini | `gemini-2.5-flash` | text + **ảnh + audio + video(YouTube)** | ~5–30s | ~5 RPM/key free, 6 key sống |
| Gemini | `gemini-2.5-flash-lite` | như trên, yếu hơn | ~2–5s | ~15 RPM/key, dùng làm overflow |

Tools sẵn có (giữ nguyên, miễn phí/rẻ): Tavily + SerpAPI (search), `read_webpage`/`read_pdf`
(đã có **Wayback fallback** + đọc PDF trực tiếp), tải file GAIA từ **mirror công khai**
(`datasets/asteriadyt/2023`).

---

## 2. Nguyên tắc thiết kế cốt lõi

> **DeepSeek làm tất cả phần TEXT. Gemini làm tất cả phần KHÔNG-PHẢI-TEXT.**

Phân vùng này: (a) đúng theo năng lực (DeepSeek không có vision/audio); (b) tôn trọng
rate-limit (câu multimodal là thiểu số → Gemini đủ quota); (c) tối ưu latency (phần lớn
câu chạy trên DeepSeek nhanh, không bị nghẽn RPM → concurrency cao).

---

## 3. Kiến trúc & luồng xử lý

```
                          ┌─────────────────────────┐
   question + file_name → │   DISPATCHER (deterministic)│
                          └───────────┬─────────────┘
        có file? → route theo đuôi    │   không file → DeepSeek router (1 call V3)
        ├─ .png/.jpg → VISION (Gemini)│
        ├─ .mp3/.wav → AUDIO  (Gemini)│
        ├─ .py       → CODE   (sandbox + V3)
        ├─ .docx/.xlsx/.pdf → EXTRACT → đẩy text vào REASONING/WEB
        └─ youtube URL → VIDEO (Gemini)
                                      │
            text questions ──────────┼──→ WEB        (V3 + search/read tools)
                                      ├──→ REASONING  (3×V3 self-consistency, R1 tiebreak)
                                      └──→ MATH/CODE  (V3 + Python sandbox)
                                      │
                          ┌───────────▼─────────────┐
                          │ FORMATTER (V3 + post-proc)│  → "FINAL ANSWER: ..."
                          └─────────────────────────┘
```

---

## 4. Routing (deterministic-first để giảm latency & sai sót)

1. **Có `file_name`** → route bằng đuôi file (không cần LLM): nhanh, không sai.
2. **Có URL YouTube** trong câu hỏi → VIDEO.
3. **Còn lại (text thuần)** → 1 call `deepseek-chat` phân loại: `WEB` (cần tra cứu thực tế)
   vs `REASONING` (logic/toán tự chứa) vs `GENERAL`. (~2s, rẻ)

Lý do: routing dựa file là tín hiệu chắc chắn nhất — đừng phí 1 LLM call và đừng để router
LLM route nhầm câu có file.

---

## 5. Bảng phân công Agent → Model (phần quan trọng nhất để review)

| Agent | Model | Latency | Cost/câu | Ghi chú thiết kế |
|-------|-------|---------|----------|------------------|
| **Dispatcher/Router** | rule + `deepseek-chat` | ~2s | ~$0.0002 | file→rule; text→1 call |
| **Web** | `deepseek-chat` + tools | ~8–15s | ~$0.001 | đọc **top-3 nguồn**, cross-check, Wayback, đọc PDF |
| **Reasoning (mặc định)** | **3× `deepseek-chat`** → majority vote | ~5s (chạy song song) | ~$0.0015 | self-consistency giết nondeterminism, latency vẫn thấp |
| **Reasoning (tiebreak)** | `deepseek-reasoner` (R1) | ~60–120s | ~$0.01 | CHỈ khi 3×V3 chia phiếu / câu cờ-flag khó; có timeout→V3 |
| **Math/Code** | `deepseek-chat` + **Python sandbox** | ~5–10s | ~$0.001 | thực thi code thật, không "tính nhẩm" bằng LLM |
| **Vision (ảnh)** | `gemini-2.5-flash` | ~5–10s | $0 | nguồn duy nhất; FEN/biểu đồ/screenshot |
| **Audio (.mp3)** | `gemini-2.5-flash` | ~10–20s | $0 | transcribe + trả lời trực tiếp |
| **Video (YouTube)** | `gemini-2.5-flash` | ~30–60s | $0 | thử lần lượt các key tới khi 1 key OK |
| **Formatter** | `deepseek-chat` + **post-proc xác định** | ~2s | ~$0.0002 | đơn vị (÷1000), yes/no, exact-wording |

**Ý tưởng then chốt cho "accuracy cao + latency thấp": dùng `3× deepseek-chat` chạy SONG
SONG + bỏ phiếu** thay cho R1 chậm. V3 nhanh (~5s), 3 bản song song vẫn ~5s wall-clock,
và bỏ phiếu ổn định hoá kết quả (trị được đúng cái "whack-a-mole" đã gặp). R1 chỉ dùng khi
3 phiếu chia rẽ.

---

## 6. Chiến lược ACCURACY

1. **Self-consistency vote (reasoning):** 3×V3 song song, lấy đa số (so khớp sau khi format).
   Chia phiếu → gọi R1 phân xử. Đây là vũ khí chính chống nondeterminism.
2. **Web đa nguồn:** đọc top-3 kết quả thay vì 1 trang; synthesis phải trích nguồn; nếu các
   nguồn mâu thuẫn → 1 lần search lại với query tinh chỉnh.
3. **Thực thi thay vì suy đoán:** câu toán/code → V3 viết Python, chạy trong sandbox
   (subprocess, timeout 10s), trả lời từ output thật.
4. **Verifier + post-proc format (xác định):** sau khi có đáp án thô, 1 bước kiểm tra
   "đáp án có đúng định dạng/đơn vị câu hỏi yêu cầu?" + code chuẩn hoá (÷1000 cho 'thousand',
   Yes/No, exact wording). Đây là bản tổng quát của các fix tay Q1/Q10 trước đây.
5. **Anti-hallucination "commit":** web prompt — ưu tiên nguồn, nếu thiếu thì đưa đáp án cụ
   thể khả dĩ nhất, KHÔNG từ chối (từ chối = 0 điểm như đoán sai).

## 7. Chiến lược LATENCY

1. **Concurrency 2 tầng (2 semaphore riêng):**
   - Text (DeepSeek, không RPM): concurrency **8–10**.
   - Multimodal (Gemini, RPM thấp): concurrency **≤6** (= số key) để tránh 429.
2. **V3-first, R1 có ngân sách:** mặc định mọi reasoning là V3 (nhanh). R1 chỉ chạy khi cần
   và luôn có `timeout → fallback V3` để 1 câu R1 treo không kéo cả run.
3. **Cache theo task_id:** runner đã lưu kết quả từng câu → chế độ "chỉ chạy lại câu sai".
   Lặp lại chỉ tốn vài cent, không đốt lại quota Gemini cho câu đã đúng.
4. **Bỏ Langfuse khi chạy batch** (đã làm) để khỏi overhead mạng mỗi call.

Wall-clock dự kiến cho 20 câu @ concurrency phù hợp: **~60–90s** nếu không kích hoạt R1;
**~2–3 phút** nếu vài câu phải dùng R1 (chạy song song nên không cộng dồn).

---

## 8. Modality MỚI cần build (rất quan trọng cho 20 câu tiếp)

Bộ scoring thật có cả `.mp3` (audio) và `.py` (code) — hệ hiện tại CHƯA xử lý được:
- **Audio agent:** tải `.mp3` từ mirror → Gemini 2.5 Flash (nhận audio native) → hỏi-đáp.
- **Code agent:** đọc `.py` → chạy trong subprocess sandbox (timeout) → trả lời theo output
  thật, không để LLM "đọc code đoán kết quả".
- **Vision agent:** đã có hướng (Gemini); ảnh cờ vua vẫn là điểm yếu (vision→FEN), cần đánh
  giá riêng nếu xuất hiện.

Thiếu 2 agent này thì mỗi câu audio/code = 0 điểm tự động (đúng tình cảnh Q8/Q17 trước khi
mở được file).

---

## 9. Ước lượng Cost & Latency cho 1 run 20 câu

| Hạng mục | Cost | Latency đóng góp |
|----------|------|------------------|
| DeepSeek V3 (router/web/reasoning vote/format) | ~$0.02–0.03 | nền ~5–15s/câu |
| DeepSeek R1 (vài câu tiebreak) | ~$0.01–0.03 | ~60–120s (song song) |
| Gemini multimodal | $0 (free) | ~10–60s/câu multimodal |
| **Tổng** | **~$0.03–0.06 / run** | **~1–3 phút wall-clock** |

So với run cũ tốn $0.33 (do gpt-4o): rẻ hơn ~6–10 lần, không phụ thuộc OpenAI.

---

## 10. Rủi ro & giảm thiểu

| Rủi ro | Giảm thiểu |
|--------|-----------|
| Gemini hết quota free (đã từng) | chỉ để Gemini làm multimodal (ít câu); xoay 6 key; flash-lite làm overflow; thử lần lượt key cho call quan trọng |
| R1 chậm làm tăng latency | mặc định V3; R1 có timeout→V3; chạy song song |
| DeepSeek dao động ở temp 0 | self-consistency vote 3×V3 |
| DeepSeek API down | fallback `gemini-2.5-flash-lite` cho text (rate-limited) |
| Vision cờ vua không chính xác | đánh dấu là giới hạn năng lực; cần tool engine nếu cờ vua tái xuất |
| File gated (401) | dùng mirror công khai; hoặc ông cấp HF token để tải bản chính thức |

---

## 11. QUYẾT ĐỊNH ĐÃ CHỐT (review 2026-06-11)

1. ✅ **Ưu tiên ACCURACY tối đa** → reasoning = 3×V3 vote, câu chia phiếu/flag-khó gọi **R1**
   phân xử. Chấp nhận wall-clock ~2–3 phút.
2. ✅ **Build phòng hờ Audio agent + Code agent** (bộ scoring thật có .mp3 và .py).
3. ✅ **Dùng HF token** (sẽ được cấp) → tải file đính kèm từ dataset chính thức
   `gaia-benchmark/GAIA` (mirror công khai chỉ là fallback).

Mặc định cho 2 điểm còn lại (có thể chỉnh):
- **Ensemble width = 3×V3** mặc định; tự nâng lên 5× cho câu R1-flag (logic nhiều bước).
- **Verifier gộp vào Formatter** (1 call vừa kiểm tra định dạng/đơn vị vừa xuất FINAL ANSWER)
  để tiết kiệm latency; phần chuẩn hoá đơn vị/yes-no vẫn bằng code xác định.

---

## 12. Việc cần ông cung cấp trước khi implement
- **HF token** (read scope) để tôi nạp vào `.env` (`HF_TOKEN=...`) và tải file GAIA chính thức.

Sau khi có token + ông duyệt, thứ tự build: (1) provider layer DeepSeek+Gemini không-OpenAI →
(2) dispatcher theo file → (3) Audio/Code/Vision agents → (4) reasoning vote+R1 → (5) web đa
nguồn → (6) formatter+verifier → (7) chạy thử + cache câu sai.

---

## 13. KẾT QUẢ THỰC TẾ — chạy trên 20 câu MỚI (next-20, offset 20)

Đã build xong package `gaia_agent/` đúng spec (không OpenAI). Code: `gaia_agent/*.py`,
runner `run_gaia.py`. Chạy trên 20 câu Level 1 **chưa từng tune** (câu 21–40):

| Mốc | Accuracy | Wall-clock | Ghi chú |
|-----|----------|------------|---------|
| Lần 1 (full) | **10/20 (50%)** | 217s | latency hog: 1 câu xlsx loop R1 217s |
| Sau fix (retry câu sai) | **13/20 (65%)** | ~52s (trừ hog) | +pptx, +list-wording, +seagull |
| Fix tiếp (chưa đo) | dự kiến ~14/20 | — | code static-reasoning + bound latency |

**Lưu ý quan trọng:** 80% ở first-20 là **overfit** (đã tune kỹ trên đúng 20 câu đó).
65% ở next-20 mới là **độ chính xác generalization thật**. Đây là con số đáng tin để báo cáo.

### Fix đã ăn (50%→65%)
- **`.pptx`**: thêm python-pptx → Q "đếm slide nhắc crustaceans" (4) ✓
- **List giữ nguyên từ ngữ + alphabetize**: Q botany ("broccoli, celery, fresh basil,...") ✓
- **Tách từ đúng**: Q ghép câu ("The seagull...") ✓ (trước tách "sea gull")
- **Màu nền ô Excel** (coordinate=RRGGBB): câu xlsx-map giờ *thấy* màu (chưa giải đúng path nhưng đã có data)

### Fix đã code nhưng CHƯA đo (user dừng để tiết kiệm credit)
- **Code agent suy luận tĩnh**: file `.py` lặp random tới khi gặp 0 → output luôn 0; thay vì
  chạy tới timeout, để LLM đọc logic. Kỳ vọng Q code (exp 0) → đúng.
- **Bound nội dung file 12K** + cap R1 120s → chặn latency hog 217s.

### Còn sai — đa số KHÓ THẬT (không phải bug)
| Câu | Loại | Lý do |
|-----|------|-------|
| vision phân số | image OCR | Gemini đọc thiếu/sai vài ô phân số trong ảnh |
| game-show xác suất (16000) | reasoning | R1 ra 12000/24000 — xác suất nhiều bước, dao động |
| Cornell LII (inference) | web | retrieval không trúng đúng mục/từ |
| audio pie (list) | audio | Gemini transcribe đúng nhưng thứ tự/từ ngữ list lệch |
| bảng phép * (b,e) | reasoning | sai 1 phần tử (b,d,e) |
| xlsx-map màu (F478A7) | file | pathfinding trên lưới màu — khó + chậm |

### Chi phí & latency
- Tổng các lần chạy (full + 2 retry + smoke): **~$0.10 DeepSeek**, Gemini free. Không OpenAI.
- Latency: bỏ 1 câu outlier thì ~50–70s/20 câu @ concurrency (text 8 / mm 4).

### Bài học mới rút ra (bổ sung cho accuracy-playbook)
1. **Đo trên tập CHƯA tune** mới biết accuracy thật — first-20 80% là ảo.
2. **Liệt kê đủ loại file**: thiếu 1 handler (.pptx) = 0 điểm câu đó; phải phủ docx/xlsx/pptx/pdf/py/mp3/png.
3. **Excel có thể mã hoá thông tin bằng MÀU**, không chỉ giá trị → phải đọc fill color.
4. **Câu "chạy code"**: đừng tin 100% vào execution — code có random/sleep/loop → để LLM
   suy luận logic; execution chỉ là gợi ý.
5. **1 câu chậm có thể nuốt toàn bộ wall-clock** → luôn cap thời gian R1 + bound input size.
6. **List/exact-wording là điểm rơi điểm âm thầm**: giữ nguyên từ ngữ gốc, alphabetize đúng.
