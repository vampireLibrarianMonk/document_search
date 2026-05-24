# Task Pipeline Tests

Modular test infrastructure for the task workflow.

## Structure

```
tests/task_pipeline/
├── README.md              ← You are here
├── CHANGELOG.md           ← All improvements made (15 iterations logged)
├── prompts/
│   └── test_series.md     ← Test definitions (13 prompts: S1-S5, M1-M5, L1-L3)
├── runners/
│   └── run_full_suite.py  ← Automated test runner (all models × all prompts)
└── results/
    ├── full_suite_2026-05-23.md           ← 15 models × 13 tests evaluation
    └── improvement_regime_2026-05-23.md   ← 5 experiments, 2 kept (+2.9 improvement)
```

## Quick Reference

**Run full suite:**
```bash
python3 tests/task_pipeline/runners/run_full_suite.py
```

**Results go to:** `tests/task_pipeline/results/` (dated filenames)

## Scoring (0-10)

| Metric | Weight | Description |
|--------|--------|-------------|
| Facts/Numbers | 25% | Exact prices, dates, license numbers present |
| Entities | 25% | All companies/vendors found |
| Sections | 20% | Requested structure followed |
| Quality | 15% | Domain-specific insights surfaced |
| No Hallucination | 15% | No fabricated data (penalty: caps at 5.0) |

## Current Best Models

| Strategy | Model | Score | Speed |
|----------|-------|-------|-------|
| Simple tasks | Nova Pro | 8.5-10/10 | ~20-80s |
| Complex tasks | Mistral Magistral | 9.8/10 | ~280s |
| Overall best | Mistral Large 3 | 8.6/10 avg | ~2400s |
| Fastest good | Llama 4 Maverick | 7.7/10 avg | ~330s |
