"""
Celery application configuration and initialization
"""

import configparser
import logging

from celery import Celery

config = configparser.ConfigParser()
config.read("config.ini")

broker_url = config.get("CELERY", "BROKER_URL", fallback="redis://localhost:6379/0")
result_backend = config.get(
    "CELERY", "RESULT_BACKEND", fallback="redis://localhost:6379/0"
)

app = Celery('comp7940_bot')
logger = logging.getLogger(__name__)

# Celery Configuration
app.conf.update(
    broker_url=broker_url,
    result_backend=result_backend,
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
)


@app.task(bind=True, max_retries=3)
def save_message_async(self, user_id, username, user_text, bot_text):
    from Mongo_db import save_chat_message

    try:
        result = save_chat_message(user_id, user_text, bot_text, username=username)
        logger.info("Message saved for user %s: %s", user_id, result)
        return {"status": "success", "result": str(result)}
    except Exception as exc:
        logger.error("Failed to save message for user %s: %s", user_id, exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@app.task(bind=True, max_retries=3)
def process_search_async(self, user_id, top_k=5):
    from Search import search_similar_users

    try:
        results = search_similar_users(user_id, top_k=top_k)
        logger.info("Search completed for user %s: %s results", user_id, len(results))
        return {"status": "success", "results": results}
    except Exception as exc:
        logger.error("Search failed for user %s: %s", user_id, exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@app.task(bind=True, max_retries=3)
def generate_chat_response_async(self, message):
    from ChatGPT_HKBU import ChatGPT
    from configparser import ConfigParser

    try:
        runtime_config = ConfigParser()
        runtime_config.read("config.ini")
        gpt = ChatGPT(runtime_config)
        response = gpt.submit(message)
        logger.info("Generated chat response")
        return {"status": "success", "response": response}
    except Exception as exc:
        logger.error("Failed to generate chat response: %s", exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
