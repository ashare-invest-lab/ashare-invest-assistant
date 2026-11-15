"""PATCH /admin/users/{id}: §7.9 approval, lifecycle, privacy and atomic history.

Real PostgreSQL/Redis cases reuse T-B03's isolated database and session fixtures.
Offline cases retain production current_admin and CSRF, replacing storage only.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import deps
from app.auth.sessions import Session

_spec = importlib.util.spec_from_file_location(
    "t_b150_auth_fixtures", Path(__file__).with_name("test_auth_t_b03.py")
)
_auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_auth)
authdb = _auth.authdb
sql = _auth.sql
app_client = _auth.app_client
mkuser = _auth.mkuser
session = _auth.session
assert_err = _auth.assert_err

API = "/api/v1/admin/users"
ADMIN_USER_KEYS = {
    "id", "username", "display_name", "status", "role", "apply_note", "created_at",
    "register_ip_region", "same_ip_registrations", "same_ip_flag", "review_reason",
    "reviewed_at", "last_login_at",
}


def patch(signed, target, status="approved", reason=None, **extra):
    return signed.client.patch(
        f"{API}/{target}", json={"status": status, "reason": reason, **extra},
        headers={"X-CSRF-Token": signed.csrf},
    )


@pytest.fixture
def offline_client(backend, make_settings, monkeypatch):
    """Exercise route/auth/validation without a DB, failing on unexpected DB use."""
    user_id = uuid.uuid4()
    signed = Session("synthetic", str(user_id), uuid.uuid4().hex, "2026-01-01T00:00:00Z")
    state = SimpleNamespace(user=SimpleNamespace(id=user_id, status="approved", role="admin"),
                            session=signed)

    class ForbiddenEngine:
        def __getattr__(self, name):
            pytest.fail(f"Request unexpectedly reached database: {name}")

    app = backend.main.create_app(make_settings())
    app.dependency_overrides[deps.get_engine] = lambda: ForbiddenEngine()
    app.dependency_overrides[deps.get_session_store] = lambda: SimpleNamespace(
        get=lambda sid: state.session
    )
    monkeypatch.setattr(deps, "load_user", lambda engine, uid: state.user)
    client = TestClient(app)
    try:
        client.cookies.set("csrf_token", signed.csrf_token)
        state.client = client
        state.csrf = signed.csrf_token
        yield state
    finally:
        client.close()


@pytest.mark.unit
@pytest.mark.parametrize("identity", ["anonymous", "user", "pending", "rejected", "disabled"])
@pytest.mark.parametrize("target", ["not-a-uuid", str(uuid.uuid4())])
def test_hidden_before_validation_or_csrf(offline_client, identity, target):
    s = offline_client
    if identity == "anonymous":
        s.session = None
    elif identity == "user":
        s.user.role = "user"
    else:
        s.user.status = identity
    # A malformed body and missing CSRF must never reveal the target or route.
    assert_err(s.client.patch(f"{API}/{target}", json={"status": "unknown"}), 404, "NOT_FOUND")


@pytest.mark.unit
def test_confirmed_admin_csrf_precedes_payload_validation(offline_client):
    s = offline_client
    assert_err(s.client.patch(f"{API}/not-a-uuid", json={"status": "unknown"}),
               403, "CSRF_FAILED")


@pytest.mark.unit
@pytest.mark.parametrize(("payload", "field"), [
    ({"status": "pending", "reason": None}, "status"),
    ({"status": "approved", "reason": "x" * 201}, "reason"),
    ({"status": "approved", "reason": 123}, "reason"),
    ({"status": "approved", "reason": None, "role": "admin"}, "role"),
    ({"reason": None}, "status"),
])
def test_request_schema_is_strict(offline_client, payload, field):
    s = offline_client
    error = assert_err(s.client.patch(f"{API}/{uuid.uuid4()}", json=payload,
                                      headers={"X-CSRF-Token": s.csrf}),
                       400, "VALIDATION_ERROR")
    assert field in _auth.fields(error)


@pytest.mark.unit
def test_admin_invalid_uuid_is_not_found(offline_client):
    assert_err(patch(offline_client, "not-a-uuid"), 404, "NOT_FOUND")


@pytest.mark.unit
def test_admin_cannot_patch_self_before_storage(offline_client):
    assert_err(patch(offline_client, offline_client.user.id, "disabled", "synthetic review"),
               409, "INVALID_STATE_TRANSITION")


@pytest.mark.integration
@pytest.mark.contract
def test_anonymous_and_real_nonadmin_are_hidden(app_client, session):
    target = uuid.uuid4()
    assert_err(app_client().patch(f"{API}/{target}", json={"status": "approved", "reason": None},
                                 headers={"X-CSRF-Token": uuid.uuid4().hex}), 404, "NOT_FOUND")
    assert_err(patch(session(), target), 404, "NOT_FOUND")


@pytest.mark.integration
@pytest.mark.contract
def test_missing_deleted_and_invalid_target(session, mkuser, sql):
    s = session(mkuser(role="admin"))
    assert_err(patch(s, uuid.uuid4()), 404, "NOT_FOUND")
    assert_err(patch(s, "not-a-uuid"), 404, "NOT_FOUND")
    deleted = mkuser(status="pending")
    sql("UPDATE app.users SET deleted_at=now() WHERE id=:id", id=deleted.id)
    assert_err(patch(s, deleted.id), 404, "NOT_FOUND")


@pytest.mark.integration
@pytest.mark.contract
@pytest.mark.parametrize(("old", "new", "action", "audit_action", "reason"), [
    ("pending", "approved", "approve", "user.approved", None),
    ("rejected", "approved", "approve", "user.approved", None),
    ("pending", "rejected", "reject", "user.rejected", "synthetic rejection"),
    ("approved", "disabled", "disable", "user.disabled", "synthetic disable"),
    ("disabled", "approved", "enable", "user.enabled", "synthetic enable"),
])
def test_transitions_return_list_projection_and_append_history(
    session, mkuser, sql, app_client, authdb, old, new, action, audit_action, reason
):
    s = session(mkuser(role="admin"))
    target = mkuser(status=old)
    target_session = session(target) if old == "approved" else None
    response = patch(s, target.id, new, reason)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == ADMIN_USER_KEYS
    assert body["id"] == target.id and body["username"] == target.username
    assert body["status"] == new and body["role"] == "user"
    assert body["review_reason"] == reason
    assert body["register_ip_region"] is None
    assert type(body["same_ip_registrations"]) is int
    assert type(body["same_ip_flag"]) is bool
    for field in ("created_at", "reviewed_at", "last_login_at"):
        if body[field] is not None:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00", body[field])
    listing = s.client.get(API, params={"q": target.username}).json()["items"]
    assert listing == [body]
    user = sql("SELECT status, reviewed_at, reviewed_by::text FROM app.users WHERE id=:id",
               id=target.id)[0]
    assert user.status == new and user.reviewed_at is not None and user.reviewed_by == s.user.id
    reviews = sql("SELECT action, reason, admin_id::text FROM app.account_reviews WHERE user_id=:id",
                  id=target.id)
    assert [(r.action, r.reason, r.admin_id) for r in reviews] == [(action, reason, s.user.id)]
    audits = sql("SELECT action, actor_id::text, target_type, detail FROM app.audit_logs "
                 "WHERE target_id=:id AND action=:action", id=target.id, action=audit_action)
    assert len(audits) == 1
    audit = audits[0]
    assert audit.actor_id == s.user.id and audit.target_type == "user"
    assert audit.detail["old_status"] == old and audit.detail["new_status"] == new
    if target_session is not None:
        assert not authdb.redis.exists(_auth.sid_key(target_session.sid))
        assert not _auth.user_session_keys(authdb, target.id)
        assert_err(target_session.client.get("/api/v1/me"), 401, "AUTH_REQUIRED")
    if new == "approved":
        login = app_client().post("/api/v1/auth/login", json={
            "username": target.username, "password": target.password,
        })
        assert login.status_code == 200, login.text


@pytest.mark.integration
@pytest.mark.contract
@pytest.mark.parametrize(("old", "new"), [
    ("pending", "rejected"), ("approved", "disabled"), ("disabled", "approved"),
])
@pytest.mark.parametrize("reason", [None, "", "   ", pytest.param(..., id="omitted")])
def test_required_reason_is_nonblank_and_does_not_mutate(session, mkuser, sql, old, new, reason):
    s = session(mkuser(role="admin"))
    target = mkuser(status=old)
    payload = {"status": new}
    if reason is not ...:
        payload["reason"] = reason
    response = s.client.patch(f"{API}/{target.id}", json=payload,
                              headers={"X-CSRF-Token": s.csrf})
    error = assert_err(response, 400, "VALIDATION_ERROR")
    assert "reason" in _auth.fields(error)
    assert sql("SELECT status FROM app.users WHERE id=:id", id=target.id)[0].status == old
    assert not sql("SELECT id FROM app.account_reviews WHERE user_id=:id", id=target.id)
    assert not sql("SELECT id FROM app.audit_logs WHERE target_id=:id AND action LIKE 'user.%'",
                   id=target.id)


@pytest.mark.integration
@pytest.mark.contract
@pytest.mark.parametrize(("old", "new"), [
    ("approved", "rejected"), ("pending", "disabled"), ("rejected", "disabled"),
    ("disabled", "rejected"), ("pending", "pending"),
    ("approved", "approved"), ("rejected", "rejected"), ("disabled", "disabled"),
])
def test_invalid_transition(session, mkuser, sql, old, new):
    s = session(mkuser(role="admin"))
    target = mkuser(status=old)
    # pending is not an accepted request status at all.
    status, code = (400, "VALIDATION_ERROR") if new == "pending" else (409, "INVALID_STATE_TRANSITION")
    assert_err(patch(s, target.id, new, "synthetic review"), status, code)
    assert sql("SELECT status FROM app.users WHERE id=:id", id=target.id)[0].status == old
    assert not sql("SELECT id FROM app.account_reviews WHERE user_id=:id", id=target.id)


@pytest.mark.integration
@pytest.mark.contract
def test_real_admin_cannot_patch_self(session, mkuser):
    s = session(mkuser(role="admin"))
    assert_err(patch(s, s.user.id, "disabled", "synthetic self review"),
               409, "INVALID_STATE_TRANSITION")


@pytest.mark.integration
@pytest.mark.contract
def test_audit_failure_rolls_back_user_and_review(session, mkuser, sql, monkeypatch):
    from app.auth import service

    s = session(mkuser(role="admin"))
    target = mkuser(status="pending")

    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(service, "audit", fail_audit)
    assert_err(patch(s, target.id), 500, "INTERNAL_ERROR")
    row = sql("SELECT status, reviewed_at, reviewed_by FROM app.users WHERE id=:id", id=target.id)[0]
    assert row.status == "pending" and row.reviewed_at is None and row.reviewed_by is None
    assert not sql("SELECT id FROM app.account_reviews WHERE user_id=:id", id=target.id)
