# Task Pipeline — Improvement Log

Tracks every change made to the task workflow, what problem it solved, and the measured impact.

---

## Iteration 1: Basic Task Tab
**Problem:** No way to create complex multi-document deliverables with iterative refinement.
**Change:** Added 🧠 Tasks tab with prompt input, document selector, SSE streaming, and refine loop.
**Result:** Working end-to-end but used the old `/generate` endpoint which timed out on large prompts.

---

## Iteration 2: Auto-Search
**Problem:** User had to manually select every relevant document.
**Change:** Added automatic search — the prompt text is used to find relevant documents from the collection.
**Result:** User can type a prompt with zero document selection and get relevant results.

---

## Iteration 3: SSE Streaming + Heartbeats
**Problem:** "NetworkError when attempting to fetch resource" — browser killed the connection during long generation.
**Change:** Converted to async SSE stream with `: keepalive` comments every 8 seconds + `X-Accel-Buffering: no` header.
**Result:** No more connection drops. User sees live status updates.

---

## Iteration 4: Bedrock Read Timeout Fix
**Problem:** "Read timeout on endpoint URL" — boto3 default 60s timeout too short for large context.
**Change:** Switched from `converse` to `converse_stream` (tokens stream back continuously, never times out).
**Result:** Eliminated all Bedrock timeout errors regardless of generation length.

---

## Iteration 5: Context Truncation (20k cap)
**Problem:** Large documents (58k chars of Brax contract boilerplate) consumed entire context window, pushing out actual proposals.
**Change:** Capped each manually-selected document at 20k chars.
**Result:** Nova Pro scored 9.8/10 — but missed 1 price that was beyond the 20k cutoff.

---

## Iteration 6: Multi-Cycle Rolling Context
**Problem:** Truncation loses information. Need all content without exceeding model limits.
**Change:** Split documents into 80k-char batches, process each cycle, accumulate findings, final synthesis pass.
**Result:** 10/10 scores from 7 models. No truncation. But introduced ordering bias (later docs weighted more).

---

