"""Vision OCR model benchmark.

Generates test images with known text, sends them to each vision model via
Bedrock Converse API, and scores accuracy, formatting, hallucination, and latency.
"""

import io
import time
import textwrap
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import boto3
from PIL import Image, ImageDraw, ImageFont

REGION = "us-east-1"
OUTPUT_FILE = "/home/flaniganp/PycharmProjects/document_search/tests/benchmark_results/vision_ocr_benchmark.txt"

PROMPT = (
    "Extract ALL text from this document image, including: company names in logos "
    "or headers, watermarks, stamps, handwritten notes, footer text, and any text "
    "embedded in images or graphics. Read every piece of visible text on the page. "
    "Return only the text content, no commentary."
)

MODELS = [
    "anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.nova-pro-v1:0",
    "mistral.mistral-large-3-675b-instruct",
    "mistral.ministral-3-3b-instruct",
    "mistral.ministral-3-8b-instruct",
    "mistral.ministral-3-14b-instruct",
    "mistral.magistral-small-2509",
    "google.gemma-3-4b-it",
    "google.gemma-3-12b-it",
    "google.gemma-3-27b-it",
    "nvidia.nemotron-nano-12b-v2",
    "qwen.qwen3-vl-235b-a22b",
    "writer.palmyra-vision-7b",
    "moonshotai.kimi-k2.5",
]

# Test cases: (name, ground_truth_text, key_tokens for accuracy scoring)
SIMPLE_TEXT = "Annual HOA Assessment: $275.00 per quarter"
SIMPLE_KEYS = ["Annual", "HOA", "Assessment", "$275.00", "per", "quarter"]

MEDIUM_TEXT = "CLOSING DISCLOSURE\nLoan Amount: $425,000\nInterest Rate: 6.875%\nMonthly Payment: $2,791.53"
MEDIUM_KEYS = ["CLOSING", "DISCLOSURE", "Loan Amount", "$425,000", "Interest Rate", "6.875%", "Monthly Payment", "$2,791.53"]

COMPLEX_TEXT = """PROPERTY INSPECTION REPORT
Date: March 15, 2024
Inspector: John R. Martinez, License #HI-4892

ROOF CONDITION
Type: Architectural shingles (30-year)
Age: Approximately 8 years
Condition: Fair - minor granule loss observed
Estimated Remaining Life: 12-15 years
Repair Cost Estimate: $1,200 - $2,500

ELECTRICAL SYSTEM
Panel: 200 amp, Square D brand
Grounding: Copper rod, verified
GFCI Protection: Present in kitchen, bathrooms
Arc-Fault Breakers: Installed in bedrooms
Deficiency: Outlet in garage not GFCI protected"""

COMPLEX_KEYS = [
    "PROPERTY INSPECTION REPORT", "March 15, 2024", "John R. Martinez",
    "HI-4892", "Architectural shingles", "30-year", "8 years", "Fair",
    "12-15 years", "$1,200", "$2,500", "200 amp", "Square D", "Copper rod",
    "GFCI", "Arc-Fault", "garage", "not GFCI protected"
]


def render_text_image(text: str, width=800, font_size=18) -> bytes:
    """Render text onto a white PNG image."""
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    lines = text.split("\n")
    line_height = font_size + 8
    height = max(200, len(lines) * line_height + 80)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    y = 30
    for line in lines:
        draw.text((30, y), line, fill="black", font=font)
        y += line_height

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@dataclass
class ModelResult:
    model: str
    test_name: str
    extracted: str = ""
    latency_s: float = 0.0
    accuracy: float = 0.0
    formatting: float = 0.0
    hallucination_penalty: float = 0.0
    error: str = ""


def score_accuracy(extracted: str, key_tokens: list[str]) -> float:
    """Score 0-10 based on what fraction of key tokens appear in the extracted text."""
    if not extracted:
        return 0.0
    lower = extracted.lower()
    found = sum(1 for k in key_tokens if k.lower() in lower)
    return round((found / len(key_tokens)) * 10, 1)


