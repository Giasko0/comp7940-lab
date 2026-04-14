# COMP7940 Telegram Cloud Chatbot

Telegram chatbot for COMP7940 that helps students with:

- a **Virtual Professor** powered by the HKBU GenAI / ChatGPT API
- **profile-based matching** for similar classmates
- **group management** for study groups
- **chat logging** in MongoDB Atlas
- **Docker**-based deployment with **Celery worker** and **Flower monitoring**

## Stack

| Component | Purpose |
| --- | --- |
| Telegram Bot | User interface on Telegram |
| MongoDB Atlas | Cloud database for profiles and chat logs |
| HKBU GenAI API | LLM responses for the virtual professor and matchmaking |
| Redis | Celery broker / backend |
| Celery Worker | Background task processing |
| Flower | Monitoring dashboard for Celery |
| Docker / Docker Compose | Container orchestration |
| GitHub Actions | Cloud deployment to AWS EC2 |

## Services

`docker compose up` starts these containers:

| Service | Description |
| --- | --- |
| `bot` | Telegram bot runtime |
| `worker` | Celery worker for background jobs |
| `flower` | Monitoring UI on port `5555` |
| `redis` | Queue broker and result backend |

## Requirements

- Python 3.12+
- Docker and Docker Compose
- Telegram bot token
- MongoDB Atlas connection string
- HKBU GenAI API key

## Configuration

Create or update `config.ini`:

```ini
[TELEGRAM]
ACCESS_TOKEN = your-telegram-bot-token

[CHATGPT]
API_KEY = your-api-key
BASE_URL = https://genai.hkbu.edu.hk/api/v0/rest
MODEL = gpt-5-mini
API_VER = 2024-12-01-preview

[MONGO]
URI = your-mongodb-atlas-uri
DB_NAME = chatbot_db
COLLECTION_NAME = users

[CELERY]
BROKER_URL = redis://redis:6379/0
RESULT_BACKEND = redis://redis:6379/0
```

## Run locally

```bash
docker compose up --build
```

Then:

- open Telegram and send `/start` to the bot
- open Flower at `http://localhost:5555`

## Deployment

The repository includes a GitHub Actions workflow that SSHes into the EC2 host and runs:

```bash
docker compose up -d --build
```

This keeps the bot, worker, Redis, and monitoring services aligned in the cloud deployment.

## Notes

- Chat messages are logged asynchronously through Celery, with a synchronous fallback if the queue is unavailable.
- Flower gives basic visibility into task execution and queue health.
- For safer production use, keep secrets out of version control and inject them through environment variables or a secrets manager.
