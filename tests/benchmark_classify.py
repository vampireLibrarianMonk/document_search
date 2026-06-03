"""Benchmark text generation models on the document classification task."""

import json
import re
import time
import boto3
import sys

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

MODELS = [
    "amazon.nova-micro-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.nova-pro-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "anthropic.claude-3-sonnet-20240229-v1:0",
    "mistral.mistral-large-2402-v1:0",
    "mistral.mistral-small-2402-v1:0",
    "mistral.magistral-small-2509",
    "meta.llama3-70b-instruct-v1:0",
    "qwen.qwen3-32b-v1:0",
    "deepseek.v3.2",
    "nvidia.nemotron-super-3-120b",
    "zai.glm-5",
]

TEST_DOCS = [
    {
        "filename": "hoa_bylaws.pdf",
        "text": "Section 4.2 Fencing Requirements. All perimeter barriers including fences shall not exceed six (6) feet in height from finished grade. Materials must be wood, vinyl, or wrought iron. Chain link fencing is prohibited in all areas visible from the street.",
        "expected_category": "HOA Governance",
    },
    {
        "filename": "inspection_report.pdf",
        "text": "Roof Inspection Summary. The roof covering is architectural shingles, approximately 15 years old. Several shingles show curling and granule loss on the south-facing slope. Flashing around the chimney shows minor separation. Recommend evaluation by a qualified roofing contractor within 2-3 years.",
        "expected_category": "Inspection Reports",
    },
    {
        "filename": "closing_disclosure.pdf",
        "text": "CLOSING DISCLOSURE. This form is a statement of final loan terms and closing costs. Loan Amount: $425,000. Interest Rate: 6.875%. Monthly P&I: $2,791.53. Closing Date: March 15, 2026. Property: 123 Oak Lane, Springfield, VA 22152.",
        "expected_category": "Closing Documents",
    },
    {
        "filename": "insurance_declarations.pdf",
        "text": "HOMEOWNERS INSURANCE DECLARATIONS PAGE. Policy Number: HO-2026-881234. Named Insured: Patrick Flanigan. Property Address: 123 Oak Lane, Springfield, VA 22152. Coverage A Dwelling: $525,000. Coverage B Other Structures: $52,500. Annual Premium: $1,847.",
        "expected_category": "Insurance",
    },
    {
        "filename": "tax_assessment.pdf",
        "text": "REAL PROPERTY TAX ASSESSMENT NOTICE. Tax Year 2026. Owner: Patrick M. Flanigan. Parcel: 0584-12-0043. Land Value: $285,000. Improvement Value: $340,000. Total Assessed: $625,000. Tax Rate: $1.15 per $100. Annual Tax Due: $7,187.50. Due dates: November 1 and May 1.",
        "expected_category": "Property Tax",
    },
]

EXISTING_CATEGORIES = ["Closing Documents", "HOA Governance", "Inspection Reports", "Insurance", "Property Tax", "Mortgage", "Title & Deed", "Appraisal/Valuation"]

# Category aliases for flexible matching
CATEGORY_ALIASES = {
    "HOA Governance": ["hoa governance", "hoa", "homeowners association", "hoa rules", "hoa bylaws"],
    "Inspection Reports": ["inspection reports", "inspection", "home inspection", "inspection report"],
    "Closing Documents": ["closing documents", "closing", "closing disclosure", "loan closing", "tax & legal"],
    "Insurance": ["insurance", "homeowners insurance", "home insurance", "insurance policy"],
    "Property Tax": ["property tax", "tax", "tax assessment", "real property tax", "tax & legal"],
}


