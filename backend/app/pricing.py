"""Bedrock pricing fetcher.

Pulls per-token pricing from the AWS bulk pricing JSON for a given region.
The pricing URL is discovered dynamically from the region index, so it
always reflects the latest published prices.

Usage:
    prices = get_pricing("us-east-1")
    cost = prices.get("anthropic.claude-3-haiku-20240307-v1:0", {})
    # {"input_per_1k": 0.00025, "output_per_1k": 0.00125}
"""

from __future__ import annotations

import json
import time as _time
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# AWS bulk pricing base URL
_PRICING_BASE = "https://pricing.us-east-1.amazonaws.com"
_REGION_INDEX_PATH = "/offers/v1.0/aws/AmazonBedrock/current/region_index.json"

# US regions we support
US_REGIONS = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
]

# Map AWS pricing usage-type prefixes to Bedrock model IDs.
# The pricing JSON uses names like "Claude3Haiku" while the API uses
# "anthropic.claude-3-haiku-20240307-v1:0". This table bridges them.
_USAGE_TO_MODEL: dict[str, str] = {
    # Anthropic
    "Claude3Haiku": "anthropic.claude-3-haiku-20240307-v1:0",
    "Claude3Sonnet": "anthropic.claude-3-sonnet-20240229-v1:0",
    "Claude3.5Sonnet": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "Claude3.7Sonnet": "anthropic.claude-3-7-sonnet-20250219-v1:0",
    "Claude3.5Haiku": "anthropic.claude-3-5-haiku-20241022-v1:0",
    "Claude4Sonnet": "anthropic.claude-sonnet-4-20250514-v1:0",
    "Claude4.5Sonnet": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "Claude4Haiku": "anthropic.claude-haiku-4-5-20251001-v1:0",
    "Claude4Opus": "anthropic.claude-opus-4-20250514-v1:0",
    "Claude4.1Opus": "anthropic.claude-opus-4-1-20250805-v1:0",
    "Claude2.0": "anthropic.claude-v2",
    "Claude2.1": "anthropic.claude-v2:1",
    "ClaudeInstant": "anthropic.claude-instant-v1",
    # Amazon Nova
    "NovaLite": "amazon.nova-lite-v1:0",
    "NovaPro": "amazon.nova-pro-v1:0",
    "NovaMicro": "amazon.nova-micro-v1:0",
    "Nova2.0Lite": "amazon.nova-2-lite-v1:0",
    "Nova2.0Pro": "amazon.nova-2-pro-v1:0",
    # Meta Llama
    "Llama3-8B": "meta.llama3-8b-instruct-v1:0",
    "Llama3-70B": "meta.llama3-70b-instruct-v1:0",
    "Llama3-1-8B": "meta.llama3-1-8b-instruct-v1:0",
    "Llama3-1-70B": "meta.llama3-1-70b-instruct-v1:0",
    "Llama3-3-70B": "meta.llama3-3-70b-instruct-v1:0",
    "Llama4-Scout-17B": "meta.llama4-scout-17b-instruct-v1:0",
    "Llama4-Maverick-17B": "meta.llama4-maverick-17b-instruct-v1:0",
    # Mistral
    "Mistral7B": "mistral.mistral-7b-instruct-v0:2",
    "MistralSmall": "mistral.mistral-small-2402-v1:0",
    "MistralLarge": "mistral.mistral-large-2402-v1:0",
    "Mistral-Large-3-675b-Instruct": "mistral.mistral-large-3-675b-instruct",
}

# In-memory cache: region -> {data, fetched_at}
_cache: dict[str, dict] = {}

# Cache pricing for 24 hours before re-fetching
_CACHE_TTL_SECONDS = 86400


def _region_prefix(region: str) -> str:
    """Convert region code to the pricing usagetype prefix (e.g., us-east-1 -> USE1)."""
    prefixes = {
        "us-east-1": "USE1",
        "us-east-2": "USE2",
        "us-west-1": "USW1",
        "us-west-2": "USW2",
    }
    return prefixes.get(region, "USE1")


