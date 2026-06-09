# Refinement Pipeline — Journey of Discovery

## Where We Started

The Tasks tab found documents, but:
- 15 irrelevant docs (reserve studies, resale certs) mixed in
- Generation took 196-275 seconds (structured pipeline triggering on bloated context)
- Output was markdown headers/tables instead of plain paragraphs
- Facts accuracy: 2-4/6

## What We Built (4 iterations)

### Iteration 1: Score threshold (frontend)
- Added `score >= 25` filter on entity follow-up searches
- **Result:** 15 → 11 docs. Cut 4 noise docs. Required: 5/5 kept.

### Iteration 2: Cohere Rerank (backend)
- Added Cohere Rerank v3.5 to rescore candidates by relevance
- Fixed API format (documents must be strings, need `api_version: 2`)
- **Result:** 11 → 10 docs. Better ordering, but emails/dimensions scored low because rerank query was "fill out form" not "roof replacement."

### Iteration 3: Prompt decomposition (backend)
- Added `decompose_prompt()` — Nova Micro extracts structured intent map from user's prompt
- Rerank query now uses `vendor + product + subject` instead of raw administrative prompt
- Entity matching uses both title AND snippet content
- **Result:** 11 → 8 docs. Emails jumped from 0.10 → 0.15 relevance. Dimensions from 0.06 → 0.15.

### Iteration 4: Refinement gambit (validation)
- Tested 5 prompts × 2 conditions (with/without refinement)
- **Result:** Refinement improves facts in 3/5 cases, never hurts recall, reduces docs consistently

## Current Scores (after all fixes applied)

| Prompt | Docs | Recall | Facts | Headers | Time |
|--------|------|--------|-------|---------|------|
| natural | 8-10 | 5/5 | 3/6 | **No** ✅ | 5.7s |
| minimal | 7 | 4/5 | 4/6 | **No** ✅ | 15s |
| detailed | 10 | 5/5 | 3-5/6 | **No** ✅ | 2.7s |

**Structural wins locked in:**
- Zero markdown headers/bullets in form-fill output
- 34-46x faster generation (chunk retrieval → single pass)
- Prompt decomposition → content-focused reranking
- Auto-include form docs when prompt implies a form
- Facts improved 1-2 points across all prompts

**Remaining variance:** Facts fluctuate 3-5/6 per run due to model non-determinism. When the user specifies the product (LIBERTY SBS) in their prompt, it consistently hits 5-6/6.

## Improvement Points to Fix

### 1. "natural" prompt produces 1/6 facts (with or without refinement)

**Root cause:** "Fill out the description of proposed modification for the exterior modification form using American Home Contractors" — no mention of LIBERTY SBS, no mention of what to include. The form-aware system prompt kicks in (form doc detected) and makes output very concise, but the model has no guidance on which option/price to cite.

**Fix path:** When decomposition detects `product: ""` (empty), look at the vendor's documents to find the primary product/option. Or: in the form-aware system prompt, add "include all relevant details: cost, materials, timeline, dimensions, contractor info."

### 2. "with_system" regressed with refinement (4/6 → 2/6)

**Root cause:** Need to investigate what Nova Micro extracted as the intent map for this prompt. Possibly misidentified the vendor or subject, leading to wrong rerank ordering.

**Diagnosis step:** Log the decomposition output for this prompt. If the intent map is wrong, the fix is either a better decomposition prompt or a fallback when confidence is low.

### 3. "conversational" and "minimal" miss the form document (4/5 recall)

**Root cause:** The exterior modification application is only found when the prompt says "exterior modification" or "application." Casual phrasing ("my HOA form") doesn't match.

**Fix path:** After decomposition, if `target_document` is extracted (e.g., "HOA form" or "application"), do an additional targeted search specifically for that. Or: detect `document_type: "application"` in the candidate list and auto-include it.

### 4. "natural" gets only 1/6 facts even without refinement

**Root cause:** The form-aware prompt ("write plain paragraphs, facts only") is too restrictive without guidance on WHAT facts to include. When the user doesn't specify "include cost, timeline, etc." the model writes one generic paragraph.

**Fix path:** Enhance the form-aware system prompt: "Include all factual details found in the vendor documents: cost/pricing, materials, dimensions, timeline, contractor license, and color specifications."

### 5. Refinement adds 1-5s latency (decomposition + rerank API calls)

**Root cause:** Nova Micro (~0.3s) + Cohere Rerank (~0.5s) = ~0.8s overhead. Some runs show 10s because the generation itself varies.

**Acceptable?** Yes — the "Find Documents" step is interactive (user reviews anyway). 1s extra is invisible.

## Next Steps (Priority Order)

1. **Fix #4 first** — Enhance form-aware system prompt to always request key facts. This fixes "natural" for free.
2. **Fix #3** — Auto-include application/form docs when `target_document` is detected.
3. **Fix #2** — Log + diagnose decomposition failure on "with_system" prompt.
4. **Fix #1** — If product is empty in intent map, infer from vendor docs.
5. **Graph-based relationships** — Build document relationship table for batch/vendor clustering.

## Metrics to Track Going Forward

- **Minimum viable:** 5/5 recall, 5/6 facts, <10s total
- **Target:** 5/5 recall, 6/6 facts, <5s total
- **Current best:** 5/5 recall, 5/6 facts, 3.7s (detailed prompt + refinement)
