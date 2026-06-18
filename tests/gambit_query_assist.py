"""
Query Assist Gambit: Find best (decomposition model × answer model) combination
for the "outside work" question.

Ground truth: 9 items we know exist from manual inspection
- 1. Damaged siding (exterior back, roofdeck)
- 2. Seal siding penetrations
- 3. Lifted Z-flashings (front siding)
- 4. Rusted/corroded patio safety rails
- 5. Loose deck hand/safety rail (safety concern)
- 6. Missing hurricane ties (deck beam and joists)
- 7. Garage door doesn't reverse (safety concern)
- 8. Rotted trim / moisture damage / cracked caulk
- 9. Drainage/grading improvement needed

Scoring: how many of the 9 ground truth items appear in the answer (keyword match)
"""
import boto3, requests, json, re, time, urllib3
from itertools import product
urllib3.disable_warnings()

client = boto3.client("bedrock-runtime", region_name="us-east-1")
API = "https://api.localhost"
QUESTION = "What outside work requires completion taking into account that we are currently working on the roof"

GROUND_TRUTH = [
    ("damaged siding", ["damaged siding", "siding damage", "siding repair"]),
    ("seal siding penetrations", ["seal siding", "siding penetration", "duct seal"]),
    ("lifted Z-flashings", ["z flashing", "z-flashing", "lifted flashing"]),
    ("rusted patio rails", ["rust", "corrod", "patio rail"]),
    ("loose deck rail", ["loose", "hand.*rail", "safety rail.*deck"]),
    ("hurricane ties", ["hurricane tie", "hurricane strap", "deck.*joist.*connection"]),
    ("garage door safety", ["garage door", "does not reverse", "reverses"]),
    ("rotted trim/caulk", ["rotted trim", "trim rot", "cracked caulk", "peeling"]),
    ("drainage/grading", ["drainage", "grading", "downspout", "storm water"]),
]

DECOMP_MODELS = [
    "amazon.nova-micro-v1:0",
    "amazon.nova-lite-v1:0",
    "amazon.nova-pro-v1:0",
    "meta.llama3-8b-instruct-v1:0",
]

ANSWER_MODELS = [
    "nvidia.nemotron-super-3-120b",
    "amazon.nova-pro-v1:0",
    "qwen.qwen3-32b-v1:0",
    "deepseek.v3.2",
    "mistral.magistral-small-2509",
]

DECOMP_PROMPT = (
    "Generate 8 specific search queries to find '{intent}' in a property document database. "
    "Each query must target a DIFFERENT physical area or system. "
    "Be specific — use technical terms from inspection reports and contractor documents. "
    "Cover: roofing, siding, structural, deck/porch, safety, drainage, mechanical, exterior finishes. "
    "Return ONLY a JSON array of 8 strings."
)

def get_intent():
    resp = client.converse(
        modelId="amazon.nova-micro-v1:0",
        messages=[{"role": "user", "content": [{"text":
            f"Extract the PRIMARY retrieval goal from this question, ignoring context clauses.\n"
            f"Question: \"{QUESTION}\"\n"
            f"Return ONLY 3-6 words describing what to find."
        }]}],
        inferenceConfig={"maxTokens": 30},
    )
    return resp["output"]["message"]["content"][0]["text"].strip()

def decompose(model_id, intent):
    try:
        resp = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": DECOMP_PROMPT.format(intent=intent)}]}],
            inferenceConfig={"maxTokens": 400},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        match = re.search(r"\[.*\]", text, re.DOTALL)
        return json.loads(match.group()) if match else [QUESTION]
    except Exception as e:
        return [f"ERROR: {e}"]

def multi_search(queries):
    all_chunks = {}
    for q in queries:
        r = requests.post(f"{API}/search", json={"query": q, "mode": "hybrid", "page": 1, "page_size": 5}, verify=False)
        for res in r.json().get("results", []):
            key = res["chunk_id"]
            if key not in all_chunks or res["score"] > all_chunks[key]["score"]:
                all_chunks[key] = res
    top = sorted(all_chunks.values(), key=lambda r: r["score"], reverse=True)[:20]
    return all_chunks, "\n\n---\n\n".join(
        f"[{r['title']}]\n{r['snippet'].replace('<em>','').replace('</em>','')}" for r in top
    )