def fetch_pricing(region: str = "us-east-1") -> dict[str, dict[str, float]]:
    """Fetch and parse Bedrock pricing for a region.

    Returns a dict mapping model_id -> {"input_per_1k": float, "output_per_1k": float}.
    Results are cached in memory.
    """
    if region in _cache:
        entry = _cache[region]
        if _time.time() - entry["fetched_at"] < _CACHE_TTL_SECONDS:
            return entry["data"]
        logger.info("Pricing cache expired for %s, refreshing", region)

    try:
        # Step 1: get the region-specific pricing URL
        idx_resp = requests.get(f"{_PRICING_BASE}{_REGION_INDEX_PATH}", timeout=10)
        idx_resp.raise_for_status()
        regions = idx_resp.json().get("regions", {})
        if region not in regions:
            logger.warning("Region %s not found in pricing index", region)
            return {}
        version_url = regions[region]["currentVersionUrl"]

        # Step 2: download the full pricing JSON for this region
        data_resp = requests.get(f"{_PRICING_BASE}{version_url}", timeout=30)
        data_resp.raise_for_status()
        data = data_resp.json()

        prices = _parse_pricing_json(data, region)
        _cache[region] = {"data": prices, "fetched_at": _time.time()}
        logger.info(
            "Loaded Bedrock pricing for %s: %d models",
            region,
            len(prices),
        )
        return prices

    except Exception as e:
        logger.warning("Failed to fetch Bedrock pricing for %s: %s", region, e)
        return {}


def load_pricing_from_json(raw_json: str, region: str = "us-east-1") -> dict[str, dict[str, float]]:
    """Parse pricing from a manually provided JSON string.

    This lets users paste the pricing JSON into Settings if the
    automatic fetch doesn't work.
    """
    try:
        data = json.loads(raw_json)
        prices = _parse_pricing_json(data, region)
        _cache[region] = {"data": prices, "fetched_at": _time.time()}
        return prices
    except Exception as e:
        logger.warning("Failed to parse manual pricing JSON: %s", e)
        return {}


def _parse_pricing_json(
    data: dict,
    region: str,
) -> dict[str, dict[str, float]]:
    """Extract per-token prices from the AWS bulk pricing JSON."""
    prefix = _region_prefix(region)
    prices: dict[str, dict[str, float]] = {}

    for sku, product in data.get("products", {}).items():
        attrs = product.get("attributes", {})
        usage = attrs.get("usagetype", "")

        # Only look at this region's on-demand token pricing
        if not usage.startswith(f"{prefix}-"):
            continue
        if "input-tokens" not in usage and "output-tokens" not in usage:
            continue
        # Skip batch, flex, priority, latency-optimized variants
        if any(
            x in usage
            for x in ["-batch", "-flex", "-priority", "-latency", "-cache", "-custom-model"]
        ):
            continue

        # Get the price
        terms = data.get("terms", {}).get("OnDemand", {}).get(sku, {})
        usd = 0.0
        for _tid, term in terms.items():
            for _did, dim in term.get("priceDimensions", {}).items():
                usd = float(dim["pricePerUnit"].get("USD", "0"))

        if usd <= 0:
            continue

        # Parse the model name from usagetype: USE1-ModelName-input-tokens
        stripped = usage.replace(f"{prefix}-", "")
        is_input = "-input-tokens" in stripped
        model_name = stripped.replace("-input-tokens", "").replace("-output-tokens", "")

        # Map to a Bedrock model ID
        model_id = _USAGE_TO_MODEL.get(model_name)
        if not model_id:
            # Try a fuzzy match for models not in our lookup table
            model_id = _fuzzy_match_model(model_name)
        if not model_id:
            continue

        if model_id not in prices:
            prices[model_id] = {"input_per_1k": 0.0, "output_per_1k": 0.0}

        if is_input:
            prices[model_id]["input_per_1k"] = usd
        else:
            prices[model_id]["output_per_1k"] = usd

    return prices


def _fuzzy_match_model(pricing_name: str) -> Optional[str]:
    """Try to match a pricing name to a model ID by pattern."""
    # Handle names like "mistral.devstral-2-123b" which include the full model ID
    if "." in pricing_name:
        return pricing_name
    return None


def estimate_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    region: str = "us-east-1",
) -> float:
    """Estimate the cost in USD for a given number of tokens."""
    prices = fetch_pricing(region)
    model_prices = prices.get(model_id, {})
    if not model_prices:
        return 0.0
    input_cost = (input_tokens / 1000) * model_prices.get("input_per_1k", 0)
    output_cost = (output_tokens / 1000) * model_prices.get("output_per_1k", 0)
    return round(input_cost + output_cost, 8)
