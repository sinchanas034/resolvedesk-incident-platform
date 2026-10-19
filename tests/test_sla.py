"""Tests for SLA (service level agreement) tracking."""
import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import SLA_HOURS, Incident, create_app, db, utcnow  # noqa: E402


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'sla.db'}",
        "SECRET_KEY": "test",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "pw",
    })


def make_incident(priority, hours_ago, status="Open"):
    return Incident(title=f"{priority} issue", description="Something is broken here",
                    category="Hardware", priority=priority, status=status,
                    reporter_name="Test", reporter_email="test@example.com",
                    created_at=utcnow() - timedelta(hours=hours_ago))


def test_sla_targets_by_priority():
    assert SLA_HOURS == {"Critical": 4, "High": 24, "Medium": 72, "Low": 168}


def test_critical_ticket_overdue_after_4_hours(app):
    with app.app_context():
        assert make_incident("Critical", 5).is_overdue
        assert not make_incident("Critical", 3).is_overdue


def test_low_ticket_not_overdue_within_7_days(app):
    with app.app_context():
        assert not make_incident("Low", 100).is_overdue
        assert make_incident("Low", 200).is_overdue


def test_resolved_ticket_is_never_overdue(app):
    with app.app_context():
        assert not make_incident("Critical", 50, status="Resolved").is_overdue


def test_dashboard_counts_overdue_tickets(app):
    with app.app_context():
        db.session.add_all([make_incident("Critical", 5), make_incident("High", 1),
                            make_incident("Critical", 9, status="Closed")])
        db.session.commit()
    client = app.test_client()
    client.post("/admin/login", data={"username": "admin", "password": "pw"})
    assert client.get("/api/stats").get_json()["overdue"] == 1
    page = client.get("/admin").get_data(as_text=True)
    assert "Overdue: 1" in page