def answer(model_id, context):
    try:
        resolved = model_id
        try:
            resp = client.converse(
                modelId=resolved,
                system=[{"text": (
                    "You answer questions using ONLY the provided document excerpts. "
                    "List every exterior/outside work item found. For each: state problem, location, fix. "
                    "Mark items covered by current roof work. Do not invent information."
                )}],
                messages=[{"role": "user", "content": [{"text": f"{context}\n\n---\n\nQuestion: {QUESTION}"}]}],
                inferenceConfig={"maxTokens": 2500},
            )
        except Exception:
            resolved = f"us.{model_id}"
            resp = client.converse(
                modelId=resolved,
                system=[{"text": (
                    "You answer questions using ONLY the provided document excerpts. "
                    "List every exterior/outside work item found. For each: state problem, location, fix. "
                    "Mark items covered by current roof work. Do not invent information."
                )}],
                messages=[{"role": "user", "content": [{"text": f"{context}\n\n---\n\nQuestion: {QUESTION}"}]}],
                inferenceConfig={"maxTokens": 2500},
            )
        return resp["output"]["message"]["content"][0]["text"]
    except Exception as e:
        return f"ERROR: {e}"

def score(answer_text):
    found = []
    text = answer_text.lower()
    for name, patterns in GROUND_TRUTH:
        if any(re.search(p, text) for p in patterns):
            found.append(name)
    return len(found), found

def short(model_id):
    return model_id.split(".")[1].split("-")[0] if "." in model_id else model_id[:12]

print("="*70)
print("QUERY ASSIST GAMBIT")
print("="*70)
print(f"Question: {QUESTION}")
print(f"Ground truth: {len(GROUND_TRUTH)} items\n")

intent = get_intent()
print(f"Core intent: {intent}\n")

# Phase 1: Test decomposition models (fixed answer model = Nemotron)
print("PHASE 1: Decomposition Model Comparison")
print("-"*50)
best_decomp = None
best_decomp_queries = None
best_decomp_score = -1

decomp_results = []
for dmodel in DECOMP_MODELS:
    t0 = time.time()
    queries = decompose(dmodel, intent)
    chunks, context = multi_search(queries)
    ans = answer("nvidia.nemotron-super-3-120b", context)
    s, found = score(ans)
    elapsed = time.time() - t0
    decomp_results.append((dmodel, queries, s, found, elapsed, context))
    print(f"  {short(dmodel):12s} | score {s}/{len(GROUND_TRUTH)} | {len(chunks)} chunks | {elapsed:.1f}s")
    if s > best_decomp_score:
        best_decomp_score = s
        best_decomp = dmodel
        best_decomp_queries = queries

print(f"\nBest decomp: {short(best_decomp)} ({best_decomp_score}/{len(GROUND_TRUTH)})")

# Phase 2: Test answer models (fixed decomp = best from Phase 1)
print(f"\nPHASE 2: Answer Model Comparison (using {short(best_decomp)} decomp)")
print("-"*50)
_, context_for_phase2 = multi_search(best_decomp_queries)

answer_results = []
for amodel in ANSWER_MODELS:
    t0 = time.time()
    ans = answer(amodel, context_for_phase2)
    s, found = score(ans)
    elapsed = time.time() - t0
    answer_results.append((amodel, s, found, elapsed, ans))
    print(f"  {short(amodel):12s} | score {s}/{len(GROUND_TRUTH)} | {elapsed:.1f}s | found: {found}")

# Summary
print(f"\n{'='*70}")
print("RESULTS SUMMARY")
print(f"{'='*70}")

print("\nDecomposition models (fixed answer=nemotron):")
for dmodel, _, s, found, elapsed, _ in decomp_results:
    print(f"  {short(dmodel):12s}: {s}/{len(GROUND_TRUTH)} in {elapsed:.1f}s | {found}")

print("\nAnswer models (fixed decomp=best):")
for amodel, s, found, elapsed, _ in answer_results:
    print(f"  {short(amodel):12s}: {s}/{len(GROUND_TRUTH)} in {elapsed:.1f}s | {found}")

best_answer = max(answer_results, key=lambda x: x[1])
print(f"\nBest answer model: {short(best_answer[0])} — {best_answer[1]}/{len(GROUND_TRUTH)} items")
print(f"Best decomp model: {short(best_decomp)} — {best_decomp_score}/{len(GROUND_TRUTH)} items")
