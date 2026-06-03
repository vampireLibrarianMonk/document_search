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
            config=BotoConfig(read_timeout=30, connect_timeout=5),
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
    for c in chunks:
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

    helpers.bulk(client, actions)
    logger.info("Indexed %d chunks (with embeddings) for %s", len(actions), document_id)


def search_chunks(
    query: str,
    filters: dict | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """Hybrid search: BM25 + kNN vector similarity, combined with score normalization."""
    client = get_client()

    filter_clauses = []
    if filters:
        for key, val in filters.items():
            if key in ("document_type", "source_type"):
                filter_clauses.append({"term": {key: val}})
            elif key == "tag":
                filter_clauses.append({"term": {"tags": val}})

    # BM25 leg
    bm25_query = {
        "multi_match": {
            "query": query,
            "fields": ["content^3", "title", "section_heading"],
            "type": "best_fields",
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
