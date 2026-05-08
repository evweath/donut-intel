"""
String and data matching utilities for deduplication and competitor matching.
Uses rapidfuzz for fuzzy string comparison (fast C++ implementation).
"""
import re
import unicodedata
from typing import Optional, Tuple

from rapidfuzz import fuzz, process


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """
    Lowercase, strip accents, collapse whitespace, remove punctuation clutter.
    Used before any string comparison.
    """
    if not text:
        return ""
    # Normalize unicode
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    # Remove common noise words for product titles
    noise = [
        r"\b(the|a|an|and|or|for|of|in|on|at|to|with|by)\b",
        r"[\"\'`]",
    ]
    for pattern in noise:
        text = re.sub(pattern, " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_model(model: str) -> str:
    """
    Normalize model numbers: uppercase, strip spaces and hyphens for comparison.
    e.g. "MD-123 A" -> "MD123A"
    """
    if not model:
        return ""
    return re.sub(r"[\s\-_./]", "", model.upper().strip())


def normalize_manufacturer(mfr: str) -> str:
    """
    Normalize manufacturer names for comparison.
    e.g. "Belshaw Adamatic" -> "belshaw adamatic"
    """
    if not mfr:
        return ""
    return re.sub(r"\s+", " ", mfr.lower().strip())


def normalize_price(price: float, tolerance_pct: float = 2.0) -> Tuple[float, float]:
    """Return a (low, high) range for price matching within tolerance."""
    if price is None or price <= 0:
        return (0.0, 0.0)
    margin = price * (tolerance_pct / 100.0)
    return (price - margin, price + margin)


# ---------------------------------------------------------------------------
# Individual comparison functions
# ---------------------------------------------------------------------------

def price_match(
    price_a: Optional[float],
    price_b: Optional[float],
    tolerance_pct: float = 2.0,
) -> float:
    """
    Returns match score 0–100.
    100 = within tolerance, 0 = no match or missing.
    """
    if price_a is None or price_b is None or price_a <= 0 or price_b <= 0:
        return 0.0
    diff_pct = abs(price_a - price_b) / max(price_a, price_b) * 100
    if diff_pct <= tolerance_pct:
        return 100.0
    if diff_pct <= tolerance_pct * 3:
        return max(0.0, 100.0 - (diff_pct - tolerance_pct) * 20)
    return 0.0


def model_match(model_a: Optional[str], model_b: Optional[str]) -> float:
    """
    Returns 100 if normalized models are identical, 0 otherwise.
    Model numbers must be exact (normalized) to count.
    """
    if not model_a or not model_b:
        return 0.0
    na = normalize_model(model_a)
    nb = normalize_model(model_b)
    if not na or not nb:
        return 0.0
    return 100.0 if na == nb else 0.0


def manufacturer_match(mfr_a: Optional[str], mfr_b: Optional[str]) -> float:
    """
    Fuzzy match on manufacturer names.
    Returns 0–100.
    """
    if not mfr_a or not mfr_b:
        return 0.0
    na = normalize_manufacturer(mfr_a)
    nb = normalize_manufacturer(mfr_b)
    if not na or not nb:
        return 0.0
    # token_sort_ratio handles word order differences ("Belshaw Adamatic" vs "Adamatic Belshaw")
    return fuzz.token_sort_ratio(na, nb)


def title_match_exact(title_a: Optional[str], title_b: Optional[str]) -> float:
    """Normalized exact title comparison."""
    if not title_a or not title_b:
        return 0.0
    return 100.0 if normalize_text(title_a) == normalize_text(title_b) else 0.0


def title_match_fuzzy(title_a: Optional[str], title_b: Optional[str]) -> float:
    """
    Fuzzy title comparison using token_sort_ratio for word-order independence.
    Returns 0–100.
    """
    if not title_a or not title_b:
        return 0.0
    na = normalize_text(title_a)
    nb = normalize_text(title_b)
    if not na or not nb:
        return 0.0
    return fuzz.token_sort_ratio(na, nb)


def description_match(desc_a: Optional[str], desc_b: Optional[str]) -> float:
    """
    Fuzzy description comparison using partial_ratio (handles partial matches).
    Returns 0–100.
    """
    if not desc_a or not desc_b:
        return 0.0
    # Use first 500 chars of description to avoid slow comparisons on long text
    na = normalize_text(desc_a[:500])
    nb = normalize_text(desc_b[:500])
    if not na or not nb:
        return 0.0
    return fuzz.partial_ratio(na, nb)


def sku_match(sku_a: Optional[str], sku_b: Optional[str]) -> float:
    """Normalized exact SKU comparison."""
    if not sku_a or not sku_b:
        return 0.0
    na = re.sub(r"[\s\-_]", "", sku_a.upper().strip())
    nb = re.sub(r"[\s\-_]", "", sku_b.upper().strip())
    return 100.0 if na and nb and na == nb else 0.0


# ---------------------------------------------------------------------------
# Composite confidence scorer
# ---------------------------------------------------------------------------

def compute_confidence(
    price_a: Optional[float],
    price_b: Optional[float],
    model_a: Optional[str],
    model_b: Optional[str],
    manufacturer_a: Optional[str],
    manufacturer_b: Optional[str],
    title_a: Optional[str],
    title_b: Optional[str],
    desc_a: Optional[str],
    desc_b: Optional[str],
    sku_a: Optional[str] = None,
    sku_b: Optional[str] = None,
    price_weight: int = 40,
    model_weight: int = 35,
    manufacturer_weight: int = 15,
    title_weight: int = 20,
    description_weight: int = 10,
    price_tolerance_pct: float = 2.0,
) -> Tuple[float, dict]:
    """
    Compute an overall duplicate confidence score (0–100) and return the
    factor breakdown.

    Scoring logic:
    - If model numbers are present and DON'T match → hard cap at 30 (not dupes)
    - If SKUs are present and DON'T match → hard cap at 25
    - Otherwise weighted sum of individual factor scores, normalized to 100
    """
    scores = {
        "price": price_match(price_a, price_b, price_tolerance_pct),
        "model_number": model_match(model_a, model_b),
        "manufacturer": manufacturer_match(manufacturer_a, manufacturer_b),
        "title_fuzzy": title_match_fuzzy(title_a, title_b),
        "description": description_match(desc_a, desc_b),
        "sku": sku_match(sku_a, sku_b),
    }

    # Hard disqualifiers
    if model_a and model_b and normalize_model(model_a) and normalize_model(model_b):
        if scores["model_number"] == 0.0:
            return 5.0, {**scores, "disqualifier": "model_number_mismatch"}

    if sku_a and sku_b:
        if scores["sku"] == 0.0:
            return 5.0, {**scores, "disqualifier": "sku_mismatch"}

    # Weighted total
    total_weight = price_weight + model_weight + manufacturer_weight + title_weight + description_weight
    weighted_sum = (
        scores["price"] * price_weight
        + scores["model_number"] * model_weight
        + scores["manufacturer"] * manufacturer_weight
        + scores["title_fuzzy"] * title_weight
        + scores["description"] * description_weight
    )
    confidence = min(100.0, weighted_sum / total_weight)

    # Bonus: if both model and price match perfectly, boost to at least 85
    if scores["model_number"] == 100.0 and scores["price"] >= 95.0:
        confidence = max(confidence, 85.0)

    return round(confidence, 2), scores
