# ResolveDesk — Incident & Service Request Platform

Built for the **Build on Elastic Beanstalk** hackathon by TrainWithShubham (theme: *How DevOps Evolves India*).

## The problem
Colleges, hospitals, housing societies and small businesses report technical and facility issues over WhatsApp, phone calls and spreadsheets. Requests get lost, duplicated, nobody owns them, and there is no way to measure how fast they get fixed.

## The solution
A central web platform where:
- **Anyone** reports an issue (title, description, category, priority, location) and gets a ticket number like `INC-00012`.
- **Reporters** track their ticket with ticket number + email, and comment on it.
- **The support team** logs in to a dashboard to filter, prioritise, assign and resolve requests. Every change is recorded in an activity timeline.
- **Metrics**: open / in-progress / resolved counts, active requests by priority, and average time to resolve.

## Tech stack
| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask, SQLAlchemy |
| Frontend | Server-rendered HTML (Jinja) + CSS, mobile-friendly |
| Database | PostgreSQL (Amazon RDS) in production, SQLite for quick local runs |
| App server | Gunicorn |
| Container | Docker |
| Cloud | AWS Elastic Beanstalk (Docker platform) |
| CI/CD | GitHub Actions: test → build image → deploy |
| Observability | `/health` endpoint, EB enhanced health, CloudWatch Logs, request timing logs |
| AI assistant | Claude (code generation and review) |

## Architecture
```
Users ──▶ Elastic Beanstalk (Load Balancer + Auto Scaling group)
              │
              ▼
        EC2 instances running the Docker container (Gunicorn + Flask)
              │                        │
              ▼                        ▼
        Amazon RDS PostgreSQL     CloudWatch Logs / EB Health
```
The app is **stateless** (sessions live in signed cookies, data lives in RDS), so EB can add or remove instances freely as traffic changes.

## Run locally

**Option A — Python only (SQLite):**
```bash
pip install -r requirements-dev.txt
python -m pytest -q          # run tests
python wsgi.py               # open http://localhost:8000
```

**Option B — Docker + PostgreSQL (same as production):**
```bash
docker compose -f docker-compose.dev.yml up --build
```
Support login: username `admin`, password `admin123` (local only — change it in production).

## Deploy to AWS Elastic Beanstalk

### 1. Create the environment (AWS Console)
1. Open **Elastic Beanstalk → Create application**.
2. Application name: `incident-platform`. Environment name: `incident-platform-prod`.
3. Platform: **Docker**, branch **Docker running on 64bit Amazon Linux 2023**.
4. Application code: **Upload your code** → upload a zip of this folder (see below).
5. Presets: **Single instance** (cheapest, good for the demo) or **High availability** (load balancer + auto scaling — shows scaling).
6. Service role / EC2 instance profile: let the console create the defaults (`aws-elasticbeanstalk-service-role`, `aws-elasticbeanstalk-ec2-role`).
7. **Database (optional but recommended)**: in *Set up networking, database and tags*, enable a database → Engine **postgres**, class `db.t3.micro`, set a username and password. EB passes `RDS_HOSTNAME`, `RDS_USERNAME`, etc. to the app automatically and the app uses them.
   - Without a database, the app falls back to SQLite inside the container, which works for a demo but **data is lost on every redeploy**.
8. **Environment properties** (Configure updates, monitoring and logging → Environment properties):
   - `SECRET_KEY` = a long random string
   - `ADMIN_USERNAME` = `admin`
   - `ADMIN_PASSWORD` = a strong password
9. Create. After ~5–10 minutes, open the environment URL and check `/health` returns `{"status": "ok"}`.

Make the zip from inside this folder:
```bash
zip -r deploy.zip . -x '.git/*' 'tests/*' '__pycache__/*' 'instance/*'
```

### 2. Turn on auto scaling (High availability environments)
Configuration → **Capacity**: Min instances `1`, Max `3`, scaling trigger **CPUUtilization**, upper threshold `70`, lower `30`.

### 3. Set up CI/CD (GitHub Actions)
1. Push this folder to a GitHub repository (`main` branch).
2. In AWS IAM, create a user for deployments with the `AdministratorAccess-AWSElasticBeanstalk` policy and create an access key.
3. In GitHub → repo **Settings → Secrets and variables → Actions**:
   - Secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
   - Variables: `EB_APP_NAME` = `incident-platform`, `EB_ENV_NAME` = `incident-platform-prod`, `AWS_REGION` = e.g. `ap-south-1`
4. Every push to `main` now runs tests, builds the Docker image, and deploys a new version to Elastic Beanstalk. Pull requests run tests only.

### 4. Monitoring
- **Health**: EB uses `/health` (checks the database connection too) — see `.ebextensions/01-app.config`.
- **Logs**: streamed to CloudWatch Logs (`/aws/elasticbeanstalk/<env>/...`). Each request is logged with method, path, status and duration; ticket creation and updates are logged as events.

## How it scales
- **Horizontal scaling**: stateless containers behind the EB load balancer; Auto Scaling adds instances on high CPU.
- **Managed database**: RDS PostgreSQL with indexed columns (status, priority, created_at) and paginated queries.
- **Safe deploys**: CI runs tests before any deploy; EB keeps every version so you can roll back in one click.
- **Next steps**: multi-organisation support, email/Slack notifications, SLA timers per priority, Redis caching for dashboard stats.

## API (support team, after login)
- `GET /api/incidents?limit=50` — latest incidents as JSON
- `GET /api/stats` — dashboard metrics as JSON
- `GET /health` — public health check
