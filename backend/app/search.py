"""OpenSearch integration for chunk indexing and hybrid search.

Indexes document chunks into OpenSearch with both full-text (BM25) and
vector (kNN) fields, enabling hybrid search that combines lexical and
semantic matching for better recall.
"""

from __future__ import annotations

import json
import logging
import os

import boto3
from botocore.config import Config as BotoConfig
from opensearchpy import OpenSearch, helpers

logger = logging.getLogger(__name__)

INDEX_NAME = "house_document_chunks"

EMBEDDING_DIMENSION = 1024

_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "index.knn": True,
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "title": {"type": "text"},
            "section_heading": {"type": "text"},
            "content": {"type": "text", "analyzer": "english"},
            "source_type": {"type": "keyword"},
            "document_type": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "embedding": {
                "type": "knn_vector",
                "dimension": EMBEDDING_DIMENSION,
                "method": {"name": "hnsw", "engine": "nmslib", "space_type": "cosinesimil"},
            },
        },
    },
}

# Lazy-init Bedrock runtime client for embeddings
_bedrock_runtime = None


def _get_bedrock_runtime():
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1"),
            config=BotoConfig(read_timeout=120, connect_timeout=10, retries={"max_attempts": 3}),
        )
    return _bedrock_runtime


def get_embedding(text: str) -> list[float]:
    """Get embedding vector for text using Bedrock Titan Embeddings."""
    client = _get_bedrock_runtime()
    model_id = os.getenv("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
    resp = client.invoke_model(
        modelId=model_id,
        body=json.dumps({"inputText": text[:8000]}),
    )
    return json.loads(resp["body"].read())["embedding"]


def get_client() -> OpenSearch:
    return OpenSearch(
        hosts=[
            {
                "host": os.getenv("OPENSEARCH_HOST", "localhost"),
                "port": int(os.getenv("OPENSEARCH_PORT", "9200")),
            },
        ],
        use_ssl=False,
        verify_certs=False,
    )


def ensure_index():
    """Create the chunk index if it doesn't exist."""
    client = get_client()
    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(index=INDEX_NAME, body=_MAPPING)
        logger.info("Created OpenSearch index: %s", INDEX_NAME)


def index_chunks(document_id: str, title: str, chunks: list[dict]):
    """Bulk-index chunks with embeddings for hybrid search. Deletes old chunks first."""
    client = get_client()

    # Remove old chunks for this document
    client.delete_by_query(
        index=INDEX_NAME,
        body={"query": {"term": {"document_id": document_id}}},
        ignore=[404],
    )

    if not chunks:
        return

    actions = []
    for i, c in enumerate(chunks):
        source = {
            "chunk_id": c["chunk_id"],
            "document_id": document_id,
            "title": title,
            "section_heading": c.get("section_heading", "Body"),
            "content": c["content"],
            "source_type": c.get("source_type", "uploaded_file"),
            "document_type": c.get("document_type", "general"),
            "tags": c.get("tags", []),
        }
        try:
            source["embedding"] = get_embedding(c["content"])
        except Exception as e:
            logger.warning("Embedding failed for chunk %s, indexing without vector: %s", c["chunk_id"], e)
        actions.append({"_index": INDEX_NAME, "_id": c["chunk_id"], "_source": source})
        # Rate limit: avoid throttling on embedding API
        if i > 0 and i % 5 == 0:
            import time
            time.sleep(0.1)

    helpers.bulk(client, actions)
    logger.info("Indexed %d chunks (with embeddings) for %s", len(actions), document_id)


def search_chunks(
    query: str,
    filters: dict | None = None,
    page: int = 1,
    page_size: int = 10,
    document_ids: list[str] | None = None,
    top_k: int | None = None,
) -> dict:
    """Hybrid search: BM25 + kNN vector similarity, combined with score normalization.
    
    When document_ids is provided, restricts search to chunks from those documents only.
    When top_k is provided and document_ids is set, returns a dict of {doc_id: text} with
    the top_k most relevant chunks grouped by document (for targeted context building).
    """
    client = get_client()

    filter_clauses = []
    if filters:
        for key, val in filters.items():
            if key in ("document_type", "source_type"):
                filter_clauses.append({"term": {key: val}})
            elif key == "tag":
                filter_clauses.append({"term": {"tags": val}})

    if document_ids:
        filter_clauses.append({"terms": {"document_id": document_ids}})

    # BM25 leg — title gets highest boost so documents whose name matches the query
    # rank above documents that merely mention the term in body text.
    # document_type is keyword, so we add wildcard clauses for each query word.
    _STOP_WORDS = {
        "the", "this", "that", "which", "what", "where", "when", "how", "who",
        "for", "from", "with", "about", "into", "does", "have", "has", "had",
        "are", "was", "were", "been", "being", "will", "would", "could", "should",
        "can", "may", "might", "shall", "must", "need", "find", "show", "get",
        "document", "file", "paper", "paperwork", "page", "copy",
        "house", "home", "property", "our", "their", "your",
    }
    query_words = [w for w in query.lower().split() if len(w) > 2 and w not in _STOP_WORDS]
    doc_type_clauses = [
        {"wildcard": {"document_type": {"value": f"*{w}*", "boost": 20}}}
        for w in query_words
    ]
    bm25_query = {
        "bool": {
            "should": [
                {
                    "multi_match": {
                        "query": query,
                        "fields": ["title^5", "content^2", "section_heading"],
                        "type": "best_fields",
                    },
                },
                *doc_type_clauses,
            ],
        },
    }

    # Build hybrid query: combine BM25 and kNN in a bool/should
    should_clauses = [bm25_query]
    try:
        query_embedding = get_embedding(query)
        knn_clause = {
            "knn": {
                "embedding": {
                    "vector": query_embedding,
                    "k": page_size * 2,
                },
            },
        }
        should_clauses.append(knn_clause)
    except Exception as e:
        logger.warning("Embedding query failed, falling back to BM25 only: %s", e)

    body = {
        "query": {
            "bool": {
                "should": should_clauses,
                "filter": filter_clauses,
                "minimum_should_match": 1,
            },
        },
        "from": (page - 1) * page_size,
        "size": page_size,
        "highlight": {
            "fields": {"content": {"fragment_size": 500, "number_of_fragments": 1}},
        },
    }

    # For user-facing searches (no document_ids restriction), collapse results so we
    # show the single best chunk per document instead of flooding results with one doc.
    if not document_ids:
        body["collapse"] = {"field": "document_id"}

    resp = client.search(index=INDEX_NAME, body=body)

    results = []
    for hit in resp["hits"]["hits"]:
        src = hit["_source"]
        snippet = src["content"][:300]
        if "highlight" in hit and "content" in hit["highlight"]:
            snippet = hit["highlight"]["content"][0]

        results.append(
            {
                "document_id": src["document_id"],
                "chunk_id": src["chunk_id"],
                "title": src["title"],
                "snippet": snippet,
                "score": round(hit["_score"], 4),
                "source_type": src["source_type"],
                "document_type": src["document_type"],
            },
        )

    # Facet aggregation
    agg_body = {
        "query": body["query"],
        "size": 0,
        "aggs": {
            "document_type": {"terms": {"field": "document_type", "size": 20}},
            "source_type": {"terms": {"field": "source_type", "size": 20}},
        },
    }
    agg_resp = client.search(index=INDEX_NAME, body=agg_body)
    facets = {}
    for agg_name in ("document_type", "source_type"):
        facets[agg_name] = {b["key"]: b["doc_count"] for b in agg_resp["aggregations"][agg_name]["buckets"]}

    return {
        "results": results,
        "total": resp["hits"]["total"]["value"],
        "facets": facets,
    }


def search_chunks_grouped(query: str, document_ids: list[str], top_k: int = 30) -> dict[str, str]:
    """Search for relevant chunks within specific documents, return grouped text by doc_id.
    
    Used by the Tasks pipeline to get only the relevant portions of large documents
    instead of loading entire documents into context.
    """
    result = search_chunks(query, document_ids=document_ids, page=1, page_size=top_k)
    grouped: dict[str, list[str]] = {}
    for r in result["results"]:
        grouped.setdefault(r["document_id"], []).append(r["snippet"])
    # Return full content text per document (deduplicated chunks joined)
    # For better context, fetch full chunk content instead of just snippets
    client = get_client()
    doc_texts: dict[str, str] = {}
    for doc_id, snippets in grouped.items():
        # Get the actual chunk IDs we found, then fetch their full content
        chunk_ids = [r["chunk_id"] for r in result["results"] if r["document_id"] == doc_id]
        body = {"query": {"terms": {"chunk_id": chunk_ids}}, "size": len(chunk_ids)}
        try:
            resp = client.search(index=INDEX_NAME, body=body)
            texts = [hit["_source"]["content"] for hit in resp["hits"]["hits"]]
            doc_texts[doc_id] = "\n".join(texts)
        except Exception:
            doc_texts[doc_id] = "\n".join(snippets)
    return doc_texts


def decompose_prompt(query: str) -> dict:
    """Use a fast model to decompose a user prompt into a structured intent map.
    
    Returns a dict with fields:
      action, target_document, vendor, product, subject, output_type
    Each field is used as a targeted retrieval/rerank signal.
    """
    import re

    try:
        client = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))
        resp = client.converse(
            modelId="amazon.nova-micro-v1:0",
            messages=[{"role": "user", "content": [{"text": (
                "Decompose this prompt into a structured intent map. "
                "Extract ONLY what is explicitly stated. Use empty string if not mentioned.\n\n"
                f"Prompt: \"{query}\"\n\n"
                "Respond with ONLY this JSON (no explanation):\n"
                '{"action":"what the user wants to do",'
                '"target_document":"specific form/document to fill or reference",'
                '"vendor":"company/person/organization name",'
                '"product":"specific product, system, or service mentioned",'
                '"subject":"the topic/domain in 3-5 words",'
                '"output_type":"what format the output should be"}'
            )}]}],
            inferenceConfig={"maxTokens": 200},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        match = re.search(r"\{[^}]+\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.warning("Prompt decomposition failed: %s", e)

    return {"action": "", "target_document": "", "vendor": "", "product": "", "subject": "", "output_type": ""}


def refine_document_selection(query: str, candidates: list[dict], top_k: int = 10) -> list[dict]:
    """Document refinement using structured prompt decomposition + reranking.
    
    Phase 1: Decompose prompt into intent map (fast model)
    Phase 2: Tag candidates with entity/vendor match from intent map
    Phase 3: Rerank using subject+vendor+product as the query (content-focused)
    Phase 4: Score cutoff — keep docs above threshold or entity matches
    
    Args:
        query: The user's prompt
        candidates: List of {document_id, title, score, snippet} dicts
        top_k: Maximum documents to return
    
    Returns:
        Filtered and reordered candidate list
    """
    import re

    if not candidates:
        return candidates

    # === Phase 1: Decompose prompt ===
    intent = decompose_prompt(query)
    logger.info("Prompt decomposition: %s", intent)

    # === Phase 2: Entity/vendor matching ===
    vendor = (intent.get("vendor") or "").lower()
    product = (intent.get("product") or "").lower()

    for doc in candidates:
        title_lower = (doc.get("title") or "").lower()
        snippet_lower = (doc.get("snippet") or "").lower()
        combined = title_lower + " " + snippet_lower
        # Match if vendor or product appears in title or snippet
        doc["_entity_match"] = bool(
            (vendor and vendor in combined) or
            (product and product in combined)
        )

    # === Phase 3: Rerank with content-focused query ===
    # Build rerank query from the content fields (not the action)
    rerank_parts = [intent.get("vendor", ""), intent.get("product", ""), intent.get("subject", "")]
    rerank_query = " ".join(p for p in rerank_parts if p).strip()
    if not rerank_query or len(rerank_query) < 5:
        rerank_query = query  # fallback

    try:
        bedrock = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"))

        rerank_docs = []
        for doc in candidates:
            title = doc.get("title", "")
            snippet = doc.get("snippet", "")
            rerank_docs.append(f"{title}. {snippet}"[:1024])

        resp = bedrock.invoke_model(
            modelId="cohere.rerank-v3-5:0",
            body=json.dumps({
                "api_version": 2,
                "query": rerank_query,
                "documents": rerank_docs,
                "top_n": len(candidates),
            }),
        )
        rerank_result = json.loads(resp["body"].read())

        reranked = []
        for item in rerank_result.get("results", []):
            idx = item["index"]
            candidates[idx]["_rerank_score"] = item["relevance_score"]
            reranked.append(candidates[idx])
        candidates = reranked

    except Exception as e:
        logger.warning("Rerank failed, skipping: %s", e)

    # === Phase 4: Score cutoff ===
    if any("_rerank_score" in doc for doc in candidates):
        scores = [doc.get("_rerank_score", 0) for doc in candidates]
        max_score = max(scores) if scores else 0
        threshold = max_score * 0.08  # Keep docs scoring at least 8% of top
        candidates = [
            doc for doc in candidates
            if doc.get("_rerank_score", 0) >= threshold or doc.get("_entity_match", False)
        ]

    return candidates[:top_k]

    return candidates[:top_k]
