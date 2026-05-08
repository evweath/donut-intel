"""
AI Product Categorizer (F64)
Uses Anthropic Claude API to auto-assign categories and subcategories.
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            import anthropic
            from backend.config import config
            api_key = config.get("ai", "anthropic_api_key", default="")
            if not api_key:
                raise ValueError("No Anthropic API key configured")
            _client = anthropic.Anthropic(api_key=api_key)
        except Exception as exc:
            logger.warning(f"AI categorizer unavailable: {exc}")
            return None
    return _client


BAKERY_CATEGORIES = [
    "Fryers & Frying Equipment",
    "Donut Glazing & Icing Equipment",
    "Dough Mixers & Prep Equipment",
    "Proofers & Ovens",
    "Display Cases & Merchandising",
    "Packaging & Supplies",
    "Ingredients & Mixes",
    "Smallwares & Utensils",
    "Refrigeration & Storage",
    "Cleaning & Sanitation",
    "Ventilation & Hoods",
    "Other Bakery Equipment",
]


def categorize_product(title: str, description: str = "") -> Optional[dict]:
    """
    Returns {"category": "...", "subcategory": "...", "confidence": 0.0} or None on failure.
    """
    client = _get_client()
    if not client:
        return None

    prompt = f"""You are a bakery and donut equipment expert. Categorize this product into one of the provided categories.

Product Title: {title}
Product Description: {description[:500] if description else 'N/A'}

Available Categories:
{chr(10).join(f'- {c}' for c in BAKERY_CATEGORIES)}

Respond with valid JSON only, no explanation:
{{
  "category": "<category from list>",
  "subcategory": "<specific subcategory, e.g. 'Commercial Gas Fryers'>",
  "confidence": <0.0-1.0>
}}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text)
    except Exception as exc:
        logger.warning(f"AI categorization failed for '{title[:50]}': {exc}")
        return None


def bulk_categorize(product_ids: list) -> dict:
    """
    Categorize multiple products and update the DB.
    Returns {product_id: result_dict}.
    """
    from backend.database.db import session_scope
    from backend.database.models import Product

    results = {}
    with session_scope() as db:
        products = (
            db.query(Product)
            .filter(Product.id.in_(product_ids), Product.is_active == True)
            .all()
        )
        for p in products:
            result = categorize_product(p.canonical_title, p.canonical_description or "")
            if result:
                p.ai_category = result.get("category")
                if not p.category:
                    p.category = result.get("category")
                if not p.subcategory:
                    p.subcategory = result.get("subcategory")
                results[p.id] = result
                logger.info(f"Categorized [{p.id}] {p.canonical_title[:40]} → {result.get('category')}")
            else:
                results[p.id] = None

    return results