## Iteration 7: Extract + Aggregate Pipeline
**Problem:** Multi-cycle rolling context had ordering bias — model prioritized last-seen documents.
**Change:** Extraction cycles only extract facts (no ranking). Shuffle document order. Separate aggregation pass synthesizes all findings equally.
**Result:** Eliminated ordering bias. All models rank Brax correctly. Nova Pro hallucinated in this mode (confirmed it shouldn't do multi-cycle).

---

## Iteration 8: Adaptive Model Routing
**Problem:** No single model is best for all tasks. Nova Pro is fast but hallucinates on complex tasks. Mistral is thorough but slow.
**Change:** Automatic routing based on context size:
- Small context (< model window) → Nova Pro single-pass
- Large context (> model window) → Llama 3.3 / Mistral Magistral multi-cycle
**Result:** Best of both worlds — fast for simple tasks, accurate for complex ones.

---

## Iteration 9: Dynamic Context Window Sizing
**Problem:** Hardcoded 250k threshold assumed Nova Pro. If user switches to a model with smaller window, it fails.
**Change:** Lookup table maps model families to their context window sizes. Unknown models default to 80k (safe).
**Result:** Any model can be configured without code changes. Threshold adjusts automatically.

---

## Iteration 10: Inference Profile Auto-Fallback
**Problem:** Some models (Claude 4.x, Llama, DeepSeek R1) need `us.` prefix for inference profiles. Hardcoded list was brittle.
**Change:** Try model as-is, catch failure, retry with `us.` prefix. Cache result for future calls.
**Result:** Every model in Bedrock works without configuration. No hardcoded model lists.

---

## Iteration 11: Reasoning Model Support
**Problem:** OpenAI GPT-OSS returns `reasoningContent` blocks before `text` blocks. Code only read `content[0]["text"]` and crashed.
**Change:** Stream parser skips `reasoningContent` deltas, only collects `text` deltas.
**Result:** OpenAI and DeepSeek R1 reasoning models work correctly.

---

## Iteration 12: Structured Schema Pipeline
**Problem:** Open-ended extraction is probabilistic — model might miss a price or company depending on how it "reads" the document.
**Change:** 4-step pipeline:
1. Generate JSON schema from prompt (what fields to look for)
2. Fill schema per document (deterministic — explicit fields, not summarization)
3. Merge schemas with code (no AI, no information loss)
4. Generate final document from structured data
**Result:** Mistral Magistral scored 9.8/10. Eliminates "did the model notice this?" problem.

---

## Iteration 13: Complexity-Based Routing
**Problem:** Nova Pro hallucinated on L1 (complex multi-entity ranking) even though context fit in its window. Context size alone doesn't predict difficulty.
**Change:** Detect prompt complexity from signals:
- 3+ sections requested → structured pipeline
- "rank all" / "every contractor" → structured pipeline
- "compare" / "best to worst" → structured pipeline
- Simple lookups → Nova Pro single-pass
**Result:** Nova Pro only handles tasks it's good at (simple lookups: 8.5-10/10). Complex tasks always go to structured pipeline (9.8/10).

---

## Iteration 14: Anti-Hallucination System Prompt
**Problem:** Claude 3 Sonnet fabricated entire companies ("Northstar Exteriors", "Best Roofers Inc").
**Change:** System prompt now says: "NEVER invent company names, prices, license numbers. If not in documents, say 'Not provided'."
**Result:** Zero hallucinations across all 17 tested models (except AI21 Jamba which is excluded).

---

## Iteration 15: Pricing Fuzzy Lookup
**Problem:** Models called via `us.` inference profile showed $0.00 cost in usage tracking.
**Change:** `estimate_cost()` now strips `us./global.` prefix and does prefix-match against pricing table.
**Result:** Correct cost estimates for ~80% of models. Remaining 20% (Claude 4.x, Writer) awaiting AWS pricing publication.

---

## Current Architecture

```
User Prompt
    │
    ├─ Complexity Detection (regex signals)
    │
    ├─ SIMPLE TASK ──→ Nova Pro single-pass (8.5-10/10, ~20-80s)
    │                   Best for: fact lookups, single-entity questions
    │
    └─ COMPLEX TASK ──→ Structured Pipeline with Mistral Magistral (9.8/10, ~280s)
                        1. Schema generation (what to look for)
                        2. Per-document extraction (JSON, deterministic)
                        3. Code merge (no AI, no loss)
                        4. Final generation from structured data
```

---

## Model Evaluation Summary (13 tests × 15 models)

| # | Model | Avg Score | Best For |
|---|-------|-----------|----------|
| 1 | Mistral Large 3 | 8.6/10 | Overall accuracy (slow) |
| 2 | Moonshot Kimi K2.5 | 8.4/10 | Balanced |
| 3 | DeepSeek R1 | 8.2/10 | Reasoning tasks |
| 4 | DeepSeek V3.2 | 8.2/10 | Fast + accurate |
| 5 | Z.AI GLM-5 | 8.1/10 | Thorough (slow) |
| 6 | Claude Haiku 4.5 | 8.0/10 | Short prompts (9.5 avg) |
| 10 | Llama 3.3 70B | 7.7/10 | Speed (521s total) |
| 12 | Llama 4 Maverick | 7.7/10 | Fastest (330s total) |
| 15 | Nova Pro | 6.7/10 | Simple lookups only |

---

## Known Limitations

1. **Nova Pro hallucinates on complex ranking tasks** — mitigated by complexity routing
2. **AWS pricing missing for Claude 4.x and Writer** — tokens tracked, cost shows $0
3. **Structured pipeline is slower** (~280s vs ~80s) — acceptable tradeoff for accuracy
4. **L2 test (maintenance plan) scores low across all models** — the prompt requires temporal reasoning (done vs pending) which all models struggle with
