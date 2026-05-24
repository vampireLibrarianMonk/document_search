# Task Pipeline Test Series

Test prompts for evaluating the task workflow across models.
Each prompt is designed to exercise different capabilities at different scales.

## Scoring Criteria (per test)

| Metric | Weight | What it measures |
|--------|--------|-----------------|
| Companies/Entities | 25% | Did it find all relevant parties? |
| Facts/Numbers | 25% | Are specific dollar amounts, dates, license numbers present? |
| Sections/Structure | 20% | Does output follow the requested format? |
| Quality Markers | 15% | Domain-specific insights (parapet walls, ARB, etc.) |
| Ranking Logic | 15% | Does it prioritize correctly per the stated problem? |
| Hallucination | -50% | Instant penalty for fabricated data |

Score = 0-10 scale. Hallucination caps score at 5.0 max.

---

## SHORT PROMPTS (single question, expects concise answer)

### S1 — Simple Lookup
```
What is the monthly HOA fee and who is the management company?
```
**Expected:** $173.13 total ($82.13 + $91.00), National Realty Partners, 703-435-3800
**Tests:** Basic fact retrieval from closing binder

### S2 — Single Entity Extraction
```
What did the home inspection find wrong with the roof?
```
**Expected:** Split seam in membrane, ponding, cracked/deteriorated sealant at flashings
**Tests:** Extracting specific findings from inspection report

### S3 — Price Comparison
```
What is the cheapest roof repair option and what does it include?
```
**Expected:** Virginia Roofing $2,289 — caulking, seam strip, patch, flashing repair, 1-year warranty
**Tests:** Finding minimum price across multiple documents

### S4 — Yes/No with Evidence
```
Does the HOA require neighbor signatures for exterior modifications?
```
**Expected:** Yes, per the Exterior Modification Application form
**Tests:** Binary question with source citation

### S5 — Date Lookup
```
When was the property purchased and for how much?
```
**Expected:** April 2, 2026 closing date, $850,000
**Tests:** Cross-referencing closing disclosure and appraisal

---

## MEDIUM PROMPTS (multi-part analysis, 2-3 sections)

### M1 — Comparison Table
```
Create a comparison table of all roof replacement options. Include company name, material type, warranty length, and price for each option. Note which ones can be done without neighbor involvement.
```
**Expected:** 4 companies, 7+ price points, parapet wall mention for Brax
**Tests:** Multi-document synthesis into structured format

### M2 — Financial Summary
```
Summarize all monthly and recurring costs for this property: mortgage payment, HOA fees, insurance, and any other regular expenses. Include the total monthly cost.
```
**Expected:** Mortgage ~$5,047.85, HOA $173.13, insurance details from USAA policy
**Tests:** Cross-category document synthesis (Account Statements + Insurance + Tax & Legal)

### M3 — Timeline Construction
```
Create a timeline of all events related to this property from earliest to most recent. Include purchase, inspections, insurance, and any maintenance work.
```
**Expected:** Chronological ordering of closing (Apr 2026), inspection (Apr 6), insurance (Apr 2), estimates (Apr-May)
**Tests:** Date extraction and ordering across many documents

### M4 — Vendor Contact Sheet
```
List every contractor, vendor, and service provider mentioned in my documents with their contact information (phone, email, address, license number).
```
**Expected:** All Day Roofing, Virginia Roofing, Brax, American Home Contractors, Dryer Vent Guys, Reddick & Sons, Eruda, USAA, Dominion Energy, etc.
**Tests:** Entity extraction across ALL document categories

### M5 — Insurance Coverage Summary
```
What does my homeowners insurance cover? Include coverage amounts, deductibles, and what is specifically excluded. Who is the carrier and what is the policy number?
```
**Expected:** USAA policy details, replacement cost, coverage confirmation amounts
**Tests:** Insurance category document synthesis

---

## LONG PROMPTS (multi-section deliverable, complex analysis)