def build_prompt(filename: str, text: str) -> str:
    categories_hint = f"\n\nExisting categories in this collection: {json.dumps(EXISTING_CATEGORIES)}\nUse one of these if the document clearly fits. Create a new category if none are a good match. Be precise — do not lump unrelated services together (e.g. HVAC repair is not Vehicle Maintenance)."
    return (
        f"Classify this document. Return ONLY a JSON object with these fields:\n"
        f"- \"category\": a short human-readable group name that describes the domain (e.g. \"Home Maintenance\", \"Medical Records\", \"Tax & Legal\", \"Vehicle Maintenance\"). Choose based on the actual subject matter of the document, not just the document format.\n"
        f"- \"document_type\": a snake_case type (e.g. \"invoice\", \"estimate\", \"proposal\", \"inspection_report\", \"insurance_policy\")\n"
        f"- \"tags\": a list of 1-3 relevant keyword tags\n"
        f"- \"title\": a clear, descriptive title for this document (e.g. \"HVAC Ductwork Repair Estimate - Reddick & Sons\" or \"Q1 2024 HOA Budget Report\"). Make it specific enough to distinguish from similar documents.\n"
        f"- \"document_date\": the date of the document in YYYY-MM-DD format (e.g. \"2026-05-19\"). Extract from the document content (statement date, invoice date, letter date, etc.). Use null if no date is found.\n"
        f"\nImportant distinctions:\n"
        f"- \"Appraisal\" means a professional property valuation (market value, comparable sales). Do NOT use it for contractor estimates, proposals, or quotes.\n"
        f"- Contractor estimates, proposals, and quotes for future work belong in \"Home Maintenance\" or a similar service category, with document_type like \"estimate\" or \"proposal\".\n"
        f"- Recurring statements (mortgage, bank, utility, credit card) belong in \"Account Statements\", NOT \"Tax & Legal\".\n"
        f"- \"Tax & Legal\" is for one-time legal documents, tax filings, contracts, deeds, and closing paperwork.\n"
        f"- Insurance documents (policies, declarations, coverage confirmations, certificates of insurance) belong in \"Insurance\", NOT \"Tax & Legal\".\n"
        f"- For recurring or dated documents, always include the date (month/year) in the title.\n"
        f"{categories_hint}\n\n"
        f"Filename: {filename}\n\n"
        f"Document text (first 2000 chars):\n{text}"
    )


def category_matches(got: str, expected: str) -> bool:
    got_lower = got.lower().strip()
    expected_lower = expected.lower().strip()
    if got_lower == expected_lower:
        return True
    aliases = CATEGORY_ALIASES.get(expected, [])
    return got_lower in aliases


def run_classify(model_id: str, filename: str, text: str):
    prompt = build_prompt(filename, text)
    start = time.time()
    try:
        resp = bedrock.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 256},
        )
        latency = time.time() - start
        raw = resp["output"]["message"]["content"][0]["text"]
        usage = resp.get("usage", {})
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)
        return {"raw": raw, "latency": latency, "input_tokens": input_tokens, "output_tokens": output_tokens, "error": None}
    except Exception as e:
        return {"raw": "", "latency": time.time() - start, "input_tokens": 0, "output_tokens": 0, "error": str(e)}


def parse_result(raw: str):
    """Try to extract JSON from model response."""
    # Try markdown code block first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1)), True
        except json.JSONDecodeError:
            pass
    # Try bare JSON
    m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group()), True
        except json.JSONDecodeError:
            pass
    return {}, False


