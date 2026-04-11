"""
This program requires the following modules:
- python-telegram-bot==22.5
- urllib3==2.6.2
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import configparser
import logging
from Mongo_db import get_user_profile as mongo_get_user_profile
from Mongo_db import get_user_profile_by_username
from Mongo_db import save_chat_message, save_user_profile as mongo_save_user_profile
from Search import search_similar_users
from ChatGPT_HKBU import ChatGPT

gpt = None

AGE_OPTIONS = ["Under 18", "18-20", "21-23", "24-26", "27+"]
GENDER_OPTIONS = ["Male", "Female", "Prefer not to say"]
HOBBY_OPTIONS = ["Programming", "Sports", "Art", "Music"]
LANGUAGE_OPTIONS = ["English", "Chinese", "Spanish", "Other"]


def _default_questionnaire():
    return {"age": None, "language": None, "gender": None, "hobbies": []}


def get_user_profile(user_id, username=None):
    profile = mongo_get_user_profile(user_id)
    if not profile and username:
        profile = get_user_profile_by_username(username)

    if profile:
        return {
            "completed": profile.get("completed", False),
            "in_group": profile.get("in_group", False),
            "questionnaire": {
                "age": profile.get("age"),
                "language": profile.get("language"),
                "gender": profile.get("gender"),
                "hobbies": profile.get("hobbies", []),
            },
        }

    return None


def ensure_user_profile(user_id):
    profile = get_user_profile(user_id)
    if profile is None:
        profile = {
            "completed": False,
            "questionnaire": _default_questionnaire(),
        }

    return profile


def get_questionnaire(user_id):
    profile = ensure_user_profile(user_id)
    questionnaire = profile.get("questionnaire") or {}
    return {
        "age": questionnaire.get("age"),
        "language": questionnaire.get("language"),
        "gender": questionnaire.get("gender"),
        "hobbies": questionnaire.get("hobbies", []),
    }


async def safe_edit_or_send(query, context, text, reply_markup=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        msg = str(e)
        if "message to edit not found" in msg.lower():
            chat_id = query.message.chat.id if query.message else query.from_user.id
            await context.bot.send_message(
                chat_id=chat_id, text=text, reply_markup=reply_markup
            )
        else:
            raise


def set_questionnaire(telegram_user, questionnaire):
    return mongo_save_user_profile(telegram_user, questionnaire, completed=False)


def mark_profile_completed(telegram_user, questionnaire):
    return mongo_save_user_profile(telegram_user, questionnaire, completed=True)


def main():
    # Configure logging so you can see initialization and error messages
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    # Load the configuration data from file
    logging.info("INIT: Loading configuration...")
    config = configparser.ConfigParser()
    config.read("config.ini")

    global gpt
    gpt = ChatGPT(config)

    # Create an Application for your bot
    logging.info("INIT: Connecting the Telegram bot...")
    app = ApplicationBuilder().token(config["TELEGRAM"]["ACCESS_TOKEN"]).build()

    # Register handlers
    logging.info("INIT: Registering bot handlers...")
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, callback))

    # Start the bot
    logging.info("INIT: Initialization done!")
    app.run_polling()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    profile = get_user_profile(user_id, username)

    if profile and profile.get("completed"):
        keyboard = [
            [
                InlineKeyboardButton(
                    "Find people similar to you", callback_data="find_similar"
                )
            ],
            [InlineKeyboardButton("Browse groups", callback_data="browse_groups")],
        ]
        text = "Welcome back! What would you like to do next?"
    else:
        keyboard = [
            [InlineKeyboardButton("Create profile", callback_data="create_profile")]
        ]
        text = "Welcome to our bot! Create your profile so we can match you with the best study group."

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)


async def ask_age(query, context, error=None):
    questionnaire = get_questionnaire(query.from_user.id)
    selected = questionnaire.get("age")
    keyboard = [
        [
            InlineKeyboardButton(
                ("✅ " if option == selected else "") + option,
                callback_data=f"age:{option}",
            )
        ]
        for option in AGE_OPTIONS
    ]
    keyboard.append([InlineKeyboardButton("Next", callback_data="next_language")])
    text = "Question 1/4: What is your age range?"
    if error:
        text += f"\n\n{error}"
    await safe_edit_or_send(
        query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def ask_language(query, context, error=None):
    questionnaire = get_questionnaire(query.from_user.id)
    selected = questionnaire.get("language")
    keyboard = [
        [
            InlineKeyboardButton(
                ("✅ " if option == selected else "") + option,
                callback_data=f"language:{option}",
            )
        ]
        for option in LANGUAGE_OPTIONS
    ]
    keyboard.append([InlineKeyboardButton("Next", callback_data="next_gender")])
    text = "Question 2/4: What is your preferred language for study groups?"
    if error:
        text += f"\n\n{error}"
    await safe_edit_or_send(
        query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def ask_gender(query, context, error=None):
    questionnaire = get_questionnaire(query.from_user.id)
    selected = questionnaire.get("gender")
    keyboard = [
        [
            InlineKeyboardButton(
                ("✅ " if option == selected else "") + option,
                callback_data=f"gender:{option}",
            )
        ]
        for option in GENDER_OPTIONS
    ]
    keyboard.append([InlineKeyboardButton("Next", callback_data="next_hobbies")])
    text = "Question 3/4: What is your gender?"
    if error:
        text += f"\n\n{error}"
    await safe_edit_or_send(
        query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def ask_hobbies(query, context):
    questionnaire = get_questionnaire(query.from_user.id)
    selected = set(questionnaire.get("hobbies", []))
    keyboard = [
        [
            InlineKeyboardButton(
                ("✅ " if option in selected else "") + option,
                callback_data=f"hobby:{option}",
            )
        ]
        for option in HOBBY_OPTIONS
    ]
    keyboard.append([InlineKeyboardButton("Done", callback_data="done_questionnaire")])
    text = "Question 4/4: Select your hobbies. Tap each item to toggle it, then press Done."
    await safe_edit_or_send(
        query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "create_profile":
        saved = set_questionnaire(query.from_user, _default_questionnaire())
        if not saved:
            await safe_edit_or_send(
                query,
                context,
                "Failed to initialize your profile. Please try again.",
            )
            return
        await ask_age(query, context)
    elif query.data == "find_similar":
        # da togliere mettere risposta con chatgpt
        result = search_similar_users(query.from_user.id, top_k=5)
        if not result.get("ok"):
            await safe_edit_or_send(query, context, f"Error: {result.get('error')}")
            return

        matches = result.get("matches", [])
        if not matches:
            await safe_edit_or_send(
                query,
                context,
                "No similar users found yet. Ask a friend to complete their profile too.",
            )
            return

        lines = ["People similar to you:"]
        for match in matches:
            hobbies = ", ".join(match.get("common_hobbies", [])) or "none"
            lines.append(
                f"- {match.get('username', 'unknown_user')} | score={match['score']} | common hobbies: {hobbies}"
            )
        # fino a qua
        await safe_edit_or_send(query, context, "\n".join(lines))
    elif query.data == "browse_groups":
        await safe_edit_or_send(query, context, "Browsing groups for you...")
    elif query.data.startswith("age:"):
        age = query.data.split(":", 1)[1]
        questionnaire = get_questionnaire(query.from_user.id)
        questionnaire["age"] = age
        set_questionnaire(query.from_user, questionnaire)
        await ask_age(query, context)
    elif query.data == "next_language":
        questionnaire = get_questionnaire(query.from_user.id)
        if not questionnaire.get("age"):
            await ask_age(
                query, context, error="Please select your age range before continuing."
            )
        else:
            await ask_language(query, context)
    elif query.data.startswith("language:"):
        language = query.data.split(":", 1)[1]
        questionnaire = get_questionnaire(query.from_user.id)
        questionnaire["language"] = language
        set_questionnaire(query.from_user, questionnaire)
        await ask_language(query, context)
    elif query.data == "next_gender":
        questionnaire = get_questionnaire(query.from_user.id)
        if not questionnaire.get("language"):
            await ask_language(
                query,
                context,
                error="Please select your preferred language before continuing.",
            )
        else:
            await ask_gender(query, context)
    elif query.data.startswith("gender:"):
        gender = query.data.split(":", 1)[1]
        questionnaire = get_questionnaire(query.from_user.id)
        questionnaire["gender"] = gender
        set_questionnaire(query.from_user, questionnaire)
        await ask_gender(query, context)
    elif query.data == "next_hobbies":
        questionnaire = get_questionnaire(query.from_user.id)
        if not questionnaire.get("gender"):
            await ask_gender(
                query, context, error="Please select your gender before continuing."
            )
        else:
            await ask_hobbies(query, context)
    elif query.data.startswith("hobby:"):
        hobby = query.data.split(":", 1)[1]
        questionnaire = get_questionnaire(query.from_user.id)
        hobbies = questionnaire.setdefault("hobbies", [])
        if hobby in hobbies:
            hobbies.remove(hobby)
        else:
            hobbies.append(hobby)
        set_questionnaire(query.from_user, questionnaire)
        await ask_hobbies(query, context)
    elif query.data == "done_questionnaire":
        user_id = query.from_user.id
        questionnaire = get_questionnaire(user_id)
        saved = mark_profile_completed(query.from_user, questionnaire)
        if not saved:
            await safe_edit_or_send(
                query,
                context,
                "Failed to save your profile. Please try again.",
            )
            return

        logging.info("QUESTIONNAIRE: Saved answers for user_id=%s", user_id)
        await safe_edit_or_send(
            query,
            context,
            "Thank you! Your profile has been saved. You can now use Find people similar to you.",
        )


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # await update.message.reply_text(response)
    logging.info("UPDATE: " + str(update))
    loading_message = await update.message.reply_text("Thinking...")

    # send the user message to the ChatGPT client
    response = gpt.submit(update.message.text)

    saved = save_chat_message(update.effective_user, update.message.text, response)
    if not saved:
        logging.warning(
            "DB: Failed to save chat message for user_id=%s", update.effective_user.id
        )

    # send the response to the Telegram box client
    await loading_message.edit_text(response)


if __name__ == "__main__":
    main()