### L1 — Roof Analysis (our benchmark)
```
Create a roof repair/replacement analysis and HOA approval package for 12133 Tribune Street, Fairfax, VA (Centerpointe townhome community).

SECTION 1 - COMPANY RANKINGS
Rank all roofing contractors from best to worst considering total value. For each company include: company name, license number, contact info, scope of work, materials, warranty length, and exact price. Evaluate how each proposal handles the shared townhome roof line — can the work be isolated to just my unit without affecting neighbors?

SECTION 2 - REPAIR vs REPLACEMENT
Compare the repair-only proposals (patching, caulking, flashing) against full roof replacement options. Include a cost/benefit breakdown: upfront cost, expected lifespan, risk of future leaks, and long-term cost per year.

SECTION 3 - NEIGHBOR COORDINATION
Since this is a townhome with shared roof sections:
- Explain how each contractor could isolate their work at the property boundary between units
- Provide a quote framework for neighbors who want to join (estimated per-unit savings for 2, 3, or 4 units combined)
- Draft a neighbor outreach letter explaining the project and inviting participation

SECTION 4 - HOA SUBMISSION CHECKLIST
Based on the Centerpointe Exterior Modification Application:
- List every required item for ARB submission
- Pre-fill what we already know (address, description of work, materials, colors, contractor info)
- Note what still needs to be gathered (neighbor signatures, start date, etc.)

SECTION 5 - RECOMMENDED PATH FORWARD
Give a clear recommendation: which contractor, which scope (repair or replace), and why. Factor in HOA compliance, neighbor impact, warranty, and total cost of ownership.

Use only facts from the source documents. Include exact dollar amounts, license numbers, warranty terms, and company contact details.
```
**Expected:** 4 companies, 7+ prices, 5 sections, parapet walls, ARB reference, draft letter, Brax ranked high
**Tests:** Full structured pipeline, multi-document, complex reasoning

### L2 — Home Maintenance Master Plan
```
Create a comprehensive home maintenance plan for 12133 Tribune Street based on all inspection findings, contractor proposals, and completed work.

SECTION 1 - COMPLETED WORK
List all maintenance work that has already been done (invoices/receipts), with dates, contractors, costs, and what was fixed.

SECTION 2 - PENDING ISSUES
From the inspection reports, list every issue that still needs attention. Categorize by urgency (immediate, within 6 months, within 1 year).

SECTION 3 - ACTIVE PROPOSALS
List all contractor proposals that haven't been accepted yet, with prices and what they would fix.

SECTION 4 - BUDGET SUMMARY
Total spent so far, total quoted for pending work, and recommended priority order based on urgency and cost.

Use only facts from the source documents.
```
**Expected:** Dryer vent work (completed), HVAC invoices, roof proposals (pending), inspection issues categorized
**Tests:** Cross-category synthesis, temporal reasoning (done vs pending)

### L3 — Property Ownership Dossier
```
Create a complete property ownership reference document for 12133 Tribune Street, Fairfax, VA.

SECTION 1 - PROPERTY DETAILS
Address, purchase price, closing date, loan details (lender, loan number, rate, monthly payment), property tax info.

SECTION 2 - HOA INFORMATION
Both associations (Master + Homeowners), monthly fees, management company contact, key rules about exterior modifications.

SECTION 3 - INSURANCE
Carrier, policy number, coverage amounts, what's covered, annual premium.

SECTION 4 - KEY CONTACTS
Mortgage servicer, HOA management, insurance agent, utility providers, and all contractors used.

SECTION 5 - IMPORTANT DATES
Closing date, first payment due, HOA registration expiration, insurance renewal, any warranty expiration dates.

Use only facts from the source documents.
```
**Expected:** Zillow Home Loans/Onity, loan #ZG001260233006, USAA, both HOA associations, all utility contacts from closing binder
**Tests:** Comprehensive cross-category extraction, maximum document coverage

---

## Test Execution Notes

- Each prompt is run with `document_ids: []` (auto-search finds relevant docs)
- Models are tested as both single-pass and structured pipeline
- Results are scored automatically + spot-checked for hallucination
- 3 runs per model for consistency scoring (min/max/avg reported)
