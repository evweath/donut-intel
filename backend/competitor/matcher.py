"""
Competitor Product Matcher (F17-F21)
Matches scraped competitor products to the master catalog using configurable criteria.
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


@dataclass
class MatchCriteria:
    use_model_number: bool = True
    use_manufacturer: bool = True
    use_title_exact: bool = True
    use_title_fuzzy: bool = True
    use_price: bool = False
    use_image_hash: bool = False
    fuzzy_threshold: float = 70.0   # 50=loose, 70=moderate, 90=strict
    price_tolerance_pct: float = 15.0

    # Weights for scoring
    weight_model: float = 40.0
    weight_manufacturer: float = 20.0
    weight_title: float = 30.0
    weight_price: float = 10.0

    @classmethod
    def from_dict(cls, d: dict) -> "MatchCriteria":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MatchResult:
    master_product_id: int
    confidence: float
    match_types: List[str] = field(default_factory=list)
    reasons: Dict[str, Any] = field(default_factory=dict)
    is_similar: bool = False
    similarity_reason: str = ""


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    return s.lower().strip()


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.token_set_ratio(a, b)


def match_competitor_product(
    competitor_product: dict,
    master_products: List[Any],  # SQLAlchemy Product objects
    criteria: Optional[MatchCriteria] = None,
) -> Optional[MatchResult]:
    """
    Attempt to match a single competitor product dict to the master catalog.
    competitor_product keys: title, price, model_number, manufacturer, image_hash, description, sku
    Returns the best match or None if below threshold.
    """
    if criteria is None:
        criteria = MatchCriteria()

    comp_title = _norm(competitor_product.get("title", ""))
    comp_model = _norm(competitor_product.get("model_number", "") or competitor_product.get("sku", ""))
    comp_mfr = _norm(competitor_product.get("manufacturer", ""))
    comp_price = competitor_product.get("price")
    comp_img_hash = competitor_product.get("image_hash", "")

    best: Optional[MatchResult] = None
    MIN_CONFIDENCE = 40.0

    for master in master_products:
        master_model = _norm(master.model_number or master.sku or "")
        master_mfr = _norm(master.manufacturer or "")
        master_title = _norm(master.canonical_title or "")
        master_price = master.price_canonical

        score = 0.0
        types = []
        reasons = {}

        # Hard disqualifier: model numbers present but don't match
        if criteria.use_model_number and comp_model and master_model:
            if comp_model == master_model:
                score += criteria.weight_model
                types.append("model_exact")
                reasons["model"] = {"comp": comp_model, "master": master_model, "score": criteria.weight_model}
            else:
                # Model numbers exist but differ — skip unless similarity is very high
                title_sim = _title_similarity(comp_title, master_title)
                if title_sim < 85:
                    continue
        elif criteria.use_model_number and comp_model and not master_model:
            pass  # master has no model, can't disqualify

        # Manufacturer match
        if criteria.use_manufacturer and comp_mfr and master_mfr:
            if comp_mfr == master_mfr:
                score += criteria.weight_manufacturer
                types.append("manufacturer")
                reasons["manufacturer"] = {"score": criteria.weight_manufacturer}
            else:
                mfr_sim = fuzz.ratio(comp_mfr, master_mfr)
                if mfr_sim >= 80:
                    partial = criteria.weight_manufacturer * (mfr_sim / 100)
                    score += partial
                    reasons["manufacturer_fuzzy"] = {"similarity": mfr_sim, "score": partial}

        # Title matching
        if comp_title and master_title:
            title_sim = _title_similarity(comp_title, master_title)
            if criteria.use_title_exact and title_sim >= 95:
                score += criteria.weight_title
                types.append("title_exact")
                reasons["title"] = {"similarity": title_sim, "score": criteria.weight_title}
            elif criteria.use_title_fuzzy and title_sim >= criteria.fuzzy_threshold:
                partial = criteria.weight_title * (title_sim / 100)
                score += partial
                types.append("title_fuzzy")
                reasons["title_fuzzy"] = {"similarity": title_sim, "score": partial}

        # Price match
        if criteria.use_price and comp_price and master_price:
            pct_diff = abs(comp_price - master_price) / master_price * 100
            if pct_diff <= criteria.price_tolerance_pct:
                price_score = criteria.weight_price * (1 - pct_diff / criteria.price_tolerance_pct)
                score += price_score
                types.append("price")
                reasons["price"] = {"comp": comp_price, "master": master_price, "pct_diff": pct_diff, "score": price_score}

        # Image hash match (F20)
        if criteria.use_image_hash and comp_img_hash:
            master_hashes = [img.image_hash for img in getattr(master, "images", []) if img.image_hash]
            if comp_img_hash in master_hashes:
                score += 30.0
                types.append("image_hash")
                reasons["image"] = {"score": 30.0}

        if score < MIN_CONFIDENCE:
            continue

        if not best or score > best.confidence:
            best = MatchResult(
                master_product_id=master.id,
                confidence=round(score, 1),
                match_types=types,
                reasons=reasons,
            )

    return best


def match_similar_product(
    competitor_product: dict,
    master_products: List[Any],
    similarity_profile: Optional[dict] = None,
) -> Optional[MatchResult]:
    """
    F27-F29: Find similar-but-not-identical products based on characteristics.
    similarity_profile: dict of {characteristic: weight}
    """
    profile = similarity_profile or {
        "category": 30,
        "manufacturer": 20,
        "price_range": 20,
        "title_keywords": 30,
    }

    comp_title = _norm(competitor_product.get("title", ""))
    comp_price = competitor_product.get("price")
    comp_mfr = _norm(competitor_product.get("manufacturer", ""))
    comp_specs = competitor_product.get("specs", {}) or {}

    best: Optional[MatchResult] = None

    for master in master_products:
        score = 0.0
        reasons = {}
        similarity_reasons = []

        # Keyword overlap (broad)
        if "title_keywords" in profile and comp_title:
            sim = _title_similarity(comp_title, _norm(master.canonical_title or ""))
            if sim >= 30:
                partial = profile["title_keywords"] * (sim / 100)
                score += partial
                reasons["title_keywords"] = {"similarity": sim}
                if sim >= 30:
                    similarity_reasons.append(f"similar title ({sim:.0f}% match)")

        # Manufacturer match
        if "manufacturer" in profile and comp_mfr and master.manufacturer:
            if comp_mfr == _norm(master.manufacturer):
                score += profile["manufacturer"]
                similarity_reasons.append("same manufacturer")

        # Price range overlap
        if "price_range" in profile and comp_price and master.price_canonical:
            price_pct = abs(comp_price - master.price_canonical) / master.price_canonical * 100
            if price_pct <= 30:
                partial = profile["price_range"] * (1 - price_pct / 30)
                score += partial
                similarity_reasons.append(f"similar price range (±{price_pct:.0f}%)")

        # Spec matching
        if "specs" in profile and comp_specs:
            master_specs = {}
            if master.specs_json:
                try:
                    master_specs = json.loads(master.specs_json)
                except Exception:
                    pass
            if master_specs:
                matching_keys = set(k.lower() for k in comp_specs) & set(k.lower() for k in master_specs)
                if matching_keys:
                    partial = profile.get("specs", 20) * (len(matching_keys) / max(len(comp_specs), 1))
                    score += partial
                    similarity_reasons.append(f"matching specs: {', '.join(list(matching_keys)[:3])}")

        if score < 25:
            continue

        if not best or score > best.confidence:
            best = MatchResult(
                master_product_id=master.id,
                confidence=round(score, 1),
                match_types=["similar"],
                reasons=reasons,
                is_similar=True,
                similarity_reason="; ".join(similarity_reasons),
            )

    return best
