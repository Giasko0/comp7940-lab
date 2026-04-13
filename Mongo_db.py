import configparser
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

def _load_config() -> configparser.SectionProxy:
    config = configparser.ConfigParser()
    config.read("config.ini")
    if not config.has_section("MONGO"):
        raise ValueError("Missing [MONGO] section in config.ini")
    return config["MONGO"]


mongo_config = _load_config()
mongo_uri = mongo_config.get("URI")
db_name = mongo_config.get("DB_NAME")

if not mongo_uri or not db_name:
    raise ValueError("Missing MONGO URI or DB_NAME in config.ini")

# Initialize GLOBALLY (This removes the Pylance errors)
client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
db = client[db_name]  # Now 'db' is defined for the whole file
users_col = db["users"]  # Now 'users_col' is defined
groups_col = db["groups"]  # Now 'groups_col' is defined

collection_cache: Optional[Collection] = None


def _normalize_telegram_user_id(user_or_id: Any) -> int:
    if hasattr(user_or_id, "id"):
        return int(user_or_id.id)
    return int(user_or_id)


def get_collection() -> Collection:
    global collection_cache
    if collection_cache is not None:
        return collection_cache

    collection_name = mongo_config.get("COLLECTION_NAME")
    if not collection_name:
        raise ValueError("Missing MONGO COLLECTION_NAME in config.ini")

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
    leader_id = _normalize_telegram_user_id(leader_id)
    # Check if the name already exists
    if groups_col.find_one({"name": group_name}):
        return False, "Group name already exists."

    leader = users_col.find_one({"telegram_user_id": leader_id}, {"_id": 0})
    if not leader:
        return False, "User profile not found. Complete /start first."

    group_data = {
        "name": group_name,
        "leader_id": leader_id,
        "members": [leader_id],
    }
    groups_col.insert_one(group_data)
    users_col.update_one(
        {"telegram_user_id": leader_id},
        {"$set": {"group_name": group_name, "in_group": True}},
    )
    return True, f"Group '{group_name}' created successfully!"


# Join a group (with 4-person limit)
def join_group(group_name, user_id):
    user_id = _normalize_telegram_user_id(user_id)
    group = groups_col.find_one({"name": group_name})

    if not group:
        return False, "Group not found."
    if len(group["members"]) >= 4:
        return False, "Group is full (max 4 people)."

    user = users_col.find_one({"telegram_user_id": user_id})
    if not user:
        return False, "User profile not found. Complete /start first."
    if user.get("group_name"):
        return False, "You are already in a group. Leave it first."

    groups_col.update_one({"name": group_name}, {"$push": {"members": user_id}})
    users_col.update_one(
        {"telegram_user_id": user_id},
        {"$set": {"group_name": group_name, "in_group": True}},
    )
    return True, f"You joined group {group_name}."


# Leave a group logic
def leave_group(user_id):
    user_id = _normalize_telegram_user_id(user_id)
    user = users_col.find_one({"telegram_user_id": user_id})
    if not user:
        return False, "User profile not found. Complete /start first."

    group_name = user.get("group_name")
    if not group_name:
        return False, "You are not in any group."

    group = groups_col.find_one({"name": group_name})
    if not group:
        return False, "Group not found."

    # If the leader leaves, they must delegate first or delete the group
    if group["leader_id"] == user_id:
        return (
            False,
            "You are the leader! Assign a new leader or delete the group before leaving.",
        )

    groups_col.update_one({"name": group_name}, {"$pull": {"members": user_id}})
    users_col.update_one(
        {"telegram_user_id": user_id},
        {"$unset": {"group_name": ""}, "$set": {"in_group": False}},
    )
    return True, "You left the group."


def delete_group(user_id):
    user_id = _normalize_telegram_user_id(user_id)
    # Only the leader can delete
    group = groups_col.find_one({"leader_id": user_id})
    if not group:
        return (
            False,
            "Only the leader can delete the group (or you aren't leading one).",
        )

    group_name = group["name"]
    users_col.update_many(
        {"group_name": group_name},
        {"$unset": {"group_name": ""}, "$set": {"in_group": False}},
    )
    groups_col.delete_one({"name": group_name})
    return True, f"Group '{group_name}' has been deleted."


def get_group_for_user(user_id):
    user_id = _normalize_telegram_user_id(user_id)
    return groups_col.find_one({"members": user_id}, {"_id": 0})


def list_groups():
    groups = list(groups_col.find({}, {"name": 1, "members": 1, "leader_id": 1, "_id": 0}))
    return groups
