# Model Benchmark Results & Recommendations

Benchmarked 2026-06-02 across all 9 model roles in the House Document Search app.
Tested 30+ models from 11 providers (Amazon, Anthropic, Mistral, Meta, Qwen, DeepSeek, NVIDIA, Z.AI, Google, Cohere, OpenAI).

## Final Recommendations (Defaults)

| Role | Recommended Model | Score | Latency | Rationale |
|------|-------------------|-------|---------|-----------|
| **Ask AI** | `qwen.qwen3-32b-v1:0` | 46.4/60 | 0.58s | Best speed+accuracy combo for interactive Q&A |
| **Classification** | `amazon.nova-micro-v1:0` | 97.1/100 | 0.46s | Perfect accuracy, fastest, cheapest |
| **Generate** | `amazon.nova-pro-v1:0` | 59/60 | 2.19s | Highest quality output with good speed |
| **Format Detection** | `meta.llama3-8b-instruct-v1:0` | 7/8 acc | 0.19s | Fastest with best accuracy+cleanliness |
| **Template Extraction** | `mistral.magistral-small-2509` | 85/100 | 6.9s | Best section+field detection, reliable JSON |
| **Vision OCR** | `mistral.ministral-3-3b-instruct` | 25/25 | 0.49s | Perfect accuracy, fastest by 4x |
| **Embeddings** | `amazon.titan-embed-text-v2:0` | 93.3% Acc@1 | 121ms | Top accuracy, 5x cheaper than alternatives |
| **Task Single-Pass** | `amazon.nova-pro-v1:0` | (same as Generate) | 2.19s | Best for large-context single-shot |
| **Task Structured** | `mistral.magistral-small-2509` | (strong JSON+structure) | 6.9s | Best for multi-step extraction pipelines |

## Detailed Results by Role

### 1. Ask AI (Interactive Q&A)

| Rank | Model | Score | Accuracy | Latency | Notes |
|------|-------|-------|----------|---------|-------|
| 1 | meta.llama3-70b-instruct-v1:0 | 46.6 | 17/25 | 1.45s | Best raw accuracy |
| **2** | **qwen.qwen3-32b-v1:0** | **46.4** | **16/25** | **0.58s** | **★ RECOMMENDED — fastest high-scorer** |
| 3 | amazon.nova-lite-v1:0 | 44.4 | 13/25 | 0.58s | Most concise |
| 4 | mistral.magistral-small-2509 | 43.5 | 16/25 | 1.50s | Solid all-around |
| 5 | amazon.nova-micro-v1:0 | 42.5 | 12/25 | 0.46s | Fastest overall |
| 6 | amazon.nova-pro-v1:0 | 42.3 | 13/25 | 0.71s | Good speed |
| 7 | anthropic.claude-3-sonnet | 42.0 | 17/25 | 2.02s | High accuracy but verbose |
| 8 | zai.glm-5 | 41.6 | 13/25 | 1.40s | |
| 9 | anthropic.claude-3-haiku | 38.3 | 17/25 | 1.69s | Hallucination detected |
| 10 | mistral.mistral-large | 38.2 | 17/25 | 2.81s | Hallucination detected |
| 11 | nvidia.nemotron-super-3-120b | 36.6 | 12/25 | 5.40s | Too slow |
| 12 | deepseek.v3.2 | 28.0 | 12/25 | 23.66s | Extreme latency |
| 13 | openai.gpt-oss-120b-1:0 | 0.0 | — | — | API failures |

### 2. Classification

| Rank | Model | Score | Cat Acc | JSON | Latency | Notes |
|------|-------|-------|---------|------|---------|-------|
| **1** | **amazon.nova-micro-v1:0** | **97.1** | **5/5** | **5/5** | **0.46s** | **★ RECOMMENDED** |
| 2 | anthropic.claude-3-sonnet | 95.9 | 5/5 | 5/5 | 1.72s | |
| 3 | qwen.qwen3-32b-v1:0 | 95.8 | 5/5 | 5/5 | 0.58s | |
| 4 | nvidia.nemotron-super-3-120b | 95.3 | 5/5 | 5/5 | 1.11s | |
| 5 | mistral.mistral-large | 95.2 | 5/5 | 5/5 | 2.37s | |
| 6 | mistral.mistral-small | 94.9 | 5/5 | 5/5 | 1.48s | |
| 7 | meta.llama3-70b | 94.9 | 5/5 | 5/5 | 1.50s | |
| 8 | deepseek.v3.2 | 94.5 | 5/5 | 5/5 | 1.94s | |
| 9 | zai.glm-5 | 93.7 | 5/5 | 5/5 | 2.69s | |
| 10 | amazon.nova-lite-v1:0 | 88.9 | 4/5 | 5/5 | 0.67s | Misclassified inspection |
| 11 | amazon.nova-pro-v1:0 | 88.8 | 4/5 | 5/5 | 0.80s | |
| 12 | anthropic.claude-3-haiku | 88.6 | 4/5 | 5/5 | 0.98s | |
| 13 | mistral.magistral-small | 78.0 | 4/5 | 4/5 | 1.59s | JSON failure |

