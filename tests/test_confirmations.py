"""Tests for the SAME / SIMILR result-classification API (backend/api/routes.py).

SAME and SIMILR are mutually exclusive per result URL: at most one value is
stored, flipping replaces it, and clearing removes the row entirely (neither
box checked).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, ResultConfirmation
from backend.api.routes import list_confirmations, set_confirmation, ConfirmationRequest


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_set_same_creates_row(db):
    res = set_confirmation(ConfirmationRequest(url="http://x/1", match_type="same"), db)
    assert res["match_type"] == "same"
    assert res["verified_at"] is not None
    row = db.query(ResultConfirmation).filter_by(url="http://x/1").one()
    assert row.match_type == "same"


def test_same_and_similar_are_mutually_exclusive(db):
    set_confirmation(ConfirmationRequest(url="http://x/1", match_type="same"), db)
    # Flipping to similar replaces the value — it must not add a second row.
    set_confirmation(ConfirmationRequest(url="http://x/1", match_type="similar"), db)
    rows = db.query(ResultConfirmation).filter_by(url="http://x/1").all()
    assert len(rows) == 1
    assert rows[0].match_type == "similar"


def test_clear_deletes_row(db):
    set_confirmation(ConfirmationRequest(url="http://x/1", match_type="same"), db)
    res = set_confirmation(ConfirmationRequest(url="http://x/1", match_type=None), db)
    assert res["match_type"] is None
    assert db.query(ResultConfirmation).filter_by(url="http://x/1").count() == 0


def test_list_returns_type_and_verified_at(db):
    set_confirmation(ConfirmationRequest(url="http://x/1", match_type="same"), db)
    set_confirmation(ConfirmationRequest(url="http://x/2", match_type="similar"), db)
    out = list_confirmations(db)["confirmations"]
    assert set(out.keys()) == {"http://x/1", "http://x/2"}
    assert out["http://x/1"]["type"] == "same"
    assert out["http://x/2"]["type"] == "similar"
    assert out["http://x/1"]["verified_at"] is not None


def test_invalid_match_type_rejected(db):
    with pytest.raises(HTTPException):
        set_confirmation(ConfirmationRequest(url="http://x/1", match_type="bogus"), db)
