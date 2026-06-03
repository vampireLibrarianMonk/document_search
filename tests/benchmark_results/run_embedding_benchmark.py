"""Embedding model benchmark for hybrid search use case."""
import json
import time
import math
import boto3

client = boto3.client("bedrock-runtime", region_name="us-east-1")

MODELS = [
    {"id": "amazon.titan-embed-text-v2:0", "dim": 1024, "cost": 0.00002, "type": "titan"},
    {"id": "amazon.titan-embed-text-v1", "dim": 1536, "cost": 0.0001, "type": "titan"},
    {"id": "amazon.titan-embed-g1-text-02", "dim": 1536, "cost": 0.0001, "type": "titan"},
    {"id": "amazon.titan-embed-image-v1", "dim": 1024, "cost": 0.0001, "type": "titan-image"},
    {"id": "cohere.embed-english-v3", "dim": 1024, "cost": 0.0001, "type": "cohere-v3"},
    {"id": "cohere.embed-multilingual-v3", "dim": 1024, "cost": 0.0001, "type": "cohere-v3"},
    {"id": "cohere.embed-v4:0", "dim": 1536, "cost": 0.00010, "type": "cohere-v4"},
]

DOCS = [
    "Perimeter barriers including fences shall not exceed six (6) feet in height from finished grade. Materials must be wood, vinyl, or wrought iron.",
    "Annual assessments for the current fiscal year are set at $275.00 per quarter, due January 1, April 1, July 1, and October 1.",
    "The roof covering is approximately 15 years old. Several shingles show signs of curling and granule loss. Recommend evaluation by a qualified roofing contractor within the next 2-3 years.",
    "Real property tax payments are due November 1 and May 1 of each year. Delinquent after December 20 and June 20 respectively.",
    "No outbuilding, storage shed, or accessory structure shall be erected without prior written approval from the Architectural Review Committee. Maximum footprint of 120 square feet.",
    "Coverage A Dwelling: $525,000. Coverage B Other Structures: $52,500. Coverage C Personal Property: $262,500. Annual Premium: $1,847.",
    "Loan Amount: $425,000. Interest Rate: 6.875%. Monthly Principal and Interest: $2,791.53. Closing Date: March 15, 2026.",
    "The HVAC system is a 2019 Carrier heat pump with 5-ton capacity. Filter was dirty at time of inspection. System responded to heating and cooling demand. Estimated remaining useful life: 10-15 years.",
]

QUERIES = [
    ("how tall can my fence be", 0),
    ("quarterly HOA fees", 1),
    ("roof condition", 2),
    ("property tax deadlines", 3),
    ("shed building rules", 4),
    ("home insurance coverage amounts", 5),
    ("mortgage interest rate", 6),
    ("air conditioning inspection", 7),
    ("what materials are allowed for fencing", 0),
    ("when do I pay my neighborhood dues", 1),
    ("shingle damage", 2),
    ("maximum size for outbuildings", 4),
    ("how much dwelling coverage", 5),
    ("monthly payment amount", 6),
    ("heat pump age and condition", 7),
]