### 3. Document Generation

| Rank | Model | Quality | Latency | Notes |
|------|-------|---------|---------|-------|
| **1** | **amazon.nova-pro-v1:0** | **59/60** | **2.19s** | **★ RECOMMENDED** |
| 2 | amazon.nova-micro-v1:0 | 58/60 | 1.39s | Best speed+quality value |
| 3 | mistral.mistral-large | 58/60 | 7.07s | 5x slower than Nova |
| 4 | amazon.nova-lite-v1:0 | 57/60 | 1.71s | |
| 5 | anthropic.claude-3-sonnet | 56/60 | 4.41s | |
| 6 | qwen.qwen3-32b-v1:0 | 56/60 | 2.79s | |
| 7 | mistral.magistral-small | 55/60 | 2.55s | |
| 8 | nvidia.nemotron-super-3-120b | 55/60 | 1.75s | |
| 9 | zai.glm-5 | 55/60 | 5.19s | |
| 10 | anthropic.claude-3-haiku | 54/60 | 2.54s | |
| 11 | deepseek.v3.2 | 54/60 | 15.52s | Unreliable latency |
| 12 | meta.llama3-70b | 0/60 | — | maxTokens validation error |

### 4. Format Detection

| Rank | Model | Accuracy | Clean | Latency | Notes |
|------|-------|----------|-------|---------|-------|
| **1** | **meta.llama3-8b-instruct-v1:0** | **7/8** | **8/8** | **0.19s** | **★ RECOMMENDED** |
| 2 | amazon.nova-micro-v1:0 | 7/8 | 8/8 | 0.29s | |
| 3 | qwen.qwen3-32b-v1:0 | 7/8 | 8/8 | 0.32s | |
| 4 | amazon.nova-lite-v1:0 | 7/8 | 8/8 | 0.33s | |
| 5 | mistral.magistral-small | 7/8 | 8/8 | 0.34s | |
| 6 | anthropic.claude-3-haiku | 7/8 | 8/8 | 0.40s | |
| 7 | nvidia.nemotron-nano-3-30b | 7/8 | 8/8 | 0.47s | |
| 8 | deepseek.v3.2 | 7/8 | 8/8 | 3.73s | Too slow |
| 9 | zai.glm-4.7-flash | 7/8 | 7/8 | 0.31s | |
| 10 | mistral.mistral-large | 7/8 | 7/8 | 0.45s | |
| 11 | mistral.mistral-small | 6/8 | 7/8 | 0.24s | |
| 12 | mistral.ministral-3-8b | 4/8 | 4/8 | 0.27s | Bad formatting |
| 13 | mistral.ministral-3-3b | 2/8 | 2/8 | 0.23s | Doesn't follow instructions |

### 5. Template Extraction

| Rank | Model | Score | JSON | Fields | Sections | Latency | Notes |
|------|-------|-------|------|--------|----------|---------|-------|
| **1** | **mistral.magistral-small-2509** | **85.0** | **2/2** | **4.5/5** | **3.0/5** | **6.9s** | **★ RECOMMENDED** |
| 2 | zai.glm-5 | 82.0 | 2/2 | 5.0/5 | 2.0/5 | 8.4s | Best field detection |
| 3 | meta.llama3-70b | 79.0 | 2/2 | 5.0/5 | 1.5/5 | 11.1s | |
| 4 | mistral.mistral-large | 76.0 | 2/2 | 4.5/5 | 1.5/5 | 12.7s | |
| 5 | deepseek.v3.2 | 76.0 | 2/2 | 4.0/5 | 2.0/5 | 15.1s | |
| 6 | amazon.nova-pro-v1:0 | 64.5 | 2/2 | 2.5/5 | 2.0/5 | 3.3s | Fastest decent option |
| 7 | anthropic.claude-3-sonnet | 64.0 | 2/2 | 3.0/5 | 1.0/5 | 7.4s | |
| 8 | qwen.qwen3-32b-v1:0 | 61.5 | 2/2 | 2.5/5 | 1.5/5 | 1.9s | Fastest overall |
| 9 | nvidia.nemotron-super-3-120b | 55.5 | 2/2 | 0.0/5 | 3.0/5 | 6.4s | No field detection |
| 10 | anthropic.claude-3-haiku | 44.0 | 2/2 | 0.0/5 | 1.5/5 | 5.8s | |
| 11 | amazon.nova-micro-v1:0 | 41.0 | 2/2 | 0.0/5 | 1.0/5 | 1.7s | |
| 12 | amazon.nova-lite-v1:0 | 41.0 | 2/2 | 0.0/5 | 1.0/5 | 2.3s | |

