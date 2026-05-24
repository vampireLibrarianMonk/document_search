"""Task pipeline test runner.

Runs the test series from task_test_series.md against all models
and produces a results markdown file with tables.

Usage: python3 tests/run_task_tests.py
"""

import json
import time
import subprocess
import os

API = "https://api.localhost"

# Test prompts with expected markers for automated scoring
TESTS = {
    # SHORT
    "S1": {
        "prompt": "What is the monthly HOA fee and who is the management company?",
        "expected_facts": ["173.13", "82.13", "91.00", "national realty partners", "703-435-3800"],
        "expected_entities": [],
        "sections": 0,
        "quality_markers": ["hoa", "management"],
    },
    "S2": {
        "prompt": "What did the home inspection find wrong with the roof?",
        "expected_facts": ["split seam", "ponding", "sealant", "flashing"],
        "expected_entities": [],
        "sections": 0,
        "quality_markers": ["membrane", "leak"],
    },
    "S3": {
        "prompt": "What is the cheapest roof repair option and what does it include?",
        "expected_facts": ["2,289", "caulking", "flashing", "1 year", "virginia roofing"],
        "expected_entities": ["virginia roofing"],
        "sections": 0,
        "quality_markers": ["warranty"],
    },
    "S4": {
        "prompt": "Does the HOA require neighbor signatures for exterior modifications?",
        "expected_facts": ["signature", "neighbor", "adjacent"],
        "expected_entities": [],
        "sections": 0,
        "quality_markers": ["arb", "application"],
    },
    "S5": {
        "prompt": "When was the property purchased and for how much?",
        "expected_facts": ["850,000", "april", "2026"],
        "expected_entities": [],
        "sections": 0,
        "quality_markers": ["closing"],
    },
    # MEDIUM
    "M1": {
        "prompt": "Create a comparison table of all roof replacement options. Include company name, material type, warranty length, and price for each option. Note which ones can be done without neighbor involvement.",
        "expected_facts": ["12,800", "15,704", "10,595", "16,114", "20,996", "2,289", "2,850"],
        "expected_entities": ["all day roofing", "virginia roofing", "brax roofing", "american home"],
        "sections": 0,
        "quality_markers": ["parapet", "warranty", "neighbor"],
    },
    "M2": {
        "prompt": "Summarize all monthly and recurring costs for this property: mortgage payment, HOA fees, insurance, and any other regular expenses. Include the total monthly cost.",
        "expected_facts": ["5,047", "173.13", "82.13", "91.00"],
        "expected_entities": ["onity", "centerpointe", "usaa"],
        "sections": 0,
        "quality_markers": ["mortgage", "insurance", "escrow"],
    },
    "M3": {
        "prompt": "Create a timeline of all events related to this property from earliest to most recent. Include purchase, inspections, insurance, and any maintenance work.",
        "expected_facts": ["april 2", "april 6", "april 10", "may 12", "may 19"],
        "expected_entities": [],
        "sections": 0,
        "quality_markers": ["closing", "inspection", "estimate"],
    },
    "M4": {
        "prompt": "List every contractor, vendor, and service provider mentioned in my documents with their contact information (phone, email, address, license number).",
        "expected_facts": ["703-627-0771", "703-751-3200", "301-209-7000", "2705171165"],
        "expected_entities": ["all day roofing", "virginia roofing", "brax roofing", "american home", "dryer vent", "reddick"],
        "sections": 0,
        "quality_markers": ["license", "phone", "email"],
    },
    "M5": {
        "prompt": "What does my homeowners insurance cover? Include coverage amounts, deductibles, and what is specifically excluded. Who is the carrier and what is the policy number?",
        "expected_facts": ["usaa", "replacement cost"],
        "expected_entities": ["usaa"],
        "sections": 0,
        "quality_markers": ["coverage", "policy", "deductible"],
    },
    # LONG
    "L1": {
        "prompt": "Create a roof repair/replacement analysis and HOA approval package for 12133 Tribune Street, Fairfax, VA (Centerpointe townhome community).\n\nSECTION 1 - COMPANY RANKINGS\nRank all roofing contractors from best to worst considering total value. For each company include: company name, license number, contact info, scope of work, materials, warranty length, and exact price. Evaluate how each proposal handles the shared townhome roof line — can the work be isolated to just my unit without affecting neighbors?\n\nSECTION 2 - REPAIR vs REPLACEMENT\nCompare the repair-only proposals (patching, caulking, flashing) against full roof replacement options. Include a cost/benefit breakdown: upfront cost, expected lifespan, risk of future leaks, and long-term cost per year.\n\nSECTION 3 - NEIGHBOR COORDINATION\nSince this is a townhome with shared roof sections:\n- Explain how each contractor could isolate their work at the property boundary between units\n- Provide a quote framework for neighbors who want to join\n- Draft a neighbor outreach letter explaining the project and inviting participation\n\nSECTION 4 - HOA SUBMISSION CHECKLIST\nBased on the Centerpointe Exterior Modification Application:\n- List every required item for ARB submission\n- Pre-fill what we already know (address, description of work, materials, colors, contractor info)\n- Note what still needs to be gathered (neighbor signatures, start date, etc.)\n\nSECTION 5 - RECOMMENDED PATH FORWARD\nGive a clear recommendation: which contractor, which scope (repair or replace), and why.\n\nUse only facts from the source documents. Include exact dollar amounts, license numbers, warranty terms, and company contact details.",
        "expected_facts": ["12,800", "15,704", "10,595", "16,114", "20,996", "2,289", "2,850"],
        "expected_entities": ["all day roofing", "virginia roofing", "brax roofing", "american home"],
        "sections": 5,
        "quality_markers": ["parapet", "neighbor", "arb", "license", "warranty", "draft"],
    },
    "L2": {
        "prompt": "Create a comprehensive home maintenance plan for 12133 Tribune Street based on all inspection findings, contractor proposals, and completed work.\n\nSECTION 1 - COMPLETED WORK\nList all maintenance work that has already been done (invoices/receipts), with dates, contractors, costs, and what was fixed.\n\nSECTION 2 - PENDING ISSUES\nFrom the inspection reports, list every issue that still needs attention. Categorize by urgency.\n\nSECTION 3 - ACTIVE PROPOSALS\nList all contractor proposals that haven't been accepted yet, with prices and what they would fix.\n\nSECTION 4 - BUDGET SUMMARY\nTotal spent so far, total quoted for pending work, and recommended priority order.\n\nUse only facts from the source documents.",
        "expected_facts": ["dryer vent", "reddick", "2,300", "12,800"],
        "expected_entities": ["dryer vent", "reddick", "all day roofing", "american home"],
        "sections": 4,
        "quality_markers": ["inspection", "invoice", "proposal", "budget"],
    },
    "L3": {
        "prompt": "Create a complete property ownership reference document for 12133 Tribune Street, Fairfax, VA.\n\nSECTION 1 - PROPERTY DETAILS\nAddress, purchase price, closing date, loan details (lender, loan number, rate, monthly payment), property tax info.\n\nSECTION 2 - HOA INFORMATION\nBoth associations, monthly fees, management company contact, key rules about exterior modifications.\n\nSECTION 3 - INSURANCE\nCarrier, policy number, coverage amounts, what's covered, annual premium.\n\nSECTION 4 - KEY CONTACTS\nMortgage servicer, HOA management, insurance agent, utility providers, and all contractors used.\n\nSECTION 5 - IMPORTANT DATES\nClosing date, first payment due, HOA registration expiration, insurance renewal, any warranty expiration dates.\n\nUse only facts from the source documents.",
        "expected_facts": ["850,000", "ZG001260233006", "173.13", "5,047"],
        "expected_entities": ["zillow", "onity", "usaa", "centerpointe", "national realty", "dominion"],
        "sections": 5,
        "quality_markers": ["loan", "mortgage", "insurance", "hoa", "closing"],
    },
}

