from typing import Any, Dict, List

from Mongo_db import get_collection


def _to_set(value) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    if isinstance(value, str):
        return {item.strip().lower() for item in value.split(",") if item.strip()}
    return set()


def _score_user(me: Dict[str, Any], other: Dict[str, Any]) -> Dict[str, Any]:
    me_hobbies = _to_set(me.get("hobbies"))
    other_hobbies = _to_set(other.get("hobbies"))

    common_hobbies = sorted(me_hobbies.intersection(other_hobbies))

    score = 0
    score += len(common_hobbies) * 3

    same_age = bool(me.get("age") and me.get("age") == other.get("age"))
    if same_age:
        score += 2

    same_gender = bool(me.get("gender") and me.get("gender") == other.get("gender"))
    if same_gender:
        score += 1

    same_language = bool(
        me.get("language") and me.get("language") == other.get("language")
    )
    if same_language:
        score += 1

    return {
        "score": score,
        "telegram_user_id": other.get("telegram_user_id"),
        "username": other.get("username") or "unknown_user",
        "age": other.get("age"),
        "gender": other.get("gender"),
        "language": other.get("language"),
        "same_age": same_age,
        "same_gender": same_gender,
        "same_language": same_language,
        "common_hobbies": common_hobbies,
    }


def search_similar_users(telegram_user_id: int, top_k: int = 5) -> Dict[str, Any]:
    collection = get_collection()

    me = collection.find_one({"telegram_user_id": telegram_user_id}, {"_id": 0})
    if not me:
        return {
            "ok": False,
            "error": "Profilo utente non trovato nel DB. Completa prima il questionario.",
        }

    others = collection.find(
        {
            "telegram_user_id": {"$ne": telegram_user_id},
            "completed": True,
        },
        {"_id": 0},
    )

    ranked: List[Dict[str, Any]] = []
    for other in others:
        result = _score_user(me, other)
        if result["score"] > 0:
            ranked.append(result)

    ranked.sort(key=lambda x: x["score"], reverse=True)

    return {
        "ok": True,
        "request_user": {
            "telegram_user_id": me.get("telegram_user_id"),
            "username": me.get("username") or me.get("user"),
            "age": me.get("age"),
            "gender": me.get("gender"),
            "language": me.get("language"),
            "hobbies": me.get("hobbies", []),
        },
        "matches": ranked[:top_k],
    }


def match_groups_to_user(telegram_user_id: int):
    from Mongo_db import db, users_col

    groups_col = db["groups"]

    # 1. Get your profile
    me = users_col.find_one({"telegram_user_id": telegram_user_id})
    if not me:
        return "Please complete your profile first."

    # 2. Get all groups that aren't full
    available_groups = list(
        groups_col.find({"$expr": {"$lt": [{"$size": "$members"}, 4]}})
    )

    group_recommendations = []

    for group in available_groups:
        group_score = 0
        member_details = []

        # 3. Check affinity with each member
        for member_id in group["members"]:
            member = users_col.find_one({"telegram_user_id": member_id})
            if member:
                # Use your existing scoring logic from search.py!
                result = _score_user(me, member)
                group_score += result["score"]
                member_details.append(member.get("username"))

        # Calculate average score for the group
        avg_score = group_score / len(group["members"]) if group["members"] else 0
        group_recommendations.append(
            {
                "name": group["name"],
                "score": round(avg_score, 1),
                "members": member_details,
            }
        )

    # 4. Sort by highest affinity
    group_recommendations.sort(key=lambda x: x["score"], reverse=True)
    return group_recommendations
