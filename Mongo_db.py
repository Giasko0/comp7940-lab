import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

collection_cache: Optional[Collection] = None


def get_collection() -> Collection:
    global collection_cache
    if collection_cache is not None:
        return collection_cache

    mongo_uri = os.getenv(
        "MONGO_URI", "mongodb+srv://Gino:1234@chatbot.nejdxh9.mongodb.net/"
    )
    db_name = os.getenv("MONGO_DB_NAME", "chatbot_db")
    collection_name = os.getenv("MONGO_COLLECTION_NAME", "users")

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    collection_cache = client[db_name][collection_name]
    collection_cache.create_index("telegram_user_id", unique=True)
    collection_cache.create_index("username")
    return collection_cache


def get_user_profile(telegram_user_id: int) -> Optional[Dict[str, Any]]:
    collection = get_collection()
    return collection.find_one({"telegram_user_id": telegram_user_id}, {"_id": 0})


def get_user_profile_by_username(username: str) -> Optional[Dict[str, Any]]:
    if not username:
        return None

    collection = get_collection()
    return collection.find_one({"username": username}, {"_id": 0})


def save_user_profile(
    telegram_user, questionnaire: Dict[str, Any], completed: bool = True
) -> bool:
    collection = get_collection()
    document = {
        "telegram_user_id": telegram_user.id,
        "username": telegram_user.username or "unknown_user",
        "in_group": False,
        "completed": completed,
        "age": questionnaire.get("age"),
        "gender": questionnaire.get("gender"),
        "hobbies": questionnaire.get("hobbies", []),
        "language": questionnaire.get("language"),
        "updated_at": datetime.now(timezone.utc),
    }

    try:
        collection.update_one(
            {"telegram_user_id": telegram_user.id},
            {
                "$set": document,
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
    except PyMongoError:
        return False

    return True


def save_chat_message(telegram_user, user_text: str, bot_text: str) -> bool:
    collection = get_collection()
    try:
        collection.update_one(
            {"telegram_user_id": telegram_user.id},
            {
                "$set": {
                    "username": telegram_user.username or "unknown_user",
                    "updated_at": datetime.now(timezone.utc),
                },
                "$setOnInsert": {
                    "created_at": datetime.now(timezone.utc),
                    "completed": False,
                },
                "$push": {
                    "messages": {
                        "user_text": user_text,
                        "bot_text": bot_text,
                        "created_at": datetime.now(timezone.utc),
                    }
                },
            },
            upsert=True,
        )
    except PyMongoError:
        return False

    return True
