"""OpenSearch integration for chunk indexing and search.

Indexes document chunks into OpenSearch for fast full-text search
with BM25 scoring, replacing the in-memory keyword scanner.
"""

from __future__ import annotations

import logging
import os

from opensearchpy import OpenSearch, helpers

logger = logging.getLogger(__name__)

INDEX_NAME = "house_document_chunks"

_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "title": {"type": "text"},
            "section_heading": {"type": "text"},
            "content": {"type": "text", "analyzer": "standard"},
            "source_type": {"type": "keyword"},
            "document_type": {"type": "keyword"},
            "tags": {"type": "keyword"},
        }
    },
}


def get_client() -> OpenSearch:
    return OpenSearch(
        hosts=[{
            "host": os.getenv("OPENSEARCH_HOST", "localhost"),
            "port": int(os.getenv("OPENSEARCH_PORT", "9200")),
        }],
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
    """Bulk-index chunks for a document. Deletes old chunks first."""
    client = get_client()

    # Remove old chunks for this document
    client.delete_by_query(
        index=INDEX_NAME,
        body={"query": {"term": {"document_id": document_id}}},
        ignore=[404],
    )

    if not chunks:
        return

    actions = [
        {
            "_index": INDEX_NAME,
            "_id": c["chunk_id"],
            "_source": {
                "chunk_id": c["chunk_id"],
                "document_id": document_id,
                "title": title,
                "section_heading": c.get("section_heading", "Body"),
                "content": c["content"],
                "source_type": c.get("source_type", "uploaded_file"),
                "document_type": c.get("document_type", "general"),
                "tags": c.get("tags", []),
            },
        }
        for c in chunks
    ]
    helpers.bulk(client, actions)
    logger.info("Indexed %d chunks for %s", len(actions), document_id)


def search_chunks(query: str, filters: dict | None = None,
                  page: int = 1, page_size: int = 10) -> dict:
    """Full-text search over chunks using OpenSearch BM25."""
    client = get_client()

    must = [{"multi_match": {
        "query": query,
        "fields": ["content^3", "title", "section_heading"],
        "type": "best_fields",
    }}]

    filter_clauses = []
    if filters:
        for key, val in filters.items():
            if key in ("document_type", "source_type"):
                filter_clauses.append({"term": {key: val}})
            elif key == "tag":
                filter_clauses.append({"term": {"tags": val}})

    body = {
        "query": {
            "bool": {
                "must": must,
                "filter": filter_clauses,
            }
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
        # Use highlighted snippet if available, otherwise first 300 chars
        snippet = src["content"][:300]
        if "highlight" in hit and "content" in hit["highlight"]:
            snippet = hit["highlight"]["content"][0]

        results.append({
            "document_id": src["document_id"],
            "chunk_id": src["chunk_id"],
            "title": src["title"],
            "snippet": snippet,
            "score": round(hit["_score"], 4),
            "source_type": src["source_type"],
            "document_type": src["document_type"],
        })

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
        facets[agg_name] = {
            b["key"]: b["doc_count"]
            for b in agg_resp["aggregations"][agg_name]["buckets"]
        }

    return {
        "results": results,
        "total": resp["hits"]["total"]["value"],
        "facets": facets,
    }
