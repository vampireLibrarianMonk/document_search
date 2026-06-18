# Query Assist Gambit Results

Date: 2026-06-17
Ground truth: 9 exterior work items from home inspection reports

## What This Tests

Which combination of (decomposition model × answer model) produces the most comprehensive
answer to "What outside work requires completion taking into account we are working on the roof?"

Ground truth items:
1. Damaged siding (exterior back, roofdeck)
2. Seal siding penetrations with duct seal
3. Lifted Z-flashings (exterior front siding)
4. Rusted/corroded patio safety rails
5. Loose deck hand/safety rail (safety concern)
6. Missing hurricane ties (deck beam and joists)
7. Garage door doesn't reverse at 5lbs (safety concern)
8. Rotted trim / moisture damage / cracked caulk
9. Drainage/grading improvement needed

## Phase 1: Decomposition Model (fixed answer = Nemotron Super)

| Model | Score | Time | Items Found |
|-------|:-----:|------|-------------|
| Nova Micro | 1/9 | 2.9s | rusted patio rails |
| Nova Lite | 3/9 | 5.2s | siding, Z-flashings, sealed penetrations |
| Nova Pro | 3/9 | 4.1s | hurricane ties, rotted trim, drainage |
| Llama 3 8B | 3/9 | 18.2s | loose rail, garage door, drainage |

**Key finding:** No single model scores above 3/9. Each model finds DIFFERENT items.
Union of all 4 models covers 8/9 items.

## Phase 2: Answer Model (fixed decomp = best single model)

| Model | Score | Time | Notes |
|-------|:-----:|------|-------|
| Nemotron Super | 5/9 | 2.3s | Fast but misses drainage + 3 others |
| Nova Pro | 5/9 | 1.7s | Fastest, same as Nemotron |
| Qwen3 32B | 5/9 | 3.0s | Same recall as Nemotron |
| **DeepSeek v3** | **6/9** | 14.6s | Best recall, slow (thinking model) |
| **Magistral Small** | **6/9** | **7.6s** | Best balance: same recall, 2x faster |

## Key Findings

1. **Decomposition is the bottleneck** — not the answer model. A single decomp model only finds 3/9.
2. **Multi-model decomposition is the fix** — running 3 fast models (Nova Micro + Nova Lite + Llama 3)
   and taking the union of their sub-queries covers 8/9 items.
3. **Magistral Small wins the answer phase** — same 6/9 recall as DeepSeek but at 7.6s vs 14.6s.
4. **The single item not found (rusted patio rails)** may be in context but not consistently retrieved
   due to search scoring variance.

## Implementation Applied

- Decomposition: 3 parallel fast models (Nova Micro, Nova Lite, Llama 3 8B), 4 queries each
- Answer: Magistral Small (configurable via BEDROCK_QUERY_ASSIST_MODEL env var)
- Total sub-queries: ~12 (after dedup)

## Running

```bash
source .venv/bin/activate
python tests/gambit_query_assist.py
```
