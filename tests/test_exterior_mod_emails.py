"""Generate follow-up emails to each roofer requesting HOA application documentation.

Uses the finalized AHC email as a template/example, then loops alphabetically
through all roofers to produce a tailored email for each based on their specific
proposals and what they've already provided.
"""

import json
import os
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

OUTPUT_DIR = Path(__file__).resolve().parent / "exterior_mod_output" / "emails"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# === Reference: the finalized AHC email as the example ===
EXAMPLE_EMAIL = """Subject: Follow-Up: Documentation Needed for HOA Exterior Modification Application

Hi American Home Contractors Team,

Hope you're doing well.

I've been combing through my documents to make sure I have my p's and q's together in preparation for HOA approval. Following our recent inspection and the proposal you provided, I need some additional documentation for the Exterior Modification Application. I've attached the blank form for your reference.

I already have the product brochures from your proposal, which is great. Could you also provide the following?

1. Description of Proposed Modification
   - Location, nature, shape, height, material, color, type of construction

2. Visual Aids
   - Sketches, photographs, or catalog illustrations of the proposed work on my specific roof

3. Dimensions and Materials List

4. Colors of All Proposed Materials
   - Membrane, flashing, edge metals, etc.

5. Estimated Start Date of Construction

6. Estimated Completion Date

I already have your license information from your proposal (VA License #2705190396, M.H.I.C. #31337-03), but please confirm that it is current.

The original construction spec for the community is 60 mil EPDM in Black (per ARB Standards Exhibit A). However, I trust your recommendation for the roofing system, and I will submit whatever system you propose to the ARB.

Please note that obtaining neighbor signatures is my responsibility, not yours.

Thank you for your assistance. I look forward to your response.

Best regards,
Patrick Flanigan
12133 Tribune Street
Fairfax, VA 22033
[Attachment: Exterior Modification Application Form]"""

# === Roofer details (what we know from their docs) ===
ROOFERS = {
    "All Day Roofing & More LLC": {
        "doc_ids": ["doc_183edbcecb4e"],
        "contact": "Daniel Nannucci, dnannucci@alldayroofingandmore.com, (703) 627-0771",
        "already_have": [
            "Proposal with 3 options (TPO 60mil $12,800 / EPDM 75mil ~$16,000 / RubberGard 90mil $25,946)",
            "Materials list for each option",
        ],
        "missing": [
            "License number not visible in their proposal",
            "No sketches/photographs of proposed work",
            "No colors specified",
            "No start/completion dates",
            "No brochures or similar installation references",
        ],
        "license_info": "Not found in proposal — need to request",
    },
    "American Home Contractors": {
        "doc_ids": ["doc_80126e445665", "doc_aaee35593d06"],
        "contact": "info@amhomeco.com, (301) 209-7000",
        "already_have": [
            "Low-Slope/Flat Roof Replacement Proposal (May 14, 2026) with 3 options ($7,200/$9,600/$17,400)",
            "GAF product brochures/spec sheets",
            "Separate roof repairs estimate ($2,850)",
            "License info: VA #2705190396, M.H.I.C. #31337-03",
        ],
        "missing": [
            "Site-specific sketches/photographs",
            "Colors of all materials",
            "Start and completion dates",
            "Description tailored for the application form",
        ],
        "license_info": "VA License #2705190396, M.H.I.C. #31337-03 (from proposal header)",
    },
    "Brax Roofing": {
        "doc_ids": ["doc_6f864ae384d9", "doc_707cc5dde5df", "doc_e8344600ec2c"],
        "contact": "Quintin, BRAX Roofing (reply to email thread)",
        "already_have": [
            "Detailed PDF quote with 5 roof section specs",
            "Two emails explaining parapet wall recommendation",
            "3 pricing options ($10,595 / $14,220 / $24,350)",
            "License info: MHIC# 109580, Virginia License #2705168455",
            "Warranty details (10yr workmanship + 10yr manufacturer)",
            "Discussion of neighbor coordination for parapet walls",
        ],
        "missing": [
            "Site-specific sketches/drawings (offered to provide for HOA)",
            "Colors of materials (membrane, parapet caps, flashing)",
            "Start and completion dates",
        ],
        "license_info": "MHIC# 109580, Virginia License #2705168455 (from quote PDF)",
    },
    "Virginia Roofing Corporation": {
        "doc_ids": ["doc_57d1c14cee79", "doc_7541b3323728"],
        "contact": "Jose Cruz, josec@varoofing.com, Office 703-751-3200, Cell 571-221-8379",
        "already_have": [
            "Full roof recovery proposal ($15,704) - 60mil Black EPDM",
            "Separate repairs proposal ($2,289)",
            "Contractor License #2705171165",
            "Materials specified (EPDM, base flashing, 24GA drip edge, counter flashing)",
            "Color: Black membrane specified",
        ],
        "missing": [
            "Site-specific sketches/photographs",
            "Colors of flashing and edge metals (ARB requires Medium Bronze aluminum)",
            "Start and completion dates",
            "No brochures or similar installation references",
        ],
        "license_info": "Contractor #2705171165 (from proposal)",
    },
}

