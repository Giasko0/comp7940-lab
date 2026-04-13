import argparse
import random
from datetime import datetime, timezone

from Mongo_db import get_collection

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


if __name__ == "__main__":
    main()
