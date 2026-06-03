"""Exterior Modification Application - Completeness Analysis

Uses the app's search/document APIs AND direct Bedrock calls to:
1. Parse the application form requirements
2. Gather ALL relevant docs per roofer
3. Cross-reference with ARB Standards for approved materials/colors
4. Produce a gap analysis showing what's missing for a complete submission
5. Generate a submission-ready writeup for each viable roofer option

Output: PlantUML diagram of the workflow + per-roofer gap/readiness report
"""

import json
import os
import sys
import time
from pathlib import Path

import boto3
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API = "https://api.localhost"
VERIFY = False
REGION = os.getenv("AWS_REGION", "us-east-1")
bedrock = boto3.client("bedrock-runtime", region_name=REGION)
MODEL = "amazon.nova-pro-v1:0"

OUTPUT_DIR = Path(__file__).resolve().parent / "exterior_mod_output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# === Document IDs ===
EXTERIOR_MOD_APP = "doc_38cebc657b28"
ARB_STANDARDS = "doc_26da506329b6"

ROOFERS = {
    "All Day Roofing & More LLC": {
        "doc_ids": ["doc_183edbcecb4e"],
        "estimates": [
            {"name": "Option 1 - TPO 60mil (15-20yr warranty)", "price": "$12,800"},
            {"name": "Option 2 - EPDM 75mil (20-30yr warranty)", "price": "~$16,000"},
            {"name": "Option 3 - RubberGard 90mil (30-50yr warranty)", "price": "$25,946"},
        ],
    },
    "American Home Contractors": {
        "doc_ids": ["doc_80126e445665", "doc_aaee35593d06"],
        "estimates": [
            {"name": "Roof repairs only", "price": "$2,850"},
            {"name": "GAF LIBERTY SBS 2-ply self-adhered (15yr warranty)", "price": "$7,200"},
            {"name": "GAF RUBEROID Torch granule membrane", "price": "$9,600"},
            {"name": "GAF Everguard TPO system", "price": "$17,400"},
        ],
    },
    "Brax Roofing": {
        "doc_ids": ["doc_6f864ae384d9", "doc_707cc5dde5df", "doc_e8344600ec2c"],
        "estimates": [
            {"name": "TPO roof replacement (no parapet walls)", "price": "$10,595"},
            {"name": "TPO roof + parapet walls (recommended)", "price": "$14,220"},
            {"name": "Full 3-home roof replacement", "price": "$24,350"},
        ],
    },
    "Virginia Roofing Corporation": {
        "doc_ids": ["doc_57d1c14cee79", "doc_7541b3323728"],
        "estimates": [
            {"name": "Full EPDM roof recovery (main roof)", "price": "$15,704"},
            {"name": "Roof repairs only (caulking, flashing, patches)", "price": "$2,289"},
        ],
    },
}

# === ARB-Approved Roof Specs (from doc_26da506329b6 Exhibit A) ===
ARB_ROOF_SPECS = """
CENTERPOINTE ARB APPROVED FLAT ROOF SPECIFICATIONS (Exhibit A):
- Flat Roof: 60 mil EPDM (per subcontractor), Color: Black
- Flat Roof Terrace: 60 mil vinyl flooring, Duradek Ultra Surcoseal "Suede"
- Flashing: Aluminum, Petersen or eq., Color: Medium Bronze
- Metal Roof: Aluminum, Petersen or eq., Color: Medium Bronze
- Metal Parapet Caps: Aluminum, Petersen or eq., Color: "Sandstone" or "Military Blue"
- Asphalt Shingles: Fiberglass 30yr, Certain Teed "Landmark", Color: Colonial State
- Notes to contractor: Color of metal parapet cap to match parapet wall.
  Refer to architectural plans, scope of work, strip elevation plans,
  ridge vents are to be concealed.
- Original supplier: Brown Roofing, 703-335-5244
"""

# === Form Requirements ===
FORM_REQUIREMENTS = """
REQUIRED SUBMISSIONS (Directions section of application):
1. Plat Plan (survey) of your lot, with location of proposed modification marked
2. Sketches, Photographs, catalog illustrations
3. Dimensions and materials for the proposed modification
4. Colors of proposed modification
5. Signatures from all adjacent neighbors

FORM FIELDS:
- Name, Phone, Email, Property Address, Community Name, Lot
- Description of Proposed Modification
- ESTIMATED STARTING DATE OF CONSTRUCTION
- ESTIMATED COMPLETION DATE
- Neighbors' Acknowledgments (signatures of adjacent lot owners)
- Owner/Applicant Signature + Date

ADDITIONAL REQUIREMENTS (from ARB Procedures):
- Complete plans and specs showing location, nature, shape, height, material, color, type of construction
- Brochures or addresses where similar installations exist (suggested)
- Must contact Miss Utility of Virginia at 1-800-552-7001
- Homeowner responsible for building permits and governmental approvals
- Work must commence within 6 months of approval, complete within 12 months
- Upon completion, notify management for ARB inspection → Certificate of Compliance
"""


