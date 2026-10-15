"""Incident & Service Request Platform - Flask application."""
import hmac
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import quote_plus

from flask import (Blueprint, Flask, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import case, func, text

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

db = SQLAlchemy()
bp = Blueprint("main", __name__)

PRIORITIES = ["Low", "Medium", "High", "Critical"]
STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
CATEGORIES = ["IT / Network", "Hardware", "Software", "Electrical",
              "Plumbing", "Facilities", "Other"]
ACTIVE_STATUSES = ["Open", "In Progress"]
DONE_STATUSES = ["Resolved", "Closed"]
# SLA: hours allowed to resolve a request, by priority
SLA_HOURS = {"Critical": 4, "High": 24, "Medium": 72, "Low": 168}


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class Incident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    priority = db.Column(db.String(20), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="Open", index=True)
    reporter_name = db.Column(db.String(100), nullable=False)
    reporter_email = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(150))
    assignee = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    resolved_at = db.Column(db.DateTime)
    updates = db.relationship("IncidentUpdate", backref="incident",
                              order_by="IncidentUpdate.created_at",
                              cascade="all, delete-orphan")

    @property
    def ref(self):
        return f"INC-{self.id:05d}"

    @property
    def due_at(self):
        return self.created_at + timedelta(hours=SLA_HOURS.get(self.priority, 72))

    @property
    def is_overdue(self):
        return self.status in ACTIVE_STATUSES and utcnow() > self.due_at

    def to_dict(self):
        return {
            "id": self.id,
            "ref": self.ref,
            "title": self.title,
            "category": self.category,
            "priority": self.priority,
            "status": self.status,
            "assignee": self.assignee,
            "location": self.location,
            "created_at": self.created_at.isoformat() + "Z",
            "resolved_at": self.resolved_at.isoformat() + "Z" if self.resolved_at else None,
        }


class IncidentUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey("incident.id"), nullable=False, index=True)
    author = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url and os.environ.get("RDS_HOSTNAME"):
        # Elastic Beanstalk injects these when an RDS database is attached
        url = "postgresql://{u}:{p}@{h}:{port}/{name}".format(
            u=os.environ.get("RDS_USERNAME", ""),
            p=quote_plus(os.environ.get("RDS_PASSWORD", "")),
            h=os.environ["RDS_HOSTNAME"],
            port=os.environ.get("RDS_PORT", "5432"),
            name=os.environ.get("RDS_DB_NAME", "ebdb"),
        )
    if not url:
        os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)
        url = "sqlite:///" + os.path.join(BASE_DIR, "instance", "incidents.db")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def is_admin():
    return bool(session.get("is_admin"))


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("main.admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def remember_ticket(incident_id):
    tickets = set(session.get("my_tickets", []))
    tickets.add(incident_id)
    session["my_tickets"] = sorted(tickets)


def can_view(incident):
    return is_admin() or incident.id in session.get("my_tickets", [])


def add_update(incident, author, message):
    db.session.add(IncidentUpdate(incident=incident, author=author, message=message))


# --------------------------------------------------------------------------
# Public routes
# --------------------------------------------------------------------------
@bp.route("/", methods=["GET"])
def index():
    return render_template("index.html", form={})


@bp.route("/report", methods=["POST"])
def report():
    form = {k: (request.form.get(k) or "").strip() for k in
            ["title", "description", "category", "priority",
             "reporter_name", "reporter_email", "location"]}
    errors = []
    if not form["title"] or len(form["title"]) > 150:
        errors.append("Please give the issue a short title (up to 150 characters).")
    if len(form["description"]) < 10:
        errors.append("Please describe the issue in a little more detail.")
    if form["category"] not in CATEGORIES:
        errors.append("Please choose a category.")
    if form["priority"] not in PRIORITIES:
        errors.append("Please choose a priority.")
    if not form["reporter_name"]:
        errors.append("Please enter your name.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", form["reporter_email"]):
        errors.append("Please enter a valid email address.")
    if errors:
        for e in errors:
            flash(e, "error")
        return render_template("index.html", form=form), 400

    incident = Incident(
        title=form["title"], description=form["description"],
        category=form["category"], priority=form["priority"],
        reporter_name=form["reporter_name"],
        reporter_email=form["reporter_email"].lower(),
        location=form["location"] or None,
    )
    db.session.add(incident)
    db.session.flush()
    add_update(incident, "System", "Request created with status Open.")
    db.session.commit()
    remember_ticket(incident.id)
    logging.getLogger("incidents").info(
        "incident_created id=%s priority=%s category=%s",
        incident.id, incident.priority, incident.category)
    flash(f"Your request {incident.ref} has been submitted. Save this number to track it.", "success")
    return redirect(url_for("main.ticket", incident_id=incident.id))


@bp.route("/track", methods=["GET", "POST"])
def track():
    if request.method == "POST":
        raw = (request.form.get("ticket") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        digits = re.sub(r"\D", "", raw)
        incident = db.session.get(Incident, int(digits)) if digits else None
        if incident and hmac.compare_digest(incident.reporter_email, email):
            remember_ticket(incident.id)
            return redirect(url_for("main.ticket", incident_id=incident.id))
        flash("We couldn't find a request with that number and email.", "error")
    return render_template("track.html")


@bp.route("/ticket/<int:incident_id>")
def ticket(incident_id):
    incident = db.get_or_404(Incident, incident_id)
    if not can_view(incident):
        flash("Enter your ticket number and email to view this request.", "info")
        return redirect(url_for("main.track"))
    return render_template("ticket.html", incident=incident,
                           statuses=STATUSES, priorities=PRIORITIES,
                           admin=is_admin())


@bp.route("/ticket/<int:incident_id>/comment", methods=["POST"])
def comment(incident_id):
    incident = db.get_or_404(Incident, incident_id)
    if not can_view(incident):
        return redirect(url_for("main.track"))
    message = (request.form.get("message") or "").strip()
    if message:
        author = "Support team" if is_admin() else incident.reporter_name
        add_update(incident, author, message)
        incident.updated_at = utcnow()
        db.session.commit()
        flash("Comment added.", "success")
    return redirect(url_for("main.ticket", incident_id=incident.id))


# --------------------------------------------------------------------------
# Admin routes
# --------------------------------------------------------------------------
@bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    from flask import current_app as app
    if request.method == "POST":
        user_ok = hmac.compare_digest(request.form.get("username", ""), app.config["ADMIN_USERNAME"])
        pass_ok = hmac.compare_digest(request.form.get("password", ""), app.config["ADMIN_PASSWORD"])
        if user_ok and pass_ok:
            session["is_admin"] = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//")
                            else url_for("main.admin"))
        flash("Invalid username or password.", "error")
    return render_template("admin_login.html")


@bp.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Signed out.", "info")
    return redirect(url_for("main.index"))


def dashboard_stats():
    by_status = dict(db.session.execute(
        db.select(Incident.status, func.count()).group_by(Incident.status)).all())
    open_by_priority = dict(db.session.execute(
        db.select(Incident.priority, func.count())
        .where(Incident.status.in_(ACTIVE_STATUSES))
        .group_by(Incident.priority)).all())
    resolved = db.session.execute(
        db.select(Incident.created_at, Incident.resolved_at)
        .where(Incident.resolved_at.isnot(None))
        .order_by(Incident.resolved_at.desc()).limit(500)).all()
    active = db.session.execute(
        db.select(Incident.created_at, Incident.priority)
        .where(Incident.status.in_(ACTIVE_STATUSES))).all()
    now = utcnow()
    overdue = sum(1 for c, p in active
                  if now > c + timedelta(hours=SLA_HOURS.get(p, 72)))
    avg_hours = None
    if resolved:
        avg_hours = round(sum((r - c).total_seconds() for c, r in resolved)
                          / len(resolved) / 3600, 1)
    return {
        "total": sum(by_status.values()),
        "by_status": {s: by_status.get(s, 0) for s in STATUSES},
        "open_by_priority": {p: open_by_priority.get(p, 0) for p in PRIORITIES},
        "avg_resolution_hours": avg_hours,
        "overdue": overdue,
    }


@bp.route("/admin")
@admin_required
def admin():
    status = request.args.get("status", "")
    priority = request.args.get("priority", "")
    q = request.args.get("q", "").strip()
    stmt = db.select(Incident)
    if status == "active":
        stmt = stmt.where(Incident.status.in_(ACTIVE_STATUSES))
    elif status in STATUSES:
        stmt = stmt.where(Incident.status == status)
    if priority in PRIORITIES:
        stmt = stmt.where(Incident.priority == priority)
    if q:
        stmt = stmt.where(Incident.title.ilike(f"%{q}%"))
    priority_rank = case({"Critical": 0, "High": 1, "Medium": 2, "Low": 3},
                         value=Incident.priority)
    stmt = stmt.order_by(priority_rank, Incident.created_at.desc())
    page = db.paginate(stmt, page=request.args.get("page", 1, type=int),
                       per_page=15, error_out=False)
    return render_template("admin.html", page=page, stats=dashboard_stats(),
                           statuses=STATUSES, priorities=PRIORITIES,
                           filters={"status": status, "priority": priority, "q": q})


@bp.route("/admin/ticket/<int:incident_id>/update", methods=["POST"])
@admin_required
def admin_update(incident_id):
    incident = db.get_or_404(Incident, incident_id)
    changes = []
    new_status = request.form.get("status")
    if new_status in STATUSES and new_status != incident.status:
        changes.append(f"Status changed from {incident.status} to {new_status}.")
        incident.status = new_status
        if new_status in DONE_STATUSES and not incident.resolved_at:
            incident.resolved_at = utcnow()
        elif new_status in ACTIVE_STATUSES:
            incident.resolved_at = None
    new_priority = request.form.get("priority")
    if new_priority in PRIORITIES and new_priority != incident.priority:
        changes.append(f"Priority changed from {incident.priority} to {new_priority}.")
        incident.priority = new_priority
    new_assignee = (request.form.get("assignee") or "").strip() or None
    if new_assignee != incident.assignee:
        changes.append(f"Assigned to {new_assignee}." if new_assignee else "Unassigned.")
        incident.assignee = new_assignee
    note = (request.form.get("message") or "").strip()
    if changes:
        add_update(incident, "Support team", " ".join(changes))
    if note:
        add_update(incident, "Support team", note)
    if changes or note:
        incident.updated_at = utcnow()
        db.session.commit()
        logging.getLogger("incidents").info("incident_updated id=%s changes=%s",
                                            incident.id, "; ".join(changes) or "comment")
        flash("Request updated.", "success")
    return redirect(url_for("main.ticket", incident_id=incident.id))


# --------------------------------------------------------------------------
# API + health
# --------------------------------------------------------------------------
@bp.route("/api/incidents")
def api_incidents():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401
    limit = min(request.args.get("limit", 50, type=int), 200)
    rows = db.session.execute(
        db.select(Incident).order_by(Incident.created_at.desc()).limit(limit)).scalars()
    return jsonify([r.to_dict() for r in rows])


@bp.route("/api/stats")
def api_stats():
    if not is_admin():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(dashboard_stats())


@bp.route("/health")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "database": "ok",
                        "version": os.environ.get("APP_VERSION", "dev")}), 200
    except Exception:  # noqa: BLE001
        logging.getLogger("incidents").exception("health_check_failed")
        return jsonify({"status": "error", "database": "unreachable"}), 503


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------
def create_app(test_config=None):
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        SQLALCHEMY_DATABASE_URI=database_url(),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", "admin123"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    if app.config["ADMIN_PASSWORD"] == "admin123" and not app.config.get("TESTING"):
        app.logger.warning("ADMIN_PASSWORD is the default. Set it as an environment variable!")

    db.init_app(app)
    app.register_blueprint(bp)

    @app.template_filter("dt")
    def format_dt(value):
        return value.strftime("%d %b %Y, %H:%M UTC") if value else "-"

    @app.context_processor
    def inject_globals():
        return {"is_admin": is_admin(), "categories": CATEGORIES,
                "all_priorities": PRIORITIES}

    @app.before_request
    def start_timer():
        g.start = time.perf_counter()

    @app.after_request
    def log_and_harden(response):
        if request.path != "/health" and not request.path.startswith("/static"):
            ms = (time.perf_counter() - g.get("start", time.perf_counter())) * 1000
            logging.getLogger("http").info("%s %s %s %.1fms", request.method,
                                           request.path, response.status_code, ms)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.errorhandler(404)
    def not_found(_):
        return render_template("error.html", code=404,
                               message="That page doesn't exist."), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template("error.html", code=500,
                               message="Something went wrong on our side."), 500

    with app.app_context():
        try:
            db.create_all()
        except Exception:  # noqa: BLE001 - another worker may be creating tables
            app.logger.exception("create_all failed (may already exist)")
        if not app.config.get("TESTING"):
            # Don't share pooled connections with forked gunicorn workers
            db.engine.dispose()

    return app