def main():
    results = []
    total = len(MODELS) * len(TEST_DOCS)
    done = 0

    for model_id in MODELS:
        model_results = {"model": model_id, "valid_json": 0, "field_completeness": 0, "category_accuracy": 0, "total_latency": 0, "total_input_tokens": 0, "total_output_tokens": 0, "errors": 0, "details": []}

        print(f"\n{'='*60}")
        print(f"Model: {model_id}")
        print(f"{'='*60}")

        for doc in TEST_DOCS:
            done += 1
            print(f"  [{done}/{total}] {doc['filename']}...", end=" ", flush=True)

            resp = run_classify(model_id, doc["filename"], doc["text"])

            if resp["error"]:
                print(f"ERROR: {resp['error'][:80]}")
                model_results["errors"] += 1
                model_results["details"].append({"doc": doc["filename"], "error": resp["error"], "valid_json": False, "fields_present": 0, "category_correct": False, "latency": resp["latency"]})
                continue

            parsed, valid = parse_result(resp["raw"])
            model_results["total_latency"] += resp["latency"]
            model_results["total_input_tokens"] += resp["input_tokens"]
            model_results["total_output_tokens"] += resp["output_tokens"]

            if valid:
                model_results["valid_json"] += 1

            required_fields = ["category", "document_type", "tags", "title", "document_date"]
            fields_present = sum(1 for f in required_fields if f in parsed and parsed[f] is not None)
            # document_date can be null legitimately, but it should still be present as a key
            if "document_date" not in parsed:
                pass  # already counted as missing
            model_results["field_completeness"] += fields_present

            cat = parsed.get("category", "")
            cat_correct = category_matches(cat, doc["expected_category"])
            if cat_correct:
                model_results["category_accuracy"] += 1

            status = "✓" if (valid and cat_correct and fields_present == 5) else "○"
            print(f"{status} json={valid} fields={fields_present}/5 cat={'✓' if cat_correct else '✗'}({cat}) {resp['latency']:.1f}s {resp['input_tokens']+resp['output_tokens']}tok")

            model_results["details"].append({
                "doc": doc["filename"],
                "valid_json": valid,
                "fields_present": fields_present,
                "category_correct": cat_correct,
                "category_got": cat,
                "latency": resp["latency"],
                "tokens": resp["input_tokens"] + resp["output_tokens"],
            })

        results.append(model_results)

    # Print summary table
    print("\n\n")
    print("=" * 120)
    print("CLASSIFICATION BENCHMARK RESULTS")
    print("=" * 120)
    header = f"{'Model':<45} {'JSON':>4} {'Fields':>6} {'CatAcc':>6} {'AvgLat':>7} {'InTok':>7} {'OutTok':>7} {'Errors':>6} {'Score':>6}"
    print(header)
    print("-" * 120)

    scored = []
    for r in results:
        n = len(TEST_DOCS)
        n_ok = n - r["errors"]
        json_rate = r["valid_json"] / n if n > 0 else 0
        field_rate = r["field_completeness"] / (n * 5) if n > 0 else 0
        cat_rate = r["category_accuracy"] / n if n > 0 else 0
        avg_lat = r["total_latency"] / n_ok if n_ok > 0 else 99
        # Score: 40% category accuracy + 30% field completeness + 20% json validity + 10% speed (lower is better, cap at 10s)
        speed_score = max(0, 1 - avg_lat / 10)
        score = cat_rate * 40 + field_rate * 30 + json_rate * 20 + speed_score * 10
        if r["errors"] == n:
            score = 0
        scored.append((score, r, json_rate, field_rate, cat_rate, avg_lat))

    scored.sort(key=lambda x: -x[0])

    for score, r, json_rate, field_rate, cat_rate, avg_lat in scored:
        n = len(TEST_DOCS)
        n_ok = n - r["errors"]
        line = f"{r['model']:<45} {r['valid_json']}/{n:>2} {r['field_completeness']:>3}/{n*5}  {r['category_accuracy']}/{n:>2}  {avg_lat:>6.2f}s {r['total_input_tokens']:>7} {r['total_output_tokens']:>7} {r['errors']:>6} {score:>6.1f}"
        print(line)

    print("-" * 120)
    print(f"\nScoring: 40% category accuracy + 30% field completeness + 20% JSON validity + 10% speed (sub-10s)")
    print(f"Tests: {len(TEST_DOCS)} documents × {len(MODELS)} models = {total} classifications")

    # Save to file
    output_path = "/home/flaniganp/PycharmProjects/document_search/tests/benchmark_results/classify_benchmark.txt"
    with open(output_path, "w") as f:
        f.write("CLASSIFICATION BENCHMARK RESULTS\n")
        f.write(f"{'='*120}\n")
        f.write(f"Tests: {len(TEST_DOCS)} documents × {len(MODELS)} models = {total} classifications\n")
        f.write(f"Scoring: 40% category accuracy + 30% field completeness + 20% JSON validity + 10% speed\n\n")
        f.write(header + "\n")
        f.write("-" * 120 + "\n")
        for score, r, json_rate, field_rate, cat_rate, avg_lat in scored:
            n = len(TEST_DOCS)
            line = f"{r['model']:<45} {r['valid_json']}/{n:>2} {r['field_completeness']:>3}/{n*5}  {r['category_accuracy']}/{n:>2}  {avg_lat:>6.2f}s {r['total_input_tokens']:>7} {r['total_output_tokens']:>7} {r['errors']:>6} {score:>6.1f}"
            f.write(line + "\n")
        f.write("-" * 120 + "\n")
        f.write(f"\nRanking (best to worst):\n")
        for i, (score, r, *_) in enumerate(scored, 1):
            f.write(f"  {i}. {r['model']} — score: {score:.1f}\n")
        f.write(f"\n\nDETAILED RESULTS\n{'='*120}\n")
        for score, r, *_ in scored:
            f.write(f"\n{r['model']} (score: {score:.1f})\n")
            for d in r["details"]:
                if d.get("error"):
                    f.write(f"  {d['doc']}: ERROR — {d['error'][:100]}\n")
                else:
                    f.write(f"  {d['doc']}: json={d['valid_json']} fields={d['fields_present']}/5 cat={'✓' if d['category_correct'] else '✗'}({d.get('category_got','?')}) {d['latency']:.1f}s {d.get('tokens',0)}tok\n")

    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
