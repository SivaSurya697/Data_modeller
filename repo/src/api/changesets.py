"""API endpoints for working with change sets."""
from __future__ import annotations

from http import HTTPStatus

from flask import Blueprint, request
from sqlalchemy import select

from src.models.db import session_scope
from src.models.tables import ChangeSet

bp = Blueprint("changesets", __name__, url_prefix="/api/changesets")


def _resolve_current_user() -> str:
    """Resolve the current user from request headers."""

    header_candidates = ("X-User", "X-User-Email", "X-User-Id")
    for header in header_candidates:
        value = request.headers.get(header)
        if value:
            return value
    return "system"


@bp.post("/")
def create() -> tuple[dict[str, object], int]:
    """Create a new change set in draft state."""

    user = _resolve_current_user()
    with session_scope() as session:
        changeset = ChangeSet(title="Auto from draft", created_by=user, state="draft")
        session.add(changeset)
        session.flush()
        payload = {"ok": True, "id": changeset.id}
    return payload, HTTPStatus.CREATED


@bp.get("/")
def index() -> tuple[list[dict[str, object]], int]:
    """Return a list of change sets with minimal metadata."""

    with session_scope() as session:
        changesets = list(
            session.execute(
                select(ChangeSet).order_by(ChangeSet.created_at.desc())
            ).scalars()
        )
        payload = [
            {"id": changeset.id, "title": changeset.title, "state": changeset.state}
            for changeset in changesets
        ]
    return payload, HTTPStatus.OK
