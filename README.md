# ResolveDesk — Incident & Service Request Platform

🌐 **Live demo:** http://resolvedesk-sinchana.us-east-1.elasticbeanstalk.com
🗄️ **Database:** Amazon RDS PostgreSQL – tickets are stored permanently
⚙️ **CI/CD:** every push to `main` is tested and deployed automatically by GitHub Actions

Built for the **Build on Elastic Beanstalk** hackathon by TrainWithShubham (theme: *How DevOps Evolves India*).

---

## The problem
Colleges, hospitals, housing societies and small businesses still report technical and facility issues over WhatsApp, phone calls and spreadsheets. Requests get lost or duplicated, nobody clearly owns them, and there is no way to measure how fast they get fixed.

## The solution
ResolveDesk is one central place to **report → track → assign → resolve** every issue.

| Who | What they can do |
|---|---|
| **Anyone** | Report an issue (title, description, category, priority, location) and get a ticket number like `INC-00012` |
| **Reporter** | Track the ticket with ticket number + email, see every update, add comments |
| **Support team** | Log in to a dashboard, filter and search, change status and priority, assign an owner, reply to the reporter |
| **Managers** | See live metrics: open / in progress / resolved, active tickets by priority, **SLA overdue count**, average time to resolve |

### SLA tracking
Each priority has a target resolution time. Active tickets that pass it are flagged **⚠️ Overdue** on the dashboard.

| Priority | Target |
|---|---|
| Critical | 4 hours |
| High | 24 hours |
| Medium | 3 days |
| Low | 7 days |

---

## Architecture

```
                 ┌──────────────────────────────┐
  Developer ───▶ │ GitHub (code)                │
   git push      │  └─ GitHub Actions (CI/CD)   │
                 │      1. run automated tests  │
                 │      2. build Docker image   │
                 │      3. deploy new version   │
                 └──────────────┬───────────────┘
                                ▼
  Users ──HTTP──▶ ┌──────────────────────────────────────────┐
                  │ AWS Elastic Beanstalk (us-east-1)        │
                  │  EC2 t3.micro in an Auto Scaling group   │
                  │  └─ Docker: Gunicorn + Flask app         │
                  │  Enhanced health checks on /health       │
                  └───────┬───────────────────────┬──────────┘
                          ▼                       ▼
            ┌──────────────────────┐   ┌──────────────────────────┐
            │ Amazon RDS           │   │ Amazon CloudWatch Logs   │
            │ PostgreSQL           │   │ + SNS email alerts       │
            │ (private, port 5432  │   │   (environment events)   │
            │  open only to the    │   └──────────────────────────┘
            │  app's security grp) │
            └──────────────────────┘
```

## Tech stack
| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask, SQLAlchemy |
| Frontend | Server-rendered HTML (Jinja) + CSS, mobile-friendly |
| Database | Amazon RDS PostgreSQL (production), SQLite (local development) |
| App server | Gunicorn (3 workers) |
| Container | Docker (non-root user, built-in health check) |
| Cloud | AWS Elastic Beanstalk – Docker on Amazon Linux 2023 |
| CI/CD | GitHub Actions: test → build image → deploy |
| Monitoring | `/health` endpoint (checks the database), EB enhanced health, CloudWatch Logs, email notifications via SNS |
| Security | IAM roles with least privilege, secrets in GitHub Secrets and EB environment properties, RDS not publicly accessible |
| AI assistant | Claude (code generation and review) |

---

## DevOps practices used
- **Infrastructure on a managed platform:** Elastic Beanstalk provisions EC2, the Auto Scaling group, security groups and monitoring.
- **Containerisation:** the same Docker image runs locally and on AWS.
- **CI/CD:** GitHub Actions runs 9 automated tests on every push and blocks the deploy if any fail. Every deploy creates a versioned application in Elastic Beanstalk, so rolling back is one click.
- **Self-healing:** if the EC2 instance stops or fails health checks, the Auto Scaling group replaces it automatically (tested during development).
- **Stateless app + managed database:** all data lives in RDS, so servers can be replaced, redeployed or scaled out without losing tickets.
- **Observability:** health endpoint, request logs with response times, CloudWatch log streaming, and email alerts on environment events.
- **Secure configuration:** no secrets in the code. AWS keys are stored in GitHub Secrets; app passwords and the database URL are Elastic Beanstalk environment properties.

## How it scales
- The app is **stateless** (sessions are signed cookies, data is in RDS), so Elastic Beanstalk can run many instances behind a load balancer by switching the environment type to *Load balanced* with Auto Scaling rules (e.g. add an instance above 70% CPU).
- Database queries use indexed columns (status, priority, created date) and the dashboard is paginated.
- RDS can be scaled vertically or given read replicas as usage grows.
- Next steps: multi-organisation support, HTTPS with a custom domain, email/Slack notifications to reporters, Redis caching for dashboard stats.

---

## Run locally
```bash
pip install -r requirements-dev.txt
python -m pytest -q          # run the 9 tests
python wsgi.py               # open http://localhost:8000
```
Or with Docker + PostgreSQL (same as production):
```bash
docker compose -f docker-compose.dev.yml up --build
```

## Configuration (environment variables)
| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string (RDS). SQLite is used if not set. |
| `SECRET_KEY` | Signs session cookies |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Support team login |

## API (support team, after login)
- `GET /api/incidents?limit=50` – latest incidents as JSON
- `GET /api/stats` – dashboard metrics as JSON (including overdue count)
- `GET /health` – public health check used by Elastic Beanstalk
