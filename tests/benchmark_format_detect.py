"""Benchmark: Format Detection models - tests which model best returns a single format word."""

import time
import boto3
import sys

REGION = "us-east-1"
SYSTEM_PROMPT = (
    "You detect the best output format for a document request. "
    "Reply with EXACTLY this format: FORMAT|REASON\n"
    "FORMAT must be one of: md, docx, pdf, png, pptx, txt\n"
    "REASON is 2-4 words explaining why.\n\n"
    "Examples:\n"
    "- 'Write a letter to my HOA' → docx|formal letter\n"
    "- 'Create a presentation about rules' → pptx|slide deck\n"
    "- 'Fill out the modification form' → docx|fillable form\n"
    "- 'Make a quick reference card' → png|visual reference\n"
    "- 'Generate a report with all fees' → pdf|formal report\n"
    "- 'Summarize the bylaws' → md|text summary\n"
    "- 'Write an email to my roofer' → txt|email message\n"
    "- 'Send an email asking about repairs' → txt|email message\n"
    "- 'Draft an email to the contractor' → txt|email message"
)

MODELS = [
    "amazon.nova-micro-v1:0",
    "amazon.nova-lite-v1:0",
    "mistral.mistral-small-2402-v1:0",
    "mistral.mistral-large-2402-v1:0",
    "mistral.magistral-small-2509",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "meta.llama3-8b-instruct-v1:0",
    "qwen.qwen3-32b-v1:0",
    "zai.glm-4.7-flash",
    "nvidia.nemotron-nano-3-30b",
    "deepseek.v3.2",
    "mistral.ministral-3-3b-instruct",
    "mistral.ministral-3-8b-instruct",
]

TEST_CASES = [
    ("Create a PowerPoint presentation about my HOA rules", "pptx"),
    ("Write a PDF report summarizing my inspection findings", "pdf"),
    ("Draft an email to my HOA about the fence", "txt"),
    ("Generate a Word document with the closing summary", "docx"),
    ("Make a reference card image of important dates", "png"),
    ("Create a markdown summary of my insurance coverage", "md"),
    ("Fill out the exterior modification application", "docx"),
    ("Write up the roof inspection findings", "md"),
]


def call_model(client, model_id, prompt):
    """Call a model and return (raw_response, latency_ms)."""
    start = time.time()
    try:
        resp = client.converse(
            modelId=model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 20},
        )
        latency = (time.time() - start) * 1000
        raw = resp["output"]["message"]["content"][0]["text"].strip()
        return raw, latency, None
    except Exception as e:
        latency = (time.time() - start) * 1000
        return None, latency, str(e)


def parse_format(raw):
    """Extract format from FORMAT|REASON response."""
    if not raw:
        return None
    parts = raw.split("|", 1)
    fmt = parts[0].strip().lower()
    if fmt in ("md", "docx", "pdf", "png", "pptx", "txt"):
        return fmt
    return None


def is_clean(raw):
    """Check if response is just FORMAT|REASON with no extra text."""
    if not raw:
        return False
    parts = raw.split("|")
    if len(parts) != 2:
        return False
    fmt = parts[0].strip().lower()
    reason = parts[1].strip()
    return fmt in ("md", "docx", "pdf", "png", "pptx", "txt") and len(reason.split()) <= 6


def run_benchmark():
    client = boto3.client("bedrock-runtime", region_name=REGION)
    results = []

    for model_id in MODELS:
        print(f"\n{'='*60}")
        print(f"Testing: {model_id}")
        print(f"{'='*60}")

        correct = 0
        clean = 0
        total_latency = 0
        details = []
        error = None

        for prompt, expected in TEST_CASES:
            raw, latency, err = call_model(client, model_id, prompt)
            if err:
                error = err
                details.append((prompt, expected, None, raw, latency, False, False, err))
                break

            detected = parse_format(raw)
            is_correct = detected == expected
            is_cl = is_clean(raw)

            if is_correct:
                correct += 1
            if is_cl:
                clean += 1
            total_latency += latency

            status = "✓" if is_correct else "✗"
            print(f"  {status} [{latency:6.0f}ms] {expected:5s} → {raw!r}")
            details.append((prompt, expected, detected, raw, latency, is_correct, is_cl, None))

        if error:
            print(f"  ⚠ ERROR: {error}")
            results.append({
                "model": model_id,
                "accuracy": 0,
                "cleanliness": 0,
                "avg_latency": 0,
                "error": error,
                "details": details,
            })
        else:
            avg_lat = total_latency / len(TEST_CASES)
            print(f"\n  Score: {correct}/8 correct, {clean}/8 clean, avg {avg_lat:.0f}ms")
            results.append({
                "model": model_id,
                "accuracy": correct,
                "cleanliness": clean,
                "avg_latency": avg_lat,
                "error": None,
                "details": details,
            })

    # Sort by accuracy desc, then cleanliness desc, then latency asc
    results.sort(key=lambda r: (-r["accuracy"], -r["cleanliness"], r["avg_latency"]))
    return results


def format_results(results):
    lines = []
    lines.append("=" * 90)
    lines.append("FORMAT DETECTION BENCHMARK RESULTS")
    lines.append("=" * 90)
    lines.append(f"{'Rank':<5}{'Model':<45}{'Accuracy':<10}{'Clean':<8}{'Avg ms':<10}{'Notes'}")
    lines.append("-" * 90)

    for i, r in enumerate(results, 1):
        if r["error"]:
            notes = f"ERROR: {r['error'][:40]}"
        else:
            notes = ""
        lines.append(
            f"{i:<5}{r['model']:<45}{r['accuracy']}/8{'':<5}{r['cleanliness']}/8{'':<4}{r['avg_latency']:>7.0f}ms   {notes}"
        )

    lines.append("-" * 90)
    lines.append("")

    # Detail section
    lines.append("\nDETAILED RESPONSES")
    lines.append("=" * 90)
    for r in results:
        if r["error"]:
            lines.append(f"\n{r['model']}: SKIPPED ({r['error'][:60]})")
            continue
        lines.append(f"\n{r['model']} — {r['accuracy']}/8 correct, {r['cleanliness']}/8 clean, {r['avg_latency']:.0f}ms avg")
        lines.append("-" * 70)
        for prompt, expected, detected, raw, latency, is_correct, is_cl, _ in r["details"]:
            mark = "✓" if is_correct else "✗"
            cl_mark = "C" if is_cl else " "
            lines.append(f"  {mark}{cl_mark} [{latency:5.0f}ms] expect={expected:5s} got={raw!r}")
            lines.append(f"       prompt: {prompt[:60]}")

    lines.append("\n" + "=" * 90)
    lines.append("RECOMMENDATION")
    lines.append("=" * 90)
    best = next((r for r in results if not r["error"]), None)
    if best:
        lines.append(f"Best model: {best['model']}")
        lines.append(f"  Accuracy: {best['accuracy']}/8, Cleanliness: {best['cleanliness']}/8, Avg latency: {best['avg_latency']:.0f}ms")
    return "\n".join(lines)


if __name__ == "__main__":
    results = run_benchmark()
    output = format_results(results)
    print("\n\n" + output)

    out_path = "/home/flaniganp/PycharmProjects/document_search/tests/benchmark_results/format_detect_benchmark.txt"
    with open(out_path, "w") as f:
        f.write(output)
    print(f"\nResults saved to: {out_path}")
