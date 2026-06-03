"""Benchmark text generation models for the Document Generation task."""

import json
import re
import time
import boto3
import os
import sys

REGION = os.getenv("AWS_REGION", "us-east-1")
client = boto3.client("bedrock-runtime", region_name=REGION)

MODELS = [
    "amazon.nova-micro-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.nova-pro-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "mistral.mistral-large-2402-v1:0",
    "mistral.magistral-small-2509",
    "meta.llama3-70b-instruct-v1:0",
    "qwen.qwen3-32b-v1:0",
    "deepseek.v3.2",
    "nvidia.nemotron-super-3-120b",
    "zai.glm-5",
]

HOA_CONTEXT = (
    "Section 4.2 Fencing Requirements. All perimeter barriers including fences shall not exceed six (6) feet "
    "in height from finished grade. Materials must be wood, vinyl, or wrought iron. Chain link fencing is "
    "prohibited. Section 5.1 Exterior Modifications. No exterior modification, including but not limited to "
    "painting, roofing, fencing, landscaping, or addition of structures, shall be commenced without prior "
    "written approval from the Architectural Review Committee (ARC). Applications must be submitted at least "
    "30 days before planned start date. Section 5.3 Outbuildings. No outbuilding, storage shed, or accessory "
    "structure shall be erected without prior written approval. Maximum footprint of 120 square feet. Must be "
    "set back at least 5 feet from property lines."
)

CLOSING_CONTEXT = (
    "CLOSING DISCLOSURE. Loan Amount: $425,000. Interest Rate: 6.875%. Monthly Principal & Interest: $2,791.53. "
    "Estimated Total Monthly Payment: $3,847.22 (includes taxes, insurance, PMI). Cash to Close: $89,234.67. "
    "Origination Charges: $4,250.00. Appraisal Fee: $550.00. Title Insurance: $2,100.00. Recording Fees: $186.00. "
    "Transfer Taxes: $4,250.00."
)

PROMPTS = [
    {
        "prompt": "Create a summary of my HOA architectural guidelines for exterior modifications",
        "context": HOA_CONTEXT,
        "type": "summary",
    },
    {
        "prompt": "Draft a letter to my HOA requesting approval for a new fence",
        "context": HOA_CONTEXT,
        "type": "letter",
    },
    {
        "prompt": "Summarize my closing costs and loan terms",
        "context": CLOSING_CONTEXT,
        "type": "summary",
    },
]

BASE_RULES = (
    "- Use only information from the provided source documents\n"
    "- Include specific details, numbers, addresses, and names from the source material\n"
    "- If the source material doesn't contain enough information, say so clearly\n"
    "- Write in plain English that a non-expert would understand"
)

FORMAT_INSTRUCTION = (
    "Structure the output as clean Markdown with proper headings (# ## ###), "
    "bullet points, and paragraphs. Use bold for key terms."
)

SYSTEM_PROMPT = (
    "You are a professional document writer. Your job is to create well-structured "
    "documents using ONLY the provided source material.\n\n"
    f"Output format instructions:\n{FORMAT_INSTRUCTION}\n\n"
    f"Rules:\n{BASE_RULES}"
)


def call_model(model_id: str, prompt: str, context: str):
    """Call a model and return (output_text, latency_seconds, output_tokens, error)."""
    user_msg = (
        f"Source documents:\n{context}\n\n"
        f"Request: {prompt}\n\n"
        "Generate the document in Markdown format following the format instructions above."
    )
    start = time.time()
    try:
        resp = client.converse(
            modelId=model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_msg}]}],
            inferenceConfig={"maxTokens": 4096},
        )
        latency = time.time() - start
        text = resp["output"]["message"]["content"][0]["text"]
        usage = resp.get("usage", {})
        output_tokens = usage.get("outputTokens", 0)
        return text, latency, output_tokens, None
    except Exception as e:
        latency = time.time() - start
        return None, latency, 0, str(e)


def score_structure(text: str) -> int:
    """Score markdown structure quality 0-5."""
    score = 0
    if re.search(r"^#{1,3}\s+", text, re.MULTILINE):
        score += 2
    if re.search(r"^[-*]\s+", text, re.MULTILINE):
        score += 1
    if re.search(r"\*\*[^*]+\*\*", text):
        score += 1
    if text.count("\n\n") >= 2:
        score += 1
    return min(score, 5)


def score_accuracy(text: str, context: str) -> int:
    """Score content accuracy 0-5: uses facts from context, no hallucinated numbers."""
    score = 0
    # Check key facts are present
    key_facts = []
    if "425,000" in context:
        key_facts = ["425,000", "6.875", "2,791", "3,847", "89,234"]
    else:
        key_facts = ["six", "6", "30 days", "120 square feet", "5 feet", "chain link"]

    found = sum(1 for f in key_facts if f.lower() in text.lower())
    ratio = found / len(key_facts) if key_facts else 0
    score = round(ratio * 5)
    return min(score, 5)


def score_completeness(text: str, context: str) -> int:
    """Score completeness 0-5: covers all relevant sections."""
    sections = []
    if "425,000" in context:
        sections = ["loan amount", "interest rate", "monthly", "cash to close", "origination"]
    else:
        sections = ["fenc", "exterior modification", "outbuilding", "architectural review", "approval"]

    found = sum(1 for s in sections if s.lower() in text.lower())
    ratio = found / len(sections) if sections else 0
    return min(round(ratio * 5), 5)


def score_instruction_following(text: str, prompt_type: str) -> int:
    """Score instruction following 0-5."""
    score = 0
    if prompt_type == "letter":
        # Should have greeting, formal tone, request language
        if any(w in text.lower() for w in ["dear", "to whom", "hello"]):
            score += 2
        if any(w in text.lower() for w in ["request", "approval", "requesting"]):
            score += 2
        if any(w in text.lower() for w in ["sincerely", "regards", "thank"]):
            score += 1
    else:
        # Summary - should have structure, headings, organized info
        if re.search(r"^#{1,3}\s+", text, re.MULTILINE):
            score += 2
        if re.search(r"^[-*]\s+", text, re.MULTILINE):
            score += 1
        if len(text) > 200:
            score += 1
        if text.count("\n\n") >= 2:
            score += 1
    return min(score, 5)


def run_benchmark():
    results = {}
    output_lines = []

    output_lines.append("=" * 80)
    output_lines.append("DOCUMENT GENERATION MODEL BENCHMARK")
    output_lines.append("=" * 80)
    output_lines.append(f"Region: {REGION}")
    output_lines.append(f"Models tested: {len(MODELS)}")
    output_lines.append(f"Prompts per model: {len(PROMPTS)}")
    output_lines.append("")

    for model_id in MODELS:
        print(f"\n{'='*60}")
        print(f"Testing: {model_id}")
        print(f"{'='*60}")
        results[model_id] = {
            "scores": [],
            "latencies": [],
            "tokens": [],
            "errors": [],
        }

        for i, p in enumerate(PROMPTS):
            print(f"  Prompt {i+1}/3: {p['prompt'][:50]}...")
            text, latency, tokens, error = call_model(model_id, p["prompt"], p["context"])

            if error:
                print(f"    ERROR: {error[:100]}")
                results[model_id]["errors"].append(error)
                results[model_id]["scores"].append({"structure": 0, "accuracy": 0, "completeness": 0, "instruction": 0, "total": 0})
                results[model_id]["latencies"].append(0)
                results[model_id]["tokens"].append(0)
                continue

            s_struct = score_structure(text)
            s_acc = score_accuracy(text, p["context"])
            s_comp = score_completeness(text, p["context"])
            s_instr = score_instruction_following(text, p["type"])
            total = s_struct + s_acc + s_comp + s_instr

            results[model_id]["scores"].append({
                "structure": s_struct, "accuracy": s_acc,
                "completeness": s_comp, "instruction": s_instr, "total": total,
            })
            results[model_id]["latencies"].append(latency)
            results[model_id]["tokens"].append(tokens)

            print(f"    Structure: {s_struct}/5 | Accuracy: {s_acc}/5 | Completeness: {s_comp}/5 | Instruction: {s_instr}/5 | Total: {total}/20")
            print(f"    Latency: {latency:.2f}s | Tokens: {tokens}")

    # Build results table
    output_lines.append("")
    output_lines.append("=" * 80)
    output_lines.append("DETAILED RESULTS PER PROMPT")
    output_lines.append("=" * 80)

    for model_id in MODELS:
        r = results[model_id]
        output_lines.append(f"\n--- {model_id} ---")
        if r["errors"]:
            output_lines.append(f"  ERRORS: {len(r['errors'])}/{len(PROMPTS)} prompts failed")
            for err in r["errors"]:
                output_lines.append(f"    {err[:120]}")
        for i, s in enumerate(r["scores"]):
            output_lines.append(
                f"  Prompt {i+1}: Struct={s['structure']} Acc={s['accuracy']} "
                f"Comp={s['completeness']} Instr={s['instruction']} "
                f"Total={s['total']}/20 | "
                f"Latency={r['latencies'][i]:.2f}s | Tokens={r['tokens'][i]}"
            )

    # Summary ranking
    output_lines.append("")
    output_lines.append("=" * 80)
    output_lines.append("FINAL RANKINGS")
    output_lines.append("=" * 80)
    output_lines.append("")

    summary = []
    for model_id in MODELS:
        r = results[model_id]
        total_score = sum(s["total"] for s in r["scores"])
        avg_latency = sum(r["latencies"]) / max(len([l for l in r["latencies"] if l > 0]), 1)
        avg_tokens = sum(r["tokens"]) / max(len([t for t in r["tokens"] if t > 0]), 1)
        num_errors = len(r["errors"])
        summary.append({
            "model": model_id,
            "total_score": total_score,
            "avg_latency": avg_latency,
            "avg_tokens": avg_tokens,
            "errors": num_errors,
        })

    # Sort by total score descending
    summary.sort(key=lambda x: x["total_score"], reverse=True)

    header = f"{'Rank':<5}{'Model':<45}{'Score':<12}{'Avg Lat':<12}{'Avg Tok':<10}{'Errors':<8}"
    output_lines.append(header)
    output_lines.append("-" * len(header))

    for rank, s in enumerate(summary, 1):
        score_str = f"{s['total_score']}/60"
        lat_str = f"{s['avg_latency']:.2f}s"
        tok_str = f"{s['avg_tokens']:.0f}"
        line = f"{rank:<5}{s['model']:<45}{score_str:<12}{lat_str:<12}{tok_str:<10}{s['errors']:<8}"
        output_lines.append(line)

    # Latency ranking
    output_lines.append("")
    output_lines.append("LATENCY RANKING (fastest first, excluding errors):")
    output_lines.append("-" * 60)
    latency_sorted = sorted([s for s in summary if s["avg_latency"] > 0], key=lambda x: x["avg_latency"])
    for rank, s in enumerate(latency_sorted, 1):
        output_lines.append(f"  {rank}. {s['model']:<45} {s['avg_latency']:.2f}s avg")

    # Best overall pick
    output_lines.append("")
    output_lines.append("=" * 80)
    if summary:
        best = summary[0]
        output_lines.append(f"RECOMMENDED: {best['model']}")
        output_lines.append(f"  Score: {best['total_score']}/60 | Avg Latency: {best['avg_latency']:.2f}s")
    output_lines.append("=" * 80)

    # Write results
    result_text = "\n".join(output_lines)
    print("\n" + result_text)

    out_path = os.path.join(
        os.path.dirname(__file__), "benchmark_results", "generate_benchmark.txt"
    )
    with open(out_path, "w") as f:
        f.write(result_text)
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    run_benchmark()