def get_chunks(doc_id: str) -> str:
    resp = requests.get(f"{API}/documents/{doc_id}/chunks", verify=VERIFY)
    resp.raise_for_status()
    data = resp.json()
    return "\n".join(c.get("content", "") for c in data.get("chunks", []))


def search(query: str, doc_ids: list[str] | None = None, limit: int = 5) -> list[dict]:
    payload = {"query": query, "limit": limit}
    if doc_ids:
        payload["document_ids"] = doc_ids
    resp = requests.post(f"{API}/search", json=payload, verify=VERIFY)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", data) if isinstance(data, dict) else data


def call_bedrock(prompt: str, max_tokens: int = 4000) -> str:
    response = bedrock.converse(
        modelId=MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens},
    )
    return response["output"]["message"]["content"][0]["text"]


def main():
    print("=" * 70)
    print("EXTERIOR MODIFICATION APPLICATION - COMPLETENESS ANALYSIS")
    print("=" * 70)

    # Step 1: Gather form + ARB specs
    print("\n[1] Loading application form and ARB standards...")
    form_text = get_chunks(EXTERIOR_MOD_APP)
    arb_text = get_chunks(ARB_STANDARDS)
    print(f"    Form: {len(form_text)} chars | ARB Standards: {len(arb_text)} chars")

    # Step 2: For each roofer, do a detailed compliance check
    all_analyses = {}

    for roofer_name, info in sorted(ROOFERS.items()):
        print(f"\n{'─' * 70}")
        print(f"[ROOFER] {roofer_name}")
        print(f"{'─' * 70}")

        # Gather content
        roofer_content = ""
        for doc_id in info["doc_ids"]:
            roofer_content += get_chunks(doc_id) + "\n"
        print(f"  Documents: {len(info['doc_ids'])}, {len(roofer_content)} chars total")

        # For each estimate, check ARB compliance + form completeness
        estimate_analyses = []
        for est in info["estimates"]:
            print(f"\n  Analyzing: {est['name']} ({est['price']})...")

            prompt = f"""You are helping a homeowner prepare an HOA Exterior Modification Application.

TASK: Analyze whether this contractor's estimate/option is COMPLIANT with the ARB-approved specifications,
and determine what's MISSING for a complete application submission.

{ARB_ROOF_SPECS}

{FORM_REQUIREMENTS}

CONTRACTOR: {roofer_name}
SELECTED OPTION: {est['name']} at {est['price']}

CONTRACTOR DOCUMENTS (excerpts):
{roofer_content[:6000]}

Produce a structured analysis with these sections:

## ARB COMPLIANCE CHECK
For each ARB spec requirement, state whether this option MEETS, PARTIALLY MEETS, CONFLICTS, or is UNKNOWN:
- Membrane type & thickness (ARB requires: 60 mil EPDM, Black)
- Flashing material & color (ARB requires: Aluminum, Medium Bronze)
- Parapet caps material & color (ARB requires: Aluminum, "Sandstone" or "Military Blue")
- Ridge vents concealed
- Any conflicts or deviations

## FORM COMPLETENESS
For each required submission item, state HAVE / MISSING / PARTIAL:
1. Plat Plan with modification location marked
2. Sketches/Photographs/Catalog illustrations
3. Dimensions and materials
4. Colors specified
5. Neighbor signatures
6. Estimated start date
7. Estimated completion date
8. Contractor license info

## ACTION ITEMS
Numbered list of specific things the homeowner must do/get to complete the submission for THIS option.
Include whether they need to ask the contractor to change materials to comply with ARB specs.

## VIABILITY RATING
Rate this option: READY / NEARLY READY / NEEDS WORK / NOT VIABLE
With one sentence explanation.
"""
            analysis = call_bedrock(prompt, max_tokens=2500)
            print(f"    ✓ Analysis complete ({len(analysis)} chars)")
            estimate_analyses.append({
                "name": est["name"],
                "price": est["price"],
                "analysis": analysis,
            })

        all_analyses[roofer_name] = {
            "doc_ids": info["doc_ids"],
            "estimates": estimate_analyses,
        }

    # Step 3: Generate the PlantUML diagram
    print(f"\n{'=' * 70}")
    print("[DIAGRAM] Generating PlantUML workflow...")
    puml = generate_plantuml(all_analyses)
    puml_path = OUTPUT_DIR / "exterior_mod_workflow.puml"
    with open(puml_path, "w") as f:
        f.write(puml)
    print(f"  Saved: {puml_path}")

    # Step 4: Save full report
    report = generate_report(all_analyses)
    report_path = OUTPUT_DIR / "completeness_report.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"  Saved: {report_path}")

    # Save raw JSON
    json_path = OUTPUT_DIR / "completeness_analysis.json"
    with open(json_path, "w") as f:
        json.dump(all_analyses, f, indent=2)
    print(f"  Saved: {json_path}")

    print(f"\n{'=' * 70}")
    print("DONE")
    print(f"{'=' * 70}")


