# Form Fill Gambit Results

Date: 2026-06-07 23:04
Combinations tested: 120
Successful: 108/120

## What This Test Does (Plain English)

We asked 10 different AI models to fill out the "Description of Proposed Modification" section of the HOA exterior modification application — the same task we did manually for the American Home Contractors roof replacement. We varied three things:

1. **Which AI model writes it** (10 models from Amazon, NVIDIA, Mistral, Meta, etc.)
2. **Which documents we gave it** (just the contractor docs? add the HOA rules? throw everything at it?)
3. **How much we told it what to do** (vague ask vs. detailed instructions)

Then a judge AI scored each result on: Did it get the facts right? Did it make stuff up? Did it write normal paragraphs? Did it cover everything needed?

## What We Learned

1. **Clear instructions matter most.** Telling the AI exactly what to include (price, dimensions, color, timeline) produced far better results than vague prompts — regardless of which model we used.

2. **More documents doesn't hurt (much).** Even when we threw 9 unrelated roof docs at the AI, with clear instructions it still focused on the right info. But vague prompts + lots of docs = hallucinations (the AI started mentioning gutter colors and siding that have nothing to do with the roof project).

3. **NVIDIA Nemotron Super is the best fit.** It scored perfectly, got all 6 required facts right, and did it in under 3 seconds. That's why it's now the default model for the Tasks tab.

4. **DeepSeek is the smartest but slowest.** It figured out what we wanted from a one-line prompt — but took 33 seconds because it "thinks" before answering. Not worth the wait when clear instructions get the same result in 3 seconds.

5. **The medium prompt was worse than the minimal one.** Partially telling the AI what to do confused it more than saying nothing. Either be specific or let the model figure it out entirely.

## The Winner

**NVIDIA Nemotron Super** with the contractor's documents selected and a clear prompt.
- Perfect accuracy, all facts correct, 2.7 seconds, flowing paragraphs, no hallucinations.

## What We Did With These Results

Based on this gambit:
1. Set Nemotron Super as the default task model (was Nova Pro)
2. Implemented chunk-level retrieval — instead of loading 136K chars of full documents, the pipeline now uses embeddings to find only the ~27K chars of relevant chunks. Generation went from 196-273s to 3-8s.
3. Added form-aware system prompt — when an application/form document is in the selection, the model automatically writes plain paragraphs instead of markdown. No user prompting needed.
4. Validated with the Retrieval E2E Gambit (see `test/results/retrieval_e2e_gambit/`): 34-46x speed improvement, 5/6 facts with detailed prompt.

## Ground Truth
Source: tmp/ahc_hoa_submission/description_of_proposed_modification.txt
Required facts: price_7200, area_750, color_black, timeline_1_day, license_va, liberty_sbs

## Top 10 Combinations (by total score /100)

| Rank | Model | Doc Set | Prompt | Score | Facts | Time |
|------|-------|---------|--------|-------|-------|------|
| 1 | mistral | kitchen_sink | detailed | 100/100 | 6/6 | 7.8s |
| 2 | v3 | with_arb_standards | minimal | 100/100 | 3/6 | 32.7s |
| 3 | nemotron | focused_no_form | detailed | 100/100 | 6/6 | 2.7s |
| 4 | nemotron | with_arb_standards | detailed | 100/100 | 6/6 | 3.0s |
| 5 | nova | kitchen_sink | detailed | 98/100 | 6/6 | 2.3s |
| 6 | qwen3 | focused_no_form | detailed | 98/100 | 6/6 | 3.7s |
| 7 | v3 | focused_no_form | detailed | 98/100 | 6/6 | 6.1s |
| 8 | magistral | kitchen_sink | detailed | 97/100 | 4/6 | 4.9s |
| 9 | nova | focused_5 | detailed | 95/100 | 6/6 | 2.2s |
| 10 | nova | focused_no_form | detailed | 95/100 | 6/6 | 2.1s |

## Best Model (averaged across all doc sets and prompts)

| Model | Avg Score | Runs |
|-------|-----------|------|
| nemotron | 89.3/100 | 12 |
| v3 | 83.8/100 | 12 |
| nova | 82.2/100 | 12 |
| qwen3 | 79.2/100 | 12 |
| nova | 77.2/100 | 12 |
| magistral | 76.6/100 | 12 |
| mistral | 76.5/100 | 12 |
| claude | 73.8/100 | 12 |
| claude | 65.5/100 | 12 |

## Best Document Set (averaged across all models and prompts)

| Doc Set | Avg Score | Description |
|---------|-----------|-------------|
| focused_5 | 79.1/100 | Only AHC docs + form (5 docs, no noise) |
| with_arb_standards | 78.9/100 | AHC docs + form + ARB Standards (6 docs — tests noise resistance) |
| kitchen_sink | 78.5/100 | All roof-related docs (tests signal extraction from noise) |
| focused_no_form | 76.6/100 | AHC docs only, no form (4 docs — tests if model still formats correctly) |

## Best Prompt Level (averaged across all models and doc sets)

| Prompt | Avg Score | Text |
|--------|-----------|------|
| detailed | 88.7/100 | Look at the exterior modification application form directions section. Using onl... |
| minimal | 74.9/100 | Fill out the description of proposed modification for the exterior modification ... |
| medium | 71.2/100 | Write the description of proposed modification section for the HOA exterior modi... |

## Recommendations

- **Best overall**: mistral.mistral-large-2402-v1:0 + kitchen_sink + detailed (100/100)
- **Fastest**: amazon.nova-lite-v1:0 (1.7s, 70/100)
- **Best with minimal prompt**: deepseek.v3.2 + with_arb_standards (100/100)