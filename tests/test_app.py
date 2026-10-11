import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import Incident, create_app, db  # noqa: E402


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "SECRET_KEY": "test",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "pw",
    })
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def report(client, **overrides):
    data = {"title": "Wi-Fi down in Lab 3", "description": "No internet since 9am on all systems",
            "category": "IT / Network", "priority": "High",
            "reporter_name": "Asha", "reporter_email": "asha@example.com"}
    data.update(overrides)
    return client.post("/report", data=data)


def login(client):
    return client.post("/admin/login", data={"username": "admin", "password": "pw"})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_home_page(client):
    assert client.get("/").status_code == 200


def test_report_creates_ticket_and_reporter_can_view(client, app):
    r = report(client)
    assert r.status_code == 302
    assert "/ticket/1" in r.headers["Location"]
    page = client.get("/ticket/1")
    assert b"INC-00001" in page.data
    with app.app_context():
        assert db.session.get(Incident, 1).status == "Open"


def test_invalid_report_rejected(client):
    r = report(client, reporter_email="not-an-email", priority="Whatever")
    assert r.status_code == 400


def test_other_users_cannot_view_ticket(client, app):
    report(client)
    other = app.test_client()
    r = other.get("/ticket/1")
    assert r.status_code == 302 and "/track" in r.headers["Location"]


def test_track_with_ticket_and_email(client, app):
    report(client)
    other = app.test_client()
    r = other.post("/track", data={"ticket": "INC-00001", "email": "ASHA@example.com"})
    assert r.status_code == 302
    assert other.get("/ticket/1").status_code == 200
    bad = app.test_client().post("/track", data={"ticket": "1", "email": "x@example.com"})
    assert b"couldn" in bad.data


def test_admin_requires_login(client):
    assert client.get("/admin").status_code == 302
    assert client.get("/api/incidents").status_code == 401


def test_admin_resolves_ticket(client, app):
    report(client)
    login(client)
    assert client.get("/admin").status_code == 200
    r = client.post("/admin/ticket/1/update",
                    data={"status": "Resolved", "priority": "High", "assignee": "Network team"})
    assert r.status_code == 302
    with app.app_context():
        inc = db.session.get(Incident, 1)
        assert inc.status == "Resolved"
        assert inc.resolved_at is not None
        assert inc.assignee == "Network team"
    stats = client.get("/api/stats").get_json()
    assert stats["by_status"]["Resolved"] == 1


def test_comment(client):
    report(client)
    r = client.post("/ticket/1/comment", data={"message": "Still not working"})
    assert r.status_code == 302
    assert b"Still not working" in client.get("/ticket/1").data
