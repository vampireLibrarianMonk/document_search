"""Benchmark: Ask AI (Q&A) models for grounded document question answering.

Tests 13 models on 5 realistic scenarios measuring accuracy, groundedness,
conciseness, latency, and token usage.
"""

import json
import os
import sys
import time
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

REGION = os.getenv("AWS_REGION", "us-east-1")
client = boto3.client("bedrock-runtime", region_name=REGION)

OUT_DIR = Path(__file__).resolve().parent / "benchmark_results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# The actual system prompt from services.py
SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions about house documents "
    "(HOA rules, inspection reports, closing paperwork, insurance, etc). "
    "Answer the question using ONLY the provided document excerpts. "
    "Give a clear, direct answer in plain English that a non-expert would understand. "
    "If the excerpts don't contain enough information to answer, say so honestly."
)

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
    "openai.gpt-oss-120b-1:0",
]

# Test scenarios: (context_passage, question, expected_keywords, scenario_name)
SCENARIOS = [
    {
        "name": "HOA Fence Rules",
        "context": """[HOA Architectural Guidelines - Section 4.7 Fences and Walls]
All perimeter fences and privacy walls must comply with the following standards as approved
by the Architectural Review Committee (ARC). Fences shall not exceed six (6) feet in height
as measured from the natural grade on the higher side. Front yard fences are limited to four
(4) feet and must be of wrought iron or decorative aluminum construction. Chain link fencing
is prohibited in all areas visible from the street. All fence installations require prior ARC
approval with a completed Exterior Modification Application submitted at least 30 days before
construction begins. Wood fences must be cedar or pressure-treated pine with a natural or
semi-transparent stain. Vinyl fencing is permitted in rear yards only. Fence posts must be
set in concrete to a minimum depth of 24 inches.""",
        "question": "How tall can my fence be?",
        "expected": ["6", "six", "feet"],
        "bonus": ["four", "4", "front yard"],
    },
    {
        "name": "Closing Disclosure",
        "context": """[Closing Disclosure - Page 1 Loan Terms]
CLOSING DISCLOSURE - This form is a statement of final loan terms and closing costs.
Loan Terms:
Loan Amount: $420,000.00
Interest Rate: 6.875%
Monthly Principal & Interest: $2,757.43
Loan Term: 30 years
Purpose: Purchase
Product: Fixed Rate
Projected Payments - Payment Calculation:
Principal & Interest: $2,757.43
Mortgage Insurance: $0 (20% down payment)
Estimated Escrow (taxes + insurance): $487.00
Estimated Total Monthly Payment: $3,244.43
This loan does not have a prepayment penalty.
This loan does not have a balloon payment.
Closing Date: March 15, 2024
Property Address: 1847 Oakwood Drive, Gilbert, AZ 85297""",
        "question": "What is my interest rate?",
        "expected": ["6.875"],
        "bonus": ["fixed", "30"],
    },
    {
        "name": "Insurance Declarations",
        "context": """[Homeowners Insurance Declarations Page - Policy HO-2024-7834521]
Named Insured: Patrick Flanigan & Sarah Flanigan
Policy Period: April 1, 2024 to April 1, 2025
Property Address: 1847 Oakwood Drive, Gilbert, AZ 85297
Coverage Summary:
  Coverage A - Dwelling: $525,000
  Coverage B - Other Structures: $52,500 (10% of A)
  Coverage C - Personal Property: $262,500 (50% of A)
  Coverage D - Loss of Use: $157,500 (30% of A)
  Coverage E - Personal Liability: $300,000 per occurrence
  Coverage F - Medical Payments: $5,000 per person
Deductible: $2,500 per occurrence (wind/hail: 2% of Coverage A)
Annual Premium: $2,847.00
Paid by: Escrow
Underwriter: State Farm Fire and Casualty Company
Agent: Jennifer Wu, Gilbert Insurance Group""",
        "question": "How much dwelling coverage do I have?",
        "expected": ["525,000", "525000"],
        "bonus": ["coverage a", "dwelling"],
    },
    {
        "name": "Property Tax Notice",
        "context": """[Maricopa County Treasurer - 2024 Property Tax Statement]
Parcel Number: 304-28-117
Owner: Flanigan Patrick J & Sarah M
Situs Address: 1847 Oakwood Dr, Gilbert AZ 85297
Tax Year 2024 Summary:
  Full Cash Value: $587,400
  Limited Property Value: $498,230
  Primary Tax Rate: 0.8847 per $100 assessed value
  Secondary Tax Rate: 3.2104 per $100 assessed value
  Total Tax: $5,412.78
Payment Schedule:
  First Half Due: October 1, 2024
  First Half Delinquent After: November 1, 2024
  Second Half Due: March 1, 2025
  Second Half Delinquent After: May 1, 2025
Payment Options: Online at mctreasurer.maricopa.gov, by mail, or in person.
If paying in full, the entire amount of $5,412.78 is due by December 31, 2024.
Interest accrues at 16% per annum on delinquent amounts.""",
        "question": "When are my taxes due?",
        "expected": ["november 1", "may 1"],
        "bonus": ["october", "march", "delinquent"],
    },
    {
        "name": "Inspection Report",
        "context": """[Home Inspection Report - Section 3: Roof System]
Inspector: Mike Torres, AZ Certified #48821
Inspection Date: February 28, 2024
Roof Type: Composition shingle (architectural style)
Estimated Age: Approximately 15 years based on wear patterns and permit records
Condition: Fair - showing age-related wear

Observations:
- Multiple areas of curling shingles noted on south-facing slope, likely due to prolonged
  UV exposure and Arizona heat cycling. Approximately 20% of south-facing shingles show
  moderate to severe curling at edges.
- Granule loss observed in valleys and high-traffic areas near HVAC equipment
- One layer of shingles present (good - not over-roofed)
- Flashing at chimney appears intact but sealant is dried and cracked
- Roof vents (turbine style) are functional but showing surface rust
- Gutters: not present (typical for Arizona construction)
- No active leaks detected during inspection; however, given age and condition,
  recommend obtaining quotes from a licensed roofing contractor within the next
  12-24 months for full replacement planning.

Summary: Roof is functional but nearing end of expected service life. The curling
shingles and granule loss indicate the roof is approximately 15 years old and will
need replacement in the near future. Recommend contractor evaluation.""",
        "question": "What did the inspector say about the roof?",
        "expected": ["curling", "shingle", "15", "contractor"],
        "bonus": ["south", "granule", "replacement"],
    },
]