def score_formatting(extracted: str, ground_truth: str) -> float:
    """Score 0-5 based on structural preservation (line breaks, headings)."""
    if not extracted:
        return 0.0
    gt_lines = [l.strip() for l in ground_truth.strip().split("\n") if l.strip()]
    ext_lines = [l.strip() for l in extracted.strip().split("\n") if l.strip()]
    # Credit for having similar number of lines
    line_ratio = min(len(ext_lines), len(gt_lines)) / max(len(gt_lines), 1)
    # Credit for sequence similarity
    seq_score = SequenceMatcher(None, ground_truth.lower(), extracted.lower()).ratio()
    return round((line_ratio * 2.5 + seq_score * 2.5), 1)


def score_hallucination(extracted: str, ground_truth: str) -> float:
    """Penalty 0-5 for added content not in the original."""
    if not extracted:
        return 0.0
    # If output is much longer than expected, likely hallucinating
    len_ratio = len(extracted) / max(len(ground_truth), 1)
    if len_ratio > 3.0:
        return 5.0
    elif len_ratio > 2.0:
        return 3.0
    elif len_ratio > 1.5:
        return 1.0
    return 0.0


def call_vision_model(client, model_id: str, image_bytes: bytes) -> tuple[str, float]:
    """Call Bedrock Converse API with image. Returns (text, latency_seconds)."""
    start = time.time()
    resp = client.converse(
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": "png", "source": {"bytes": image_bytes}}},
                    {"text": PROMPT},
                ],
            },
        ],
        inferenceConfig={"maxTokens": 4096},
    )
    latency = time.time() - start
    text = resp["output"]["message"]["content"][0]["text"]
    return text, latency