FAKE_INDICATORS = ["northstar", "best roofers", "affordable roofing", "roof toppers", "j&j roofing", "premier roofing", "elite roof"]

MODELS = [
    ("amazon.nova-pro-v1:0", "Nova Pro"),
    ("meta.llama4-maverick-17b-instruct-v1:0", "Llama 4 Maverick"),
    ("meta.llama3-3-70b-instruct-v1:0", "Llama 3.3 70B"),
    ("deepseek.v3.2", "DeepSeek V3.2"),
    ("qwen.qwen3-next-80b-a3b", "Qwen 3 Next 80B"),
    ("nvidia.nemotron-super-3-120b", "NVIDIA Nemotron 120B"),
    ("mistral.magistral-small-2509", "Mistral Magistral"),
    ("mistral.mistral-large-3-675b-instruct", "Mistral Large 3"),
    ("writer.palmyra-x5-v1:0", "Writer X5"),
    ("zai.glm-5", "Z.AI GLM-5"),
    ("deepseek.r1-v1:0", "DeepSeek R1"),
    ("anthropic.claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("anthropic.claude-haiku-4-5-20251001-v1:0", "Claude Haiku 4.5"),
    ("moonshotai.kimi-k2.5", "Moonshot Kimi K2.5"),
    ("google.gemma-3-27b-it", "Google Gemma 27B"),
]


def score_test(test_id: str, markdown: str) -> dict:
    """Score a test result against expected markers."""
    test = TESTS[test_id]
    ml = markdown.lower()

    # Facts found
    facts_total = len(test["expected_facts"])
    facts_found = sum(1 for f in test["expected_facts"] if f in ml)

    # Entities found
    ent_total = len(test["expected_entities"])
    ent_found = sum(1 for e in test["expected_entities"] if e in ml)

    # Sections
    sec_total = test["sections"]
    sec_found = 0
    if sec_total > 0:
        for i in range(1, sec_total + 1):
            if f"section {i}" in ml or f"## {i}" in ml or f"### {i}" in ml:
                sec_found += 1

    # Quality markers
    qual_total = len(test["quality_markers"])
    qual_found = sum(1 for q in test["quality_markers"] if q in ml)

    # Hallucination
    halluc = any(f in ml for f in FAKE_INDICATORS)

    # Composite score
    facts_pct = facts_found / max(facts_total, 1)
    ent_pct = ent_found / max(ent_total, 1) if ent_total > 0 else 1.0
    sec_pct = sec_found / max(sec_total, 1) if sec_total > 0 else 1.0
    qual_pct = qual_found / max(qual_total, 1)

    raw = (facts_pct * 0.25 + ent_pct * 0.25 + sec_pct * 0.20 + qual_pct * 0.15 + (0.15 if not halluc else 0)) * 10
    if halluc:
        raw = min(raw, 5.0)

    return {
        "facts": f"{facts_found}/{facts_total}",
        "entities": f"{ent_found}/{ent_total}" if ent_total > 0 else "—",
        "sections": f"{sec_found}/{sec_total}" if sec_total > 0 else "—",
        "quality": f"{qual_found}/{qual_total}",
        "halluc": halluc,
        "score": round(raw, 1),
    }


def run_test(model_id: str, prompt: str) -> tuple:
    """Run a single test, return (elapsed, markdown, error)."""
    start = time.time()
    proc = subprocess.run(
        ["curl", "-sk", "-N", "-X", "POST", f"{API}/tasks/generate",
         "-H", "Content-Type: application/json", "--max-time", "600",
         "-d", json.dumps({"prompt": prompt, "document_ids": [], "history": []})],
        capture_output=True, text=True)
    elapsed = time.time() - start
    markdown = ""
    error = ""
    for line in proc.stdout.split("\n"):
        if line.startswith("data: "):
            try:
                d = json.loads(line[6:])
                if "result" in d:
                    markdown = d["result"]["markdown"]
                elif "error" in d:
                    error = d["error"][:150]
            except:
                pass
    return elapsed, markdown, error


def main():
    """Run full test series and output results markdown."""
    print("Task Pipeline Test Series Runner")
    print("=" * 60)

    all_results = {}  # model -> {test_id -> score_dict}

    for model_id, model_name in MODELS:
        print(f"\n{'='*60}")
        print(f"Model: {model_name}")
        print(f"{'='*60}")

        # Set model for both strategies
        subprocess.run(["curl", "-sk", "-X", "PUT", f"{API}/admin/config",
                        "-H", "Content-Type: application/json",
                        "-d", json.dumps({"BEDROCK_TASK_SINGLE_MODEL_ID": model_id,
                                         "BEDROCK_TASK_MULTI_MODEL_ID": model_id})],
                       capture_output=True)
        time.sleep(2)

        model_results = {}
        for test_id in sorted(TESTS.keys()):
            test = TESTS[test_id]
            print(f"  {test_id}...", end=" ", flush=True)
            elapsed, md, error = run_test(model_id, test["prompt"])
            if error:
                print(f"ERROR ({elapsed:.0f}s)")
                model_results[test_id] = {"score": 0, "time": elapsed, "error": error[:40]}
            else:
                s = score_test(test_id, md)
                s["time"] = elapsed
                model_results[test_id] = s
                print(f"{s['score']}/10 ({elapsed:.0f}s)")

        all_results[model_name] = model_results

    # Restore defaults
    subprocess.run(["curl", "-sk", "-X", "PUT", f"{API}/admin/config",
                    "-H", "Content-Type: application/json",
                    "-d", json.dumps({"BEDROCK_TASK_SINGLE_MODEL_ID": "amazon.nova-pro-v1:0",
                                     "BEDROCK_TASK_MULTI_MODEL_ID": "mistral.magistral-small-2509"})],
                   capture_output=True)

    # Generate results markdown
    output_path = os.path.join(os.path.dirname(__file__), "..", "results", f"full_suite_{time.strftime("%Y-%m-%d")}.md")
    with open(output_path, "w") as f:
        f.write("# Task Pipeline Test Results\n\n")
        f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M')}\n\n")

        # Summary table
        f.write("## Summary (Average Score per Model)\n\n")
        f.write("| # | Model | Avg | Short | Medium | Long | Total Time |\n")
        f.write("|---|-------|-----|-------|--------|------|------------|\n")

        summaries = []
        for model_name, results in all_results.items():
            short = [r["score"] for tid, r in results.items() if tid.startswith("S") and "error" not in r]
            medium = [r["score"] for tid, r in results.items() if tid.startswith("M") and "error" not in r]
            long = [r["score"] for tid, r in results.items() if tid.startswith("L") and "error" not in r]
            all_scores = short + medium + long
            avg = sum(all_scores) / len(all_scores) if all_scores else 0
            total_time = sum(r.get("time", 0) for r in results.values())
            summaries.append((avg, model_name, short, medium, long, total_time))

        for i, (avg, name, short, medium, long, total_time) in enumerate(sorted(summaries, reverse=True), 1):
            s_avg = f"{sum(short)/len(short):.1f}" if short else "—"
            m_avg = f"{sum(medium)/len(medium):.1f}" if medium else "—"
            l_avg = f"{sum(long)/len(long):.1f}" if long else "—"
            f.write(f"| {i} | {name} | {avg:.1f} | {s_avg} | {m_avg} | {l_avg} | {total_time:.0f}s |\n")

        # Detailed results per test
        f.write("\n## Detailed Results\n\n")
        for test_id in sorted(TESTS.keys()):
            category = {"S": "Short", "M": "Medium", "L": "Long"}[test_id[0]]
            f.write(f"### {test_id} ({category})\n\n")
            f.write(f"**Prompt:** {TESTS[test_id]['prompt'][:100]}...\n\n")
            f.write("| Model | Score | Facts | Entities | Sections | Quality | Halluc | Time |\n")
            f.write("|-------|-------|-------|----------|----------|---------|--------|------|\n")
            rows = []
            for model_name, results in all_results.items():
                r = results.get(test_id, {})
                if "error" in r:
                    rows.append((0, f"| {model_name} | ERR | — | — | — | — | — | {r.get('time',0):.0f}s |"))
                else:
                    rows.append((r.get("score", 0),
                                f"| {model_name} | {r['score']} | {r['facts']} | {r['entities']} | {r['sections']} | {r['quality']} | {'⚠️' if r['halluc'] else '✅'} | {r['time']:.0f}s |"))
            for _, row in sorted(rows, reverse=True):
                f.write(row + "\n")
            f.write("\n")

    print(f"\n\nResults written to: {output_path}")


if __name__ == "__main__":
    main()
