# Improvement Regime Results

Generated: 2026-05-23 15:54

Systematic prompt tuning: apply change → measure → keep or rollback.

## Summary

| # | Experiment | Avg | L1 | L2 | M4 | S3 | Status |
|---|-----------|-----|----|----|----|----|--------|
| 0 | Baseline | 5.4 | 0.0 | 6.5 | 6.7 | 8.5 | ✅ Kept |
| 1 | Exp 1: Add 'exhaustive' instruction to s | 8.2 | 9.8 | 6.5 | 6.7 | 10.0 | ✅ Kept |
| 2 | Exp 2: Strengthen extraction prompt to d | 8.1 | 9.6 | 6.1 | 7.3 | 9.5 | ❌ Rolled back |
| 3 | Exp 3: Add temporal awareness to extract | 8.1 | 9.8 | 6.5 | 6.7 | 9.5 | ❌ Rolled back |
| 4 | Exp 4: Increase schema generation detail | 8.4 | 9.6 | 6.5 | 7.3 | 10.0 | ✅ Kept |
| 5 | Exp 5: Lower complexity threshold from 3 | 7.5 | 10.0 | 5.5 | 6.7 | 8.0 | ❌ Rolled back |

**Starting score:** 5.4/10
**Final score:** 8.4/10
**Improvement:** +2.9

## Experiment Details

### Exp 1: Add 'exhaustive' instruction to system prompt
Tell the model to include EVERY entity and price found, not just the most relevant ones

**File:** `main.py`

**Change:**
```
- "Output well-structured Markdown."
+ "Output well-structured Markdown. Include EVERY company, price, and entity found
```

### Exp 2: Strengthen extraction prompt to demand all prices
Make the schema extraction prompt explicitly ask for every dollar amount

**File:** `task_pipeline.py`

**Change:**
```
- - Use null for fields not found in this document
+ - Use null for fields not found in this document
- For price fields, extract EVE
```

### Exp 3: Add temporal awareness to extraction
Help models distinguish completed work (invoices) from proposals (estimates)

**File:** `task_pipeline.py`

**Change:**
```
- - Use exact values (prices, names, numbers) — never paraphrase numbers
+ - Use exact values (prices, names, numbers) — never paraphrase numbers
- For eac
```

### Exp 4: Increase schema generation detail
Ask for more granular schema with nested fields for options/pricing

**File:** `task_pipeline.py`

**Change:**
```
- - Include a "_metadata" key with: task_summary, key_problem, output_sections[]
+ - Include a "_metadata" key with: task_summary, key_problem, output_sections[]
-
```

### Exp 5: Lower complexity threshold from 30k to 15k
Route more tasks to structured pipeline earlier

**File:** `main.py`

**Change:**
```
- if complexity_signals and total_context_chars > 30000:
+ if complexity_signals and total_context_chars > 15000:
```