def run_benchmark():
    client = boto3.client("bedrock-runtime", region_name=REGION)

    # Generate test images
    test_cases = [
        ("simple", SIMPLE_TEXT, SIMPLE_KEYS, render_text_image(SIMPLE_TEXT)),
        ("medium", MEDIUM_TEXT, MEDIUM_KEYS, render_text_image(MEDIUM_TEXT, width=900)),
        ("complex", COMPLEX_TEXT, COMPLEX_KEYS, render_text_image(COMPLEX_TEXT, width=1000, font_size=16)),
    ]

    all_results: list[ModelResult] = []

    for model_id in MODELS:
        print(f"\n{'='*60}")
        print(f"Testing: {model_id}")
        print(f"{'='*60}")

        for test_name, ground_truth, keys, img_bytes in test_cases:
            result = ModelResult(model=model_id, test_name=test_name)
            try:
                extracted, latency = call_vision_model(client, model_id, img_bytes)
                result.extracted = extracted
                result.latency_s = latency
                result.accuracy = score_accuracy(extracted, keys)
                result.formatting = score_formatting(extracted, ground_truth)
                result.hallucination_penalty = score_hallucination(extracted, ground_truth)
                print(f"  {test_name}: acc={result.accuracy}/10 fmt={result.formatting}/5 "
                      f"hall=-{result.hallucination_penalty} lat={latency:.2f}s")
            except Exception as e:
                error_msg = str(e)[:120]
                result.error = error_msg
                print(f"  {test_name}: ERROR - {error_msg}")

            all_results.append(result)

    # Aggregate scores per model
    print("\n\n")
    print("=" * 100)
    print("VISION OCR BENCHMARK RESULTS")
    print("=" * 100)

    # Build per-model aggregates
    model_scores: dict[str, dict] = {}
    for r in all_results:
        if r.model not in model_scores:
            model_scores[r.model] = {
                "accuracy": [], "formatting": [], "hallucination": [],
                "latency": [], "errors": 0, "tests": 0
            }
        ms = model_scores[r.model]
        ms["tests"] += 1
        if r.error:
            ms["errors"] += 1
        else:
            ms["accuracy"].append(r.accuracy)
            ms["formatting"].append(r.formatting)
            ms["hallucination"].append(r.hallucination_penalty)
            ms["latency"].append(r.latency_s)

    # Calculate composite score and rank
    ranked = []
    for model, scores in model_scores.items():
        if scores["errors"] == scores["tests"]:
            ranked.append((model, 0, 0, 0, 0, 0, scores["errors"], "ALL FAILED"))
            continue
        avg_acc = sum(scores["accuracy"]) / len(scores["accuracy"]) if scores["accuracy"] else 0
        avg_fmt = sum(scores["formatting"]) / len(scores["formatting"]) if scores["formatting"] else 0
        avg_hall = sum(scores["hallucination"]) / len(scores["hallucination"]) if scores["hallucination"] else 0
        avg_lat = sum(scores["latency"]) / len(scores["latency"]) if scores["latency"] else 0
        # Composite: accuracy (weight 2) + formatting - hallucination penalty
        composite = avg_acc * 2 + avg_fmt - avg_hall * 2
        ranked.append((model, composite, avg_acc, avg_fmt, avg_hall, avg_lat, scores["errors"], ""))

    ranked.sort(key=lambda x: x[1], reverse=True)

    # Format output
    output_lines = []
    output_lines.append("=" * 110)
    output_lines.append("VISION OCR MODEL BENCHMARK RESULTS")
    output_lines.append(f"Region: {REGION} | Test images: 3 (simple, medium, complex)")
    output_lines.append(f"Prompt: {PROMPT[:80]}...")
    output_lines.append("=" * 110)
    output_lines.append("")
    output_lines.append(f"{'Rank':<5}{'Model':<48}{'Composite':<10}{'Acc/10':<8}{'Fmt/5':<7}{'Hall':<7}{'Lat(s)':<8}{'Errors':<7}")
    output_lines.append("-" * 110)

    for i, (model, composite, acc, fmt, hall, lat, errors, note) in enumerate(ranked, 1):
        if note:
            output_lines.append(f"{i:<5}{model:<48}{'N/A':<10}{'N/A':<8}{'N/A':<7}{'N/A':<7}{'N/A':<8}{errors:<7} {note}")
        else:
            output_lines.append(f"{i:<5}{model:<48}{composite:<10.1f}{acc:<8.1f}{fmt:<7.1f}{hall:<7.1f}{lat:<8.2f}{errors:<7}")

    output_lines.append("-" * 110)
    output_lines.append("")
    output_lines.append("Scoring: Composite = Accuracy*2 + Formatting - Hallucination*2")
    output_lines.append("  Accuracy (0-10): % of key tokens correctly extracted")
    output_lines.append("  Formatting (0-5): structural preservation (line breaks, headings)")
    output_lines.append("  Hallucination (0-5): penalty for added content not in original")
    output_lines.append("  Latency: average seconds per image")
    output_lines.append("")

    # Detailed results per model
    output_lines.append("")
    output_lines.append("=" * 110)
    output_lines.append("DETAILED RESULTS BY MODEL")
    output_lines.append("=" * 110)

    for model_id in MODELS:
        model_results = [r for r in all_results if r.model == model_id]
        output_lines.append(f"\n{'─'*80}")
        output_lines.append(f"Model: {model_id}")
        output_lines.append(f"{'─'*80}")
        for r in model_results:
            if r.error:
                output_lines.append(f"  [{r.test_name}] ERROR: {r.error}")
            else:
                output_lines.append(f"  [{r.test_name}] acc={r.accuracy}/10 fmt={r.formatting}/5 hall=-{r.hallucination_penalty} lat={r.latency_s:.2f}s")
                # Show first 200 chars of extracted text
                preview = r.extracted[:200].replace("\n", "\\n")
                output_lines.append(f"    Output: {preview}...")

    result_text = "\n".join(output_lines)
    print(result_text)

    with open(OUTPUT_FILE, "w") as f:
        f.write(result_text)
    print(f"\n\nResults saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    run_benchmark()