def generate_plantuml(analyses: dict) -> str:
    """Generate a PlantUML activity diagram showing the submission workflow."""
    roofer_notes = []
    for name, data in sorted(analyses.items()):
        options = []
        for est in data["estimates"]:
            # Extract viability from analysis text
            viability = "?"
            for line in est["analysis"].split("\n"):
                if "READY" in line.upper() or "VIABLE" in line.upper():
                    if "NOT VIABLE" in line.upper():
                        viability = "NOT VIABLE"
                    elif "NEARLY READY" in line.upper():
                        viability = "NEARLY READY"
                    elif "NEEDS WORK" in line.upper():
                        viability = "NEEDS WORK"
                    elif "READY" in line.upper():
                        viability = "READY"
                    break
            options.append(f"    * {est['name']} ({est['price']}) - **{viability}**")
        roofer_notes.append(f"  card \"{name}\" as {name.split()[0].lower()} {{\n" + "\n".join(options) + "\n  }")

    return f"""@startuml exterior_mod_workflow
!theme plain
title Exterior Modification Application - Roof Replacement Workflow

|Homeowner|
start
:Gather roofer proposals\\n(4 companies, 9 estimates);

|App - Document Search|
:Search indexed documents;
:Retrieve form requirements\\n(doc_38cebc657b28);
:Retrieve ARB Standards\\n(doc_26da506329b6);
:Cross-reference materials\\nvs ARB-approved specs;

|Bedrock AI|
:Analyze each estimate\\nfor ARB compliance;
:Identify gaps in\\nsubmission requirements;
:Generate per-option\\nwriteups for form;

|Homeowner|
:Review compliance report;

if (Materials comply with ARB specs?) then (yes)
  :Proceed with submission;
else (no)
  :Contact contractor to\\nrequest ARB-compliant materials;
  note right
    ARB requires:
    * 60 mil EPDM, Black
    * Aluminum flashing, Medium Bronze
    * Parapet caps: Sandstone/Military Blue
  end note
endif

:Gather missing items;
note right
  Common gaps:
  * Plat plan with roof marked
  * Photos of current roof
  * Neighbor signatures
  * Start/completion dates
  * Miss Utility call
end note

:Complete application form;
:Submit to National Realty Partners\\n(Theoharis Management);

|ARB|
:Review (up to 60 days);

if (Approved?) then (yes)
  :Begin work within 6 months;
  :Complete within 12 months;
  :Request final inspection;
  :Receive Certificate of Compliance;
else (no)
  :Address feedback;
  :Resubmit;
endif

stop

legend right
  |= Roofer |= Best Option |= ARB Compliant? |
  | All Day Roofing | EPDM 75mil | Partial (needs Black confirmation) |
  | American Home | Repairs only | N/A (minor repair) |
  | Brax Roofing | TPO + parapet walls | **CONFLICTS** (TPO ≠ EPDM) |
  | Virginia Roofing | EPDM recovery | **BEST MATCH** (60mil EPDM Black) |
endlegend

@enduml
"""


def generate_report(analyses: dict) -> str:
    """Generate the markdown completeness report."""
    lines = [
        "# Exterior Modification Application - Completeness Report",
        f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n## ARB-Approved Roof Specifications (from Centerpointe Standards)",
        f"\n{ARB_ROOF_SPECS}",
        f"\n## Form Requirements",
        f"\n{FORM_REQUIREMENTS}",
        "\n---\n",
    ]

    for name, data in sorted(analyses.items()):
        lines.append(f"\n# {name}")
        lines.append(f"\nDocuments: {', '.join(data['doc_ids'])}")
        for est in data["estimates"]:
            lines.append(f"\n## {est['name']} — {est['price']}")
            lines.append(f"\n{est['analysis']}")
            lines.append("\n---\n")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