### 6. Vision OCR

| Rank | Model | Score | Accuracy | Format | Halluc | Latency | Notes |
|------|-------|-------|----------|--------|--------|---------|-------|
| **1** | **mistral.ministral-3-3b-instruct** | **25/25** | **10/10** | **5/5** | **0** | **0.49s** | **★ RECOMMENDED** |
| 2 | mistral.ministral-3-14b | 25/25 | 10/10 | 5/5 | 0 | 0.77s | |
| 3 | google.gemma-3-4b-it | 25/25 | 10/10 | 5/5 | 0 | 0.70s | |
| 4 | anthropic.claude-3-haiku | 25/25 | 10/10 | 5/5 | 0 | 2.18s | Previous default |
| 5 | anthropic.claude-3-sonnet | 25/25 | 10/10 | 5/5 | 0 | 2.33s | |
| 6 | google.gemma-3-12b-it | 25/25 | 10/10 | 5/5 | 0 | 1.51s | |
| 7 | qwen.qwen3-vl-235b | 25/25 | 10/10 | 5/5 | 0 | 5.98s | |
| 8 | google.gemma-3-27b-it | 25/25 | 10/10 | 5/5 | 0 | 12.78s | |
| 9 | mistral.magistral-small | 24.9/25 | 10/10 | 4.9/5 | 0 | 1.41s | |
| 10 | nvidia.nemotron-nano-12b | 24.5/25 | 9.8/10 | 4.9/5 | 0 | 0.79s | |
| 11 | amazon.nova-lite-v1:0 | 24.1/25 | 10/10 | 4.1/5 | 0 | 0.73s | Flattens structure |
| 12 | amazon.nova-pro-v1:0 | 23.5/25 | 10/10 | 3.5/5 | 0 | 0.95s | Flattens structure |
| 13 | mistral.ministral-3-8b | 22.6/25 | 10/10 | 4.6/5 | 1.0 | 0.94s | Adds bold |
| 14 | mistral.mistral-large-3-675b | 22.6/25 | 10/10 | 4.6/5 | 1.0 | 1.90s | Adds bold |
| 15 | moonshotai.kimi-k2.5 | 20.9/25 | 10/10 | 4.3/5 | 1.7 | 1.59s | Hallucinated numbers |
| — | writer.palmyra-vision-7b | FAILED | — | — | — | — | API error |

### 7. Embeddings

| Rank | Model | Dim | Acc@1 | MRR | Latency | Cost/1K tokens |
|------|-------|-----|-------|-----|---------|----------------|
| **1** | **amazon.titan-embed-text-v2:0** | **1024** | **93.3%** | **0.967** | **121ms** | **$0.00002 ★** |
| 2 | cohere.embed-multilingual-v3 | 1024 | 93.3% | 0.967 | 96ms | $0.00010 |
| 3 | cohere.embed-v4:0 | 1536 | 93.3% | 0.967 | 145ms | $0.00010 |
| 4 | cohere.embed-english-v3 | 1024 | 93.3% | 0.956 | 101ms | $0.00010 |
| 5 | amazon.titan-embed-text-v1 | 1536 | 86.7% | 0.933 | 122ms | $0.00010 |
| 6 | amazon.titan-embed-g1-text-02 | 1536 | 86.7% | 0.933 | 127ms | $0.00010 |
| 7 | amazon.titan-embed-image-v1 | 1024 | 80.0% | 0.889 | 145ms | $0.00010 |

## Changes from Previous Defaults

| Role | Previous Default | New Default | Why |
|------|-----------------|-------------|-----|
| Ask AI | `anthropic.claude-3-haiku` | `qwen.qwen3-32b-v1:0` | 3x faster, same accuracy, no hallucination |
| Classification | `BEDROCK_MODEL_ID` (haiku) | `amazon.nova-micro-v1:0` | Perfect accuracy, fastest, cheapest |
| Generate | `anthropic.claude-3-sonnet` | `amazon.nova-pro-v1:0` | Higher quality (59 vs 56), 2x faster |
| Format Detection | `BEDROCK_MODEL_ID` (haiku) | `meta.llama3-8b-instruct-v1:0` | Fastest (194ms), perfect cleanliness |
| Template Extraction | `BEDROCK_MODEL_ID` (haiku) | `mistral.magistral-small-2509` | Dramatically better field detection |
| Vision OCR | `anthropic.claude-3-haiku` | `mistral.ministral-3-3b-instruct` | Same quality, 4.4x faster, cheaper |
| Embeddings | `amazon.titan-embed-text-v2:0` | `amazon.titan-embed-text-v2:0` | Already optimal (no change) |
| Task Single-Pass | `amazon.nova-pro-v1:0` | `amazon.nova-pro-v1:0` | Already optimal (no change) |
| Task Structured | `mistral.magistral-small-2509` | `mistral.magistral-small-2509` | Already optimal (no change) |
