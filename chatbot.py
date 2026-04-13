"""
This program requires the following modules:
- python-telegram-bot==22.5
- urllib3==2.6.2
- celery==5.4.0
- redis==5.0.1
"""

from Mongo_db import create_group, join_group, delete_group, list_groups, leave_group
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


def get_config_value(config, section, option, fallback=None):
    if config.has_section(section) and config.has_option(section, option):
        return config[section][option]
    return fallback


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
    telegram_token = get_config_value(config, "TELEGRAM", "ACCESS_TOKEN")
    if not telegram_token:
        raise ValueError("Missing Telegram bot token in config.ini [TELEGRAM].")
    app = ApplicationBuilder().token(telegram_token).build()

    # Register handlers
    logging.info("INIT: Registering bot handlers...")
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))  # Add this line
    app.add_handler(CommandHandler("group", group_command))
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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Virtual Professor - Command List*\n\n"
        "*General Commands:*\n"
        "/start - Start the bot and take the questionnaire\n"
        "/help - Show this help message\n\n"
        "*Group Management:*\n"
        "/group create [name] - Create a new group (You become leader)\n"
        "/group join [name] - Join an existing group\n"
        "/group leave - Leave your current group\n"
        "/group delete - Delete the group (Leaders only)\n"
        "/group list - See all available groups\n\n"
        "*Matchmaking:*\n"
        "Use the buttons in the menu to find people with similar interests!"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


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
    text = "Question 2/4: What language do you speak?"
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