# === Prompt template ===
PROMPT_TEMPLATE = """Write a follow-up email from Patrick Flanigan to a roofing contractor requesting documentation needed for an HOA Exterior Modification Application.

USE THIS EMAIL AS THE EXAMPLE for tone, structure, and content:

{example_email}

---

NOW WRITE A SIMILAR EMAIL FOR THIS ROOFER:

Contractor: {roofer_name}
Contact: {contact}
What Patrick already has from them: {already_have}
What is still missing: {missing}
License info status: {license_info}

RULES:
- Follow the same structure and tone as the example
- Start with the "combing through documents" intro
- Acknowledge what they've already provided (be specific to this roofer)
- Only ask for what's actually MISSING — don't ask for things already provided
- Include the ARB original spec note (60 mil EPDM Black) and that Patrick trusts their recommendation
- If license info is already known, mention it and ask to confirm current. If not known, ask for it.
- Neighbor signatures are Patrick's responsibility
- Attach the Exterior Modification Application form
- If this roofer previously offered to help with HOA documentation (like Brax did), reference that
- Keep it concise and natural — a real follow-up email, not a form letter
"""


def generate_email(roofer_name: str, info: dict) -> str:
    prompt = PROMPT_TEMPLATE.format(
        example_email=EXAMPLE_EMAIL,
        roofer_name=roofer_name,
        contact=info["contact"],
        already_have="\n  - ".join(info["already_have"]),
        missing="\n  - ".join(info["missing"]),
        license_info=info["license_info"],
    )
    response = bedrock.converse(
        modelId=MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1200},
    )
    return response["output"]["message"]["content"][0]["text"]


def main():
    print("=" * 70)
    print("GENERATING ROOFER FOLLOW-UP EMAILS")
    print("=" * 70)

    all_emails = {}

    for roofer_name, info in sorted(ROOFERS.items()):
        print(f"\n  [{roofer_name}] Generating...")
        t0 = time.time()
        email = generate_email(roofer_name, info)
        elapsed = time.time() - t0
        print(f"    Done in {elapsed:.1f}s ({len(email)} chars)")

        all_emails[roofer_name] = email

        # Save individual file
        safe_name = roofer_name.replace(" ", "_").replace("&", "and").replace(".", "")
        path = OUTPUT_DIR / f"{safe_name}_email.txt"
        with open(path, "w") as f:
            f.write(email)
        print(f"    Saved: {path.name}")

    # Print all
    print(f"\n{'=' * 70}")
    for name, email in sorted(all_emails.items()):
        print(f"\n{'─' * 70}")
        print(f"TO: {ROOFERS[name]['contact']}")
        print(f"{'─' * 70}")
        print(email)

    # Save combined
    combined_path = OUTPUT_DIR / "all_roofer_emails.json"
    with open(combined_path, "w") as f:
        json.dump(all_emails, f, indent=2)
    print(f"\n\nAll emails saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
