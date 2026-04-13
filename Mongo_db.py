import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

# Fetch values from your docker-compose environment variables
mongo_uri = os.getenv(
    "MONGO_URI", "mongodb+srv://Gino:1234@chatbot.nejdxh9.mongodb.net/"
)
db_name = os.getenv("MONGO_DB_NAME", "chatbot_db")

# Initialize GLOBALLY (This removes the Pylance errors)
client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
db = client[db_name]  # Now 'db' is defined for the whole file
users_col = db["users"]  # Now 'users_col' is defined
groups_col = db["groups"]  # Now 'groups_col' is defined

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

    # Create a group and set the creator as the leader


def create_group(group_name, leader_id):
    groups_col = db["groups"]
    # Check if the name already exists
    if groups_col.find_one({"name": group_name}):
        return False, "Group name already exists."

    group_data = {
        "name": group_name,
        "leader_id": leader_id,
        "members": [leader_id],  # Leader is the first member
    }
    groups_col.insert_one(group_data)
    # Update the user to reference this group
    users_col.update_one({"user_id": leader_id}, {"$set": {"group_name": group_name}})
    return True, f"Group '{group_name}' created successfully!"


# Join a group (with 4-person limit)
def join_group(group_name, user_id):
    groups_col = db["groups"]
    group = groups_col.find_one({"name": group_name})

    if not group:
        return False, "Group not found."
    if len(group["members"]) >= 4:
        return False, "Group is full (max 4 people)."

    # Check if user is already in a group
    user = users_col.find_one({"user_id": user_id})
    if user.get("group_name"):
        return False, "You are already in a group. Leave it first."

    groups_col.update_one({"name": group_name}, {"$push": {"members": user_id}})
    users_col.update_one({"user_id": user_id}, {"$set": {"group_name": group_name}})
    return True, f"You joined group {group_name}."


# Leave a group logic
def leave_group(user_id):
    user = users_col.find_one({"user_id": user_id})
    group_name = user.get("group_name")
    if not group_name:
        return False, "You are not in any group."

    groups_col = db["groups"]
    group = groups_col.find_one({"name": group_name})

    # If the leader leaves, they must delegate first or delete the group
    if group["leader_id"] == user_id:
        return (
            False,
            "You are the leader! Assign a new leader or delete the group before leaving.",
        )

    groups_col.update_one({"name": group_name}, {"$pull": {"members": user_id}})
    users_col.update_one({"user_id": user_id}, {"$unset": {"group_name": ""}})
    return True, "You left the group."


def delete_group(user_id):
    # Only the leader can delete
    group = groups_col.find_one({"leader_id": user_id})
    if not group:
        return (
            False,
            "Only the leader can delete the group (or you aren't leading one).",
        )

    group_name = group["name"]
    # 1. Remove group reference from all members
    users_col.update_many({"group_name": group_name}, {"$unset": {"group_name": ""}})
    # 2. Delete the group document
    groups_col.delete_one({"name": group_name})
    return True, f"Group '{group_name}' has been deleted."


def list_groups():
    groups = groups_col.find({}, {"name": 1, "members": 1, "_id": 0})
    if not groups:
        return "No groups available at the moment."

    msg = "Available Groups:\n"
    for g in groups:
        msg += f"- {g['name']} ({len(g['members'])}/4 members)\n"
    return msg