async def ask_hobbies(query, context, error=None):
    questionnaire = get_questionnaire(query.from_user.id)
    selected = questionnaire.get("hobbies", [])
    keyboard = [
        [
            InlineKeyboardButton(
                ("✅ " if option in selected else "") + option,
                callback_data=f"hobby:{option}",
            )
        ]
        for option in HOBBY_OPTIONS
    ]
    keyboard.append([InlineKeyboardButton("Finish", callback_data="finish_profile")])
    text = "Question 4/4: What are your hobbies (You can pick multiple)?"
    if error:
        text += f"\n\n{error}"
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
        await query.message.edit_text("Searching for similar users...")
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
            username = match.get("username", "Unknown")
            score = match.get("score", 0)
            lines.append(f"• @{username} (Match: {score:.0%})")

        text = "\n".join(lines)
        keyboard = [
            [InlineKeyboardButton("Back to main menu", callback_data="back_to_main")]
        ]
        await safe_edit_or_send(
            query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "browse_groups":
        groups = list_groups()
        if not groups:
            await safe_edit_or_send(
                query,
                context,
                "No groups available yet. Be the first to create one!",
            )
            return

        lines = ["Available groups:"]
        for group in groups:
            name = group.get("name", "Unknown")
            members = len(group.get("members", []))
            lines.append(f"• {name} ({members} members)")

        text = "\n".join(lines)
        keyboard = [
            [InlineKeyboardButton("Back to main menu", callback_data="back_to_main")]
        ]
        await safe_edit_or_send(
            query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "back_to_main":
        profile = get_user_profile(query.from_user.id)
        if profile and profile.get("completed"):
            keyboard = [
                [
                    InlineKeyboardButton(
                        "Find people similar to you", callback_data="find_similar"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "Browse groups", callback_data="browse_groups"
                    )
                ],
            ]
            text = "What would you like to do next?"
        else:
            keyboard = [
                [InlineKeyboardButton("Create profile", callback_data="create_profile")]
            ]
            text = "Welcome to our bot! Create your profile so we can match you with the best study group."
        await safe_edit_or_send(
            query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("age:"):
        age = query.data.split(":")[1]
        questionnaire = get_questionnaire(query.from_user.id)
        questionnaire["age"] = age
        set_questionnaire(query.from_user, questionnaire)
        await ask_age(query, context)

    elif query.data.startswith("language:"):
        language = query.data.split(":")[1]
        questionnaire = get_questionnaire(query.from_user.id)
        questionnaire["language"] = language
        set_questionnaire(query.from_user, questionnaire)
        await ask_language(query, context)

    elif query.data == "next_language":
        questionnaire = get_questionnaire(query.from_user.id)
        if questionnaire.get("age") is None:
            await ask_age(query, context, "Please select an age range first.")
            return
        await ask_language(query, context)

    elif query.data.startswith("gender:"):
        gender = query.data.split(":")[1]
        questionnaire = get_questionnaire(query.from_user.id)
        questionnaire["gender"] = gender
        set_questionnaire(query.from_user, questionnaire)
        await ask_gender(query, context)

    elif query.data == "next_gender":
        questionnaire = get_questionnaire(query.from_user.id)
        if questionnaire.get("language") is None:
            await ask_language(query, context, "Please select a language first.")
            return
        await ask_gender(query, context)

    elif query.data.startswith("hobby:"):
        hobby = query.data.split(":")[1]
        questionnaire = get_questionnaire(query.from_user.id)
        hobbies = questionnaire.get("hobbies", [])
        if hobby in hobbies:
            hobbies.remove(hobby)
        else:
            hobbies.append(hobby)
        questionnaire["hobbies"] = hobbies
        set_questionnaire(query.from_user, questionnaire)
        await ask_hobbies(query, context)

    elif query.data == "next_hobbies":
        questionnaire = get_questionnaire(query.from_user.id)
        if questionnaire.get("gender") is None:
            await ask_gender(query, context, "Please select a gender first.")
            return
        await ask_hobbies(query, context)

    elif query.data == "finish_profile":
        questionnaire = get_questionnaire(query.from_user.id)
        mark_profile_completed(query.from_user, questionnaire)
        keyboard = [
            [
                InlineKeyboardButton(
                    "Find people similar to you", callback_data="find_similar"
                )
            ],
            [InlineKeyboardButton("Browse groups", callback_data="browse_groups")],
        ]
        await safe_edit_or_send(
            query,
            context,
            "Profile completed! What would you like to do next?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # Group commands handlers
    elif query.data.startswith("group_"):
        await handle_group_callback(query, context)


async def handle_group_callback(query, context):
    """Handle group-related callback queries"""
    data = query.data.split("_", 2)
    if len(data) < 2:
        return

    action = data[1]
    group_name = data[2] if len(data) > 2 else None

    if action == "join" and group_name:
        result = join_group(group_name, query.from_user)
        if result:
            await safe_edit_or_send(query, context, f"Successfully joined {group_name}!")
        else:
            await safe_edit_or_send(query, context, "Failed to join group.")

    elif action == "leave":
        result = leave_group(query.from_user)
        if result:
            await safe_edit_or_send(query, context, "Successfully left the group!")
        else:
            await safe_edit_or_send(query, context, "You are not in any group.")


async def group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /group command"""
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "Usage: /group create [name] | /group join [name] | /group leave | /group delete | /group list"
        )
        return

    action = context.args[0].lower()

    if action == "create":
        group_name = " ".join(context.args[1:]) if len(context.args) > 1 else None
        if not group_name:
            await update.message.reply_text("Usage: /group create [group_name]")
            return
        result = create_group(group_name, update.effective_user)
        if result:
            await update.message.reply_text(f"Group '{group_name}' created!")
        else:
            await update.message.reply_text("Failed to create group.")

    elif action == "list":
        groups = list_groups()
        if not groups:
            await update.message.reply_text("No groups available.")
        else:
            lines = ["Available groups:"]
            for group in groups:
                name = group.get("name", "Unknown")
                members = len(group.get("members", []))
                lines.append(f"• {name} ({members} members)")
            await update.message.reply_text("\n".join(lines))

    elif action == "join":
        group_name = " ".join(context.args[1:]) if len(context.args) > 1 else None
        if not group_name:
            await update.message.reply_text("Usage: /group join [group_name]")
            return
        result = join_group(group_name, update.effective_user)
        if result:
            await update.message.reply_text(f"Joined '{group_name}'!")
        else:
            await update.message.reply_text("Failed to join group.")

    elif action == "leave":
        result = leave_group(update.effective_user)
        if result:
            await update.message.reply_text("Left the group!")
        else:
            await update.message.reply_text("You are not in any group.")

    elif action == "delete":
        result = delete_group(update.effective_user)
        if result:
            await update.message.reply_text("Group deleted!")
        else:
            await update.message.reply_text("You are not a group leader.")


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages with async Celery tasks"""
    logging.info("UPDATE: " + str(update))
    loading_message = await update.message.reply_text("Thinking...")

    # send the user message to the ChatGPT client
    response = gpt.submit(update.message.text)

    save_chat_message(update.effective_user, update.message.text, response)

    # send the response to the Telegram box client
    await loading_message.edit_text(response)


if __name__ == "__main__":
    main()
