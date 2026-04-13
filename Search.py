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

    if me.get("age") and me.get("age") == other.get("age"):
        score += 2

    if me.get("gender") and me.get("gender") == other.get("gender"):
        score += 1

    return {
        "score": score,
        "telegram_user_id": other.get("telegram_user_id"),
        "username": other.get("username") or "unknown_user",
        "age": other.get("age"),
        "gender": other.get("gender"),
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
        },
        "matches": ranked[:top_k],
    }
