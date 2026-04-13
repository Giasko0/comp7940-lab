import argparse
import random
from datetime import datetime, timezone

from Mongo_db import get_collection, db

AGE_OPTIONS = ["Under 18", "18-20", "21-23", "24-26", "27+"]
GENDER_OPTIONS = ["Male", "Female", "Prefer not to say"]
HOBBY_OPTIONS = [
    "Programming",
    "Sports",
    "Art",
    "Music",
    "Gaming",
    "Gym",
    "Chess",
    "Photography",
]
LANGUAGE_OPTIONS = ["Italian", "English", "Bilingual"]

ITALIAN_BRAINROT_NAMES = [
    "Gigachad Gennaro",
    "Spaghettino Supremo",
    "Pasta Wizard Piero",
    "Mozzarella Maverick",
    "Risotto Rambo",
    "Espresso Enforcer",
    "Cappuccino Commando",
    "Lasagna Legend",
    "Polenta Phantom",
    "Cannolo Crusher",
    "Zio Sigma Salvo",
    "Nonno Turbo Nino",
    "Trenbolone Tonino",
    "Focaccia Fury Fabio",
    "Biscotto Boss Beppe",
    "Mandolino Matrix Marco",
    "Pesto Paladin Paolo",
    "Carbonara Captain Carlo",
    "Tiramisu Titan Tino",
    "Gelato Gladiator Gianni",
]


def username_from_name(name: str, idx: int) -> str:
    compact = "".join(ch for ch in name.lower() if ch.isalnum())
    return f"{compact[:18]}_{idx}"


def make_fake_user(idx: int) -> dict:
    name = ITALIAN_BRAINROT_NAMES[idx % len(ITALIAN_BRAINROT_NAMES)]
    hobby_count = random.randint(2, 4)
    hobbies = random.sample(HOBBY_OPTIONS, hobby_count)

    return {
        "telegram_user_id": 900000 + idx,
        "username": username_from_name(name, idx),
        "display_name": name,
        "in_group": random.choice([True, False]),
        "age": random.choice(AGE_OPTIONS),
        "gender": random.choice(GENDER_OPTIONS),
        "hobbies": hobbies,
        "language": random.choice(LANGUAGE_OPTIONS),
        "completed": True,
        "updated_at": datetime.now(timezone.utc),
    }


def seed_users(count: int) -> tuple[int, int]:
    collection = get_collection()
    inserted = 0
    updated = 0

    for i in range(count):
        user_doc = make_fake_user(i)
        result = collection.update_one(
            {"telegram_user_id": user_doc["telegram_user_id"]},
            {
                "$set": user_doc,
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
        if result.upserted_id is not None:
            inserted += 1
        else:
            updated += 1

    return inserted, updated


def seed_groups_with_space():
    groups_col = db["groups"]
    users_col = db["users"]

    # Get the fake users we just created (IDs >= 900000)
    fake_users = list(users_col.find({"telegram_user_id": {"$gte": 900000}}))
    group_names = [
        "Study_Club_AI",
        "Python_Beginners",
        "Data_Crunchers",
        "Cyber_Security_Lab",
        "ML_Enthusiasts",
        "Web_Dev_Squad",
        "Deep_Learning_Circle",
    ]

    user_idx = 0

    for g_name in group_names:
        # Check if we still have users left to assign
        if user_idx >= len(fake_users):
            print(f"Stopping at {g_name}: No more fake users available to fill groups.")
            break

        # Pick 1 to 3 users
        num_members = random.randint(1, 3)
        members_for_this_group = fake_users[user_idx : user_idx + num_members]
        user_idx += num_members

        member_ids = [u["telegram_user_id"] for u in members_for_this_group]
        leader_id = member_ids[0]

        groups_col.update_one(
            {"name": g_name},
            {"$set": {"name": g_name, "leader_id": leader_id, "members": member_ids}},
            upsert=True,
        )

        users_col.update_many(
            {"telegram_user_id": {"$in": member_ids}},
            {"$set": {"group_name": g_name, "in_group": True}},
        )

    print(f"Groups successfully seeded: {group_names[:user_idx]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed fake users into MongoDB")
    parser.add_argument("--count", type=int, default=20, help="Number of fake users")
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed for reproducible data"
    )
    args = parser.parse_args()

    if args.count <= 0:
        raise ValueError("--count must be greater than 0")

    random.seed(args.seed)
    inserted, updated = seed_users(args.count)
    print(
        f"Seeding complete. Requested={args.count}, inserted={inserted}, updated={updated}"
    )

    seed_groups_with_space()


if __name__ == "__main__":
    main()