def call_model(model_id: str, context: str, question: str) -> dict:
    """Call a model via Bedrock Converse API, return answer + metrics."""
    user_msg = f"Document excerpts:\n{context}\n\nQuestion: {question}"

    start = time.time()
    try:
        resp = client.converse(
            modelId=model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_msg}]}],
            inferenceConfig={"maxTokens": 512},
        )
        latency = time.time() - start
        answer = resp["output"]["message"]["content"][0]["text"]
        usage = resp.get("usage", {})
        return {
            "answer": answer,
            "latency": latency,
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
            "error": None,
        }
    except Exception as e:
        return {
            "answer": "",
            "latency": time.time() - start,
            "input_tokens": 0,
            "output_tokens": 0,
            "error": str(e),
        }


def score_accuracy(answer: str, expected: list[str], bonus: list[str]) -> int:
    """Score 0-5: how many expected facts appear in the answer."""
    lower = answer.lower()
    # Must have at least one primary expected keyword
    primary_hits = sum(1 for k in expected if k.lower() in lower)
    bonus_hits = sum(1 for k in bonus if k.lower() in lower)

    if primary_hits == 0:
        return 0
    # Base score from primary (up to 3 points)
    base = min(3, primary_hits)
    # Bonus points (up to 2)
    extra = min(2, bonus_hits)
    return min(5, base + extra)


def score_groundedness(answer: str, context: str) -> int:
    """Score 0-1: 1 if answer appears grounded, 0 if hallucination detected.

    Simple heuristic: check if answer introduces specific numbers/names not in context.
    """
    import re

    # Extract dollar amounts and percentages from answer
    answer_numbers = set(re.findall(r"\$[\d,]+\.?\d*|\d+\.?\d*%", answer))
    context_lower = context.lower()

    for num in answer_numbers:
        # Clean for lookup
        clean = num.replace("$", "").replace(",", "").replace("%", "")
        if clean and clean not in context_lower and num not in context:
            # Found a specific number in answer not in context - possible hallucination
            return 0
    return 1


def score_conciseness(answer: str) -> int:
    """Score 0-5 for conciseness. Shorter focused answers score higher."""
    words = len(answer.split())
    if words <= 30:
        return 5
    elif words <= 60:
        return 4
    elif words <= 100:
        return 3
    elif words <= 150:
        return 2
    elif words <= 250:
        return 1
    return 0


