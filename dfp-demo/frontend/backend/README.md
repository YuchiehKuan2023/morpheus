# DFP Demo Backend API

Backend API server for the Digital Fingerprinting Platform Dashboard.

## Features

- REST API endpoints for dashboard data
- Real-time anomaly detection monitoring via Kafka
- MLflow integration for model metadata
- User profile and statistics endpoints

## Setup

**1. Install dependencies:**

```bash
pip install -r requirements.txt
```

**2. Configure environment variables in `.env`:**

```bash
# Copy the example file
cp .env.example .env

# Edit .env with your configuration
```

### Environment Variables

| Variable       | Description                            | Default                 | Example                                                 |
| -------------- | -------------------------------------- | ----------------------- | ------------------------------------------------------- |
| `ENVIRONMENT`  | Deployment environment                 | `development`           | `production`, `staging`                                 |
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated) | `http://localhost:5173` | `https://app.example.com,https://dashboard.example.com` |
| `HOST`         | Server bind address                    | `0.0.0.0`               | `127.0.0.1`                                             |
| `PORT`         | Server port                            | `8000`                  | `8080`                                                  |
| `LOG_LEVEL`    | Logging level                          | `info`                  | `debug`, `warning`, `error`                             |

**Security Note:** For production deployments, always set `CORS_ORIGINS` to specific domains. Never use wildcard patterns in production.

**3. Run the server:**

```bash
python main.py
```

Or with uvicorn:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

- `GET /` - Root endpoint with API info
- `GET /api/health` - Health check
- `GET /api/stats` - System statistics
- `GET /api/anomalies` - List anomalies
- `GET /api/users` - List monitored users
- `GET /docs` - Interactive API documentation (Swagger UI)

## Development

The API runs on port **8000** by default (configurable via `PORT` environment variable).

Access the interactive API documentation at:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