def cosine_sim(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def embed(model_id, model_type, text, input_type):
    if model_type == "titan":
        body = {"inputText": text}
    elif model_type == "titan-image":
        body = {"inputText": text}
    elif model_type == "cohere-v3":
        body = {"texts": [text], "input_type": input_type}
    elif model_type == "cohere-v4":
        body = {"texts": [text], "input_type": input_type, "embedding_types": ["float"]}
    else:
        raise ValueError(f"Unknown type: {model_type}")

    start = time.time()
    resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
    latency = time.time() - start
    result = json.loads(resp["body"].read())

    if model_type in ("titan", "titan-image"):
        vec = result["embedding"]
    elif model_type == "cohere-v3":
        vec = result["embeddings"][0]
    elif model_type == "cohere-v4":
        vec = result["embeddings"]["float"][0]
    else:
        vec = result["embedding"]

    return vec, latency


def benchmark_model(model):
    model_id = model["id"]
    model_type = model["type"]
    print(f"\n  Testing {model_id} ({model['dim']}d)...")

    # Embed documents
    doc_vecs = []
    doc_latencies = []
    for doc in DOCS:
        input_type = "search_document" if "cohere" in model_type else None
        vec, lat = embed(model_id, model_type, doc, input_type)
        doc_vecs.append(vec)
        doc_latencies.append(lat)

    # Embed queries and score
    correct_at_1 = 0
    reciprocal_ranks = []
    query_latencies = []
    details = []

    for query_text, expected_idx in QUERIES:
        input_type = "search_query" if "cohere" in model_type else None
        q_vec, lat = embed(model_id, model_type, query_text, input_type)
        query_latencies.append(lat)

        # Rank docs by cosine similarity
        sims = [(i, cosine_sim(q_vec, dv)) for i, dv in enumerate(doc_vecs)]
        sims.sort(key=lambda x: x[1], reverse=True)
        ranked_ids = [s[0] for s in sims]

        rank = ranked_ids.index(expected_idx) + 1
        if rank == 1:
            correct_at_1 += 1
        reciprocal_ranks.append(1.0 / rank)
        details.append((query_text, expected_idx, ranked_ids[0], rank, sims[0][1]))

    accuracy = correct_at_1 / len(QUERIES)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    avg_latency = (sum(doc_latencies) + sum(query_latencies)) / (len(doc_latencies) + len(query_latencies))

    return {
        "model": model_id,
        "dim": model["dim"],
        "cost": model["cost"],
        "accuracy_at_1": accuracy,
        "mrr": mrr,
        "avg_latency_ms": avg_latency * 1000,
        "details": details,
    }


def main():
    print("=" * 80)
    print("EMBEDDING MODEL BENCHMARK - House Document Hybrid Search")
    print("=" * 80)
    print(f"\n  Documents: {len(DOCS)}")
    print(f"  Queries: {len(QUERIES)}")
    print(f"  Models: {len(MODELS)}")

    results = []
    for model in MODELS:
        try:
            r = benchmark_model(model)
            results.append(r)
            print(f"    Accuracy@1: {r['accuracy_at_1']:.1%} | MRR: {r['mrr']:.3f} | Latency: {r['avg_latency_ms']:.0f}ms")
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({
                "model": model["id"],
                "dim": model["dim"],
                "cost": model["cost"],
                "accuracy_at_1": None,
                "mrr": None,
                "avg_latency_ms": None,
                "error": str(e),
                "details": [],
            })

    # Sort by MRR descending (None last)
    results.sort(key=lambda x: x.get("mrr") or 0, reverse=True)

    # Output
    output = []
    output.append("=" * 90)
    output.append("EMBEDDING MODEL BENCHMARK RESULTS - House Document Hybrid Search")
    output.append("=" * 90)
    output.append(f"\nTest setup: {len(DOCS)} document chunks, {len(QUERIES)} queries")
    output.append("Metrics: Accuracy@1 (top result correct), MRR (mean reciprocal rank)")
    output.append("Context: App uses hybrid BM25 + kNN, so embedding quality matters for paraphrase recall\n")

    # Summary table
    output.append("-" * 90)
    output.append(f"{'Model':<38} {'Dim':>4} {'Acc@1':>7} {'MRR':>6} {'Latency':>9} {'Cost/1K':>10}")
    output.append("-" * 90)
    for r in results:
        if r.get("accuracy_at_1") is not None:
            output.append(
                f"{r['model']:<38} {r['dim']:>4} {r['accuracy_at_1']:>6.1%} {r['mrr']:>6.3f} {r['avg_latency_ms']:>7.0f}ms ${r['cost']:.5f}"
            )
        else:
            output.append(f"{r['model']:<38} {r['dim']:>4} {'ERROR':>7} {'':>6} {'':>9} ${r['cost']:.5f}  ({r.get('error','')})")
    output.append("-" * 90)

    # Detailed per-query results
    output.append("\n\nDETAILED PER-QUERY RESULTS")
    output.append("=" * 90)
    for r in results:
        if not r.get("details"):
            continue
        output.append(f"\n{'─' * 90}")
        output.append(f"Model: {r['model']} ({r['dim']}d)")
        output.append(f"{'─' * 90}")
        output.append(f"  {'Query':<45} {'Expected':>3} {'Got':>3} {'Rank':>4} {'Top Score':>9}")
        output.append(f"  {'-'*45} {'---':>3} {'---':>3} {'----':>4} {'---------':>9}")
        for query_text, expected, got, rank, top_score in r["details"]:
            marker = "✓" if rank == 1 else "✗"
            output.append(f"  {query_text:<45} D{expected:>1}   D{got:>1}   {rank:>3}   {top_score:>7.4f} {marker}")

    # Recommendation
    output.append("\n\n" + "=" * 90)
    output.append("ANALYSIS & RECOMMENDATION")
    output.append("=" * 90)
    valid = [r for r in results if r.get("mrr") is not None]
    if valid:
        best = valid[0]
        cheapest_good = min(
            [r for r in valid if r["accuracy_at_1"] >= 0.8],
            key=lambda x: x["cost"],
            default=None,
        )
        output.append(f"\n  Best overall (MRR):  {best['model']} — MRR {best['mrr']:.3f}, Acc@1 {best['accuracy_at_1']:.1%}")
        if cheapest_good:
            output.append(f"  Best value (≥80%):   {cheapest_good['model']} — MRR {cheapest_good['mrr']:.3f}, Cost ${cheapest_good['cost']:.5f}/1K tokens")
        output.append(f"\n  Current default: amazon.titan-embed-text-v2:0 at $0.00002/1K tokens (5x cheaper than alternatives)")

    text = "\n".join(output)
    print("\n" + text)

    with open("/home/flaniganp/PycharmProjects/document_search/tests/benchmark_results/embedding_benchmark.txt", "w") as f:
        f.write(text + "\n")
    print(f"\n  Results saved to tests/benchmark_results/embedding_benchmark.txt")


if __name__ == "__main__":
    main()