def run_benchmark():
    """Run all models on all scenarios and print results."""
    results = {}

    print("=" * 80)
    print("ASK AI (Q&A) MODEL BENCHMARK")
    print("=" * 80)
    print(f"Models: {len(MODELS)}")
    print(f"Scenarios: {len(SCENARIOS)}")
    print(f"Region: {REGION}")
    print("=" * 80)

    for model_id in MODELS:
        short_name = model_id.split(".")[-1] if "." in model_id else model_id
        print(f"\n{'─' * 60}")
        print(f"Testing: {model_id}")
        print(f"{'─' * 60}")

        model_scores = {
            "accuracy": 0,
            "groundedness": 0,
            "conciseness": 0,
            "total_latency": 0.0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "errors": 0,
            "answers": [],
        }

        for scenario in SCENARIOS:
            result = call_model(model_id, scenario["context"], scenario["question"])

            if result["error"]:
                print(f"  ✗ {scenario['name']}: ERROR - {result['error'][:80]}")
                model_scores["errors"] += 1
                model_scores["answers"].append({"scenario": scenario["name"], "error": result["error"]})
                continue

            acc = score_accuracy(result["answer"], scenario["expected"], scenario["bonus"])
            grounded = score_groundedness(result["answer"], scenario["context"])
            concise = score_conciseness(result["answer"])

            model_scores["accuracy"] += acc
            model_scores["groundedness"] += grounded
            model_scores["conciseness"] += concise
            model_scores["total_latency"] += result["latency"]
            model_scores["total_input_tokens"] += result["input_tokens"]
            model_scores["total_output_tokens"] += result["output_tokens"]

            status = "✓" if acc >= 3 else "△" if acc >= 1 else "✗"
            print(
                f"  {status} {scenario['name']}: acc={acc}/5 "
                f"grounded={'Y' if grounded else 'N'} "
                f"concise={concise}/5 "
                f"latency={result['latency']:.2f}s "
                f"tokens={result['input_tokens']}→{result['output_tokens']}"
            )
            model_scores["answers"].append({
                "scenario": scenario["name"],
                "answer": result["answer"][:200],
                "accuracy": acc,
                "grounded": grounded,
                "conciseness": concise,
                "latency": result["latency"],
            })

        results[model_id] = model_scores

    # Print ranked results
    print("\n\n")
    print("=" * 100)
    print("RANKED RESULTS")
    print("=" * 100)

    # Calculate composite score
    ranked = []
    for model_id, scores in results.items():
        n = len(SCENARIOS) - scores["errors"]
        if n == 0:
            ranked.append((model_id, 0, scores))
            continue

        # Accuracy: 0-25 (5 per scenario)
        accuracy = scores["accuracy"]
        # Groundedness: penalty of -5 per hallucination detected
        hallucination_penalty = (n - scores["groundedness"]) * 5
        # Conciseness: 0-25 (5 per scenario)
        conciseness = scores["conciseness"]
        # Latency bonus: faster = better (0-10 scale)
        avg_latency = scores["total_latency"] / n
        latency_score = max(0, 10 - avg_latency)  # 1s = 9pts, 5s = 5pts, 10s = 0pts

        composite = accuracy + conciseness + latency_score - hallucination_penalty
        if scores["errors"] > 0:
            composite -= scores["errors"] * 10  # Heavy penalty for errors

        ranked.append((model_id, composite, scores))

    ranked.sort(key=lambda x: x[1], reverse=True)

    # Header
    header = f"{'Rank':<5}{'Model':<42}{'Acc':>5}{'Gnd':>5}{'Cnc':>5}{'Lat':>7}{'Tok In':>8}{'Tok Out':>9}{'Score':>7}{'Err':>5}"
    print(header)
    print("─" * len(header))

    for rank, (model_id, composite, scores) in enumerate(ranked, 1):
        n = len(SCENARIOS) - scores["errors"]
        avg_lat = scores["total_latency"] / n if n > 0 else 0
        print(
            f"{rank:<5}"
            f"{model_id:<42}"
            f"{scores['accuracy']:>3}/25"
            f"{scores['groundedness']:>3}/5"
            f"{scores['conciseness']:>3}/25"
            f"{avg_lat:>6.2f}s"
            f"{scores['total_input_tokens']:>8}"
            f"{scores['total_output_tokens']:>9}"
            f"{composite:>7.1f}"
            f"{scores['errors']:>5}"
        )

    # Legend
    print("\n" + "─" * 80)
    print("Scoring:")
    print("  Acc (Accuracy): 0-25 (5 pts per scenario for correct key facts)")
    print("  Gnd (Groundedness): 0-5 (1 pt per scenario if no hallucination detected)")
    print("  Cnc (Conciseness): 0-25 (5 pts per scenario for focused answers)")
    print("  Lat (Latency): average seconds per call")
    print("  Score = Accuracy + Conciseness + LatencyBonus(10-avgLat) - HallucinationPenalty(5 each) - ErrorPenalty(10 each)")
    print("─" * 80)

    # Save to file
    output_file = OUT_DIR / "ask_ai_benchmark.txt"
    with open(output_file, "w") as f:
        f.write("ASK AI (Q&A) MODEL BENCHMARK RESULTS\n")
        f.write(f"{'=' * 80}\n")
        f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Region: {REGION}\n")
        f.write(f"Models tested: {len(MODELS)}\n")
        f.write(f"Scenarios: {len(SCENARIOS)}\n\n")

        f.write(f"System Prompt:\n  {SYSTEM_PROMPT}\n\n")

        f.write(f"{'=' * 100}\n")
        f.write("RANKED RESULTS\n")
        f.write(f"{'=' * 100}\n")
        f.write(header + "\n")
        f.write("─" * len(header) + "\n")

        for rank, (model_id, composite, scores) in enumerate(ranked, 1):
            n = len(SCENARIOS) - scores["errors"]
            avg_lat = scores["total_latency"] / n if n > 0 else 0
            f.write(
                f"{rank:<5}"
                f"{model_id:<42}"
                f"{scores['accuracy']:>3}/25"
                f"{scores['groundedness']:>3}/5"
                f"{scores['conciseness']:>3}/25"
                f"{avg_lat:>6.2f}s"
                f"{scores['total_input_tokens']:>8}"
                f"{scores['total_output_tokens']:>9}"
                f"{composite:>7.1f}"
                f"{scores['errors']:>5}"
                + "\n"
            )

        f.write(f"\n{'─' * 80}\n")
        f.write("Scoring:\n")
        f.write("  Acc (Accuracy): 0-25 (5 pts per scenario for correct key facts)\n")
        f.write("  Gnd (Groundedness): 0-5 (1 pt per scenario if no hallucination detected)\n")
        f.write("  Cnc (Conciseness): 0-25 (5 pts per scenario for focused answers)\n")
        f.write("  Lat (Latency): average seconds per call\n")
        f.write("  Score = Accuracy + Conciseness + LatencyBonus(10-avgLat) - HallucinationPenalty(5 each) - ErrorPenalty(10 each)\n")
        f.write(f"{'─' * 80}\n")

        f.write(f"\n\n{'=' * 80}\n")
        f.write("DETAILED ANSWERS PER MODEL\n")
        f.write(f"{'=' * 80}\n")

        for model_id, scores in results.items():
            f.write(f"\n{'─' * 60}\n")
            f.write(f"{model_id}\n")
            f.write(f"{'─' * 60}\n")
            for ans in scores["answers"]:
                if "error" in ans:
                    f.write(f"  {ans['scenario']}: ERROR - {ans['error'][:100]}\n")
                else:
                    f.write(f"  {ans['scenario']}:\n")
                    f.write(f"    Accuracy: {ans['accuracy']}/5 | Grounded: {'Y' if ans['grounded'] else 'N'} | Concise: {ans['conciseness']}/5 | Latency: {ans['latency']:.2f}s\n")
                    f.write(f"    Answer: {ans['answer']}\n")

    print(f"\n\nResults saved to: {output_file}")

    # Also save raw JSON for further analysis
    json_file = OUT_DIR / "ask_ai_benchmark.json"
    with open(json_file, "w") as f:
        json.dump(
            {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "region": REGION,
                "system_prompt": SYSTEM_PROMPT,
                "models": MODELS,
                "results": {
                    model_id: {
                        "accuracy": s["accuracy"],
                        "groundedness": s["groundedness"],
                        "conciseness": s["conciseness"],
                        "avg_latency": s["total_latency"] / max(1, len(SCENARIOS) - s["errors"]),
                        "total_input_tokens": s["total_input_tokens"],
                        "total_output_tokens": s["total_output_tokens"],
                        "errors": s["errors"],
                        "answers": s["answers"],
                    }
                    for model_id, s in results.items()
                },
                "ranked": [
                    {"rank": i + 1, "model": m, "composite_score": round(c, 1)}
                    for i, (m, c, _) in enumerate(ranked)
                ],
            },
            f,
            indent=2,
            default=str,
        )
    print(f"JSON saved to: {json_file}")


if __name__ == "__main__":
    run_benchmark()
