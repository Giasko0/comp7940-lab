"""
This program requires the following modules:
- python-telegram-bot==22.5
- urllib3==2.6.2
"""

from pathlib import Path

from Mongo_db import (
    create_group,
    delete_group,
    get_group_for_user,
    join_group,
    leave_group,
    list_groups,
)
from telegram import BotCommand, Update, InlineKeyboardButton, InlineKeyboardMarkup
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
import json
import logging
from urllib.parse import quote_plus, unquote_plus
from Mongo_db import get_user_profile as mongo_get_user_profile
from Mongo_db import get_user_profile_by_username
from Mongo_db import save_chat_message, save_user_profile as mongo_save_user_profile
from Search import search_similar_users
from ChatGPT_HKBU import ChatGPT

gpt = None
COURSE_INFO_PATH = Path(__file__).with_name("course_info.md")

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
    profile = get_user_profile(telegram_user.id, telegram_user.username)
    keep_completed = bool(profile and profile.get("completed"))
    return mongo_save_user_profile(telegram_user, questionnaire, completed=keep_completed)


def mark_profile_completed(telegram_user, questionnaire):
    return mongo_save_user_profile(telegram_user, questionnaire, completed=True)


def get_config_value(config, section, option, fallback=None):
    if config.has_section(section) and config.has_option(section, option):
        return config[section][option]
    return fallback


def build_main_menu_keyboard(include_profile_edit: bool = False, include_back: bool = False):
    keyboard = [
        [InlineKeyboardButton("Find people similar to you", callback_data="find_similar")],
        [InlineKeyboardButton("Manage grouping", callback_data="manage_grouping")],
        [InlineKeyboardButton("Virtual professor", callback_data="virtual_professor")],
    ]
    if include_profile_edit:
        keyboard.append([InlineKeyboardButton("Edit profile", callback_data="edit_profile")])
    if include_back:
        keyboard.append([InlineKeyboardButton("Back to menu", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)


def back_to_menu_markup():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Back to menu", callback_data="back_to_main")]]
    )


def with_back_to_menu(rows):
    return InlineKeyboardMarkup(
        rows + [[InlineKeyboardButton("Back to menu", callback_data="back_to_main")]]
    )


def build_edit_profile_keyboard():
    return with_back_to_menu(
        [
            [InlineKeyboardButton("Edit age", callback_data="edit_question:age")],
            [InlineKeyboardButton("Edit language", callback_data="edit_question:language")],
            [InlineKeyboardButton("Edit gender", callback_data="edit_question:gender")],
            [InlineKeyboardButton("Edit hobbies", callback_data="edit_question:hobbies")],
        ]
    )


def build_group_join_rows(groups):
    rows = []
    for group in groups:
        name = group.get("name", "Unknown")
        members = len(group.get("members", []))
        rows.append(
            [
                InlineKeyboardButton(
                    f"{name} ({members}/4)",
                    callback_data=f"group_join:{quote_plus(name)}",
                )
            ]
        )
    return rows


def build_manage_grouping_view(user_id: int):
    groups = list_groups()
    current_group = get_group_for_user(user_id)
    has_group = current_group is not None
    is_leader = bool(has_group and current_group.get("leader_id") == user_id)

    rows = build_group_join_rows(groups)
    if not has_group:
        rows.append([InlineKeyboardButton("Create group", callback_data="group_create_prompt")])
    if has_group:
        rows.append([InlineKeyboardButton("Leave current group", callback_data="group_leave")])
    if is_leader:
        rows.append([InlineKeyboardButton("Delete my group", callback_data="group_delete")])

    title = "Manage grouping: pick a group to join or use actions below."
    return title, with_back_to_menu(rows)


def generate_matchmaking_text(result):
    return gpt.submit_matchmaking(
        result.get("request_user", {}),
        result.get("matches", []),
    ).strip()


def load_course_info():
    with COURSE_INFO_PATH.open("r", encoding="utf-8") as file:
        return file.read()


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

    async def post_init(application):
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Start the bot"),
                BotCommand("help", "Show the command list"),
                BotCommand("group", "Manage groups"),
            ]
        )

    app = ApplicationBuilder().token(telegram_token).post_init(post_init).build()

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
        reply_markup = build_main_menu_keyboard(
            include_profile_edit=True, include_back=False
        )
        text = "Welcome back! What would you like to do next?"
    else:
        reply_markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Create profile", callback_data="create_profile")],
                [InlineKeyboardButton("Manage grouping", callback_data="manage_grouping")],
                [InlineKeyboardButton("Virtual professor", callback_data="virtual_professor")],
            ]
        )
        text = "Welcome to our bot! Create your profile so we can match you with the best study group."

    await update.message.reply_text(text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 *Maestro - Command List*\n\n"
        "*General Commands:*\n"
        "/start - Start the bot and take the questionnaire\n"
        "/help - Show this help message\n\n"
        "*Group Management:*\n"
        "/group create [name] - Create a new group (You become leader)\n"
        "/group join [name] - Join an existing group\n"
        "/group leave - Leave your current group\n"
        "/group delete - Delete the group (Leaders only)\n"
        "/group list - See all available groups\n\n"
        "*Main Menu:*\n"
        "Find similar people, manage grouping, edit your profile, or ask the Virtual Professor.\n"
        "Use *Edit profile* to update one specific answer without redoing everything."
    )
    await update.message.reply_text(
        help_text, parse_mode="Markdown", reply_markup=back_to_menu_markup()
    )


async def ask_age(query, context, error=None):
    questionnaire = get_questionnaire(query.from_user.id)
    selected = questionnaire.get("age")
    single_edit_mode = context.user_data.get("single_edit_mode", False)
    keyboard = [
        [
            InlineKeyboardButton(
                ("✅ " if option == selected else "") + option,
                callback_data=f"age:{option}",
            )
        ]
        for option in AGE_OPTIONS
    ]
    keyboard.append(
        [
            InlineKeyboardButton(
                "Save changes" if single_edit_mode else "Next",
                callback_data="finish_profile" if single_edit_mode else "next_language",
            )
        ]
    )
    keyboard.append([InlineKeyboardButton("Back to menu", callback_data="back_to_main")])
    text = "Question 1/4: What is your age range?"
    if error:
        text += f"\n\n{error}"
    await safe_edit_or_send(
        query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def ask_language(query, context, error=None):
    questionnaire = get_questionnaire(query.from_user.id)
    selected = questionnaire.get("language")
    single_edit_mode = context.user_data.get("single_edit_mode", False)
    keyboard = [
        [
            InlineKeyboardButton(
                ("✅ " if option == selected else "") + option,
                callback_data=f"language:{option}",
            )
        ]
        for option in LANGUAGE_OPTIONS
    ]
    keyboard.append(
        [
            InlineKeyboardButton(
                "Save changes" if single_edit_mode else "Next",
                callback_data="finish_profile" if single_edit_mode else "next_gender",
            )
        ]
    )
    keyboard.append([InlineKeyboardButton("Back to menu", callback_data="back_to_main")])
    text = "Question 2/4: What language do you speak?"
    if error:
        text += f"\n\n{error}"
    await safe_edit_or_send(
        query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def ask_gender(query, context, error=None):
    questionnaire = get_questionnaire(query.from_user.id)
    selected = questionnaire.get("gender")
    single_edit_mode = context.user_data.get("single_edit_mode", False)
    keyboard = [
        [
            InlineKeyboardButton(
                ("✅ " if option == selected else "") + option,
                callback_data=f"gender:{option}",
            )
        ]
        for option in GENDER_OPTIONS
    ]
    keyboard.append(
        [
            InlineKeyboardButton(
                "Save changes" if single_edit_mode else "Next",
                callback_data="finish_profile" if single_edit_mode else "next_hobbies",
            )
        ]
    )
    keyboard.append([InlineKeyboardButton("Back to menu", callback_data="back_to_main")])
    text = "Question 3/4: What is your gender?"
    if error:
        text += f"\n\n{error}"
    await safe_edit_or_send(
        query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def ask_hobbies(query, context, error=None):
    questionnaire = get_questionnaire(query.from_user.id)
    selected = questionnaire.get("hobbies", [])
    single_edit_mode = context.user_data.get("single_edit_mode", False)
    keyboard = [
        [
            InlineKeyboardButton(
                ("✅ " if option in selected else "") + option,
                callback_data=f"hobby:{option}",
            )
        ]
        for option in HOBBY_OPTIONS
    ]
    keyboard.append(
        [
            InlineKeyboardButton(
                "Save changes" if single_edit_mode else "Finish",
                callback_data="finish_profile",
            )
        ]
    )
    keyboard.append([InlineKeyboardButton("Back to menu", callback_data="back_to_main")])
    text = "Question 4/4: What are your hobbies (You can pick multiple)?"
    if error:
        text += f"\n\n{error}"
    await safe_edit_or_send(
        query, context, text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data not in {"virtual_professor", "group_create_prompt"}:
        context.user_data.pop("pending_action", None)

    if query.data == "create_profile":
        context.user_data["single_edit_mode"] = False
        saved = mongo_save_user_profile(
            query.from_user, _default_questionnaire(), completed=False
        )
        if not saved:
            await safe_edit_or_send(
                query,
                context,
                "Failed to initialize your profile. Please try again.",
                reply_markup=back_to_menu_markup(),
            )
            return
        await ask_age(query, context)
    elif query.data == "virtual_professor":
        context.user_data["single_edit_mode"] = False
        context.user_data["pending_action"] = "virtual_professor"
        await safe_edit_or_send(
            query,
            context,
            "Ask your question to the Virtual Professor.",
            reply_markup=back_to_menu_markup(),
        )
    elif query.data == "manage_grouping":
        context.user_data["single_edit_mode"] = False
        text, reply_markup = build_manage_grouping_view(query.from_user.id)
        await safe_edit_or_send(query, context, text, reply_markup=reply_markup)
    elif query.data == "edit_profile":
        if not get_user_profile(query.from_user.id, query.from_user.username):
            saved = mongo_save_user_profile(
                query.from_user, _default_questionnaire(), completed=False
            )
            if not saved:
                await safe_edit_or_send(
                    query,
                    context,
                    "Failed to load your profile. Please try again.",
                    reply_markup=back_to_menu_markup(),
                )
                return
        context.user_data["single_edit_mode"] = False
        await safe_edit_or_send(
            query,
            context,
            "Choose what you want to edit:",
            reply_markup=build_edit_profile_keyboard(),
        )
    elif query.data == "group_create_prompt":
        context.user_data["pending_action"] = "group_create"
        await safe_edit_or_send(
            query,
            context,
            "Send the group name you want to create.",
            reply_markup=back_to_menu_markup(),
        )
    elif query.data.startswith("edit_question:"):
        field = query.data.split(":", 1)[1]
        context.user_data["single_edit_mode"] = True
        if field == "age":
            await ask_age(query, context)
        elif field == "language":
            await ask_language(query, context)
        elif field == "gender":
            await ask_gender(query, context)
        elif field == "hobbies":
            await ask_hobbies(query, context)
        else:
            await safe_edit_or_send(
                query,
                context,
                "Unknown profile field.",
                reply_markup=back_to_menu_markup(),
            )
    elif query.data == "find_similar":
        await query.message.edit_text("Searching for similar users...")
        result = search_similar_users(query.from_user.id, top_k=5)
        if not result.get("ok"):
            await safe_edit_or_send(
                query,
                context,
                f"Error: {result.get('error')}",
                reply_markup=back_to_menu_markup(),
            )
            return

        matches = result.get("matches", [])
        if not matches:
            await safe_edit_or_send(
                query,
                context,
                "No similar users found yet. Ask a friend to complete their profile too.",
                reply_markup=back_to_menu_markup(),
            )
            return

        text = generate_matchmaking_text(result)
        if text.startswith("Error:"):
            await safe_edit_or_send(
                query,
                context,
                "Error while generating matchmaking recommendations. Please try again.",
                reply_markup=back_to_menu_markup(),
            )
            return
        await safe_edit_or_send(
            query, context, text, reply_markup=back_to_menu_markup()
        )

    elif query.data == "browse_groups":
        text, reply_markup = build_manage_grouping_view(query.from_user.id)
        await safe_edit_or_send(query, context, text, reply_markup=reply_markup)

    elif query.data == "back_to_main":
        context.user_data["single_edit_mode"] = False
        profile = get_user_profile(query.from_user.id)
        if profile and profile.get("completed"):
            reply_markup = build_main_menu_keyboard(
                include_profile_edit=True, include_back=False
            )
            text = "What would you like to do next?"
        else:
            reply_markup = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("Create profile", callback_data="create_profile")],
                    [InlineKeyboardButton("Manage grouping", callback_data="manage_grouping")],
                    [InlineKeyboardButton("Virtual professor", callback_data="virtual_professor")],
                ]
            )
            text = "Welcome to our bot! Create your profile so we can match you with the best study group."
        await safe_edit_or_send(
            query, context, text, reply_markup=reply_markup
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
        single_edit_mode = context.user_data.get("single_edit_mode", False)
        context.user_data["single_edit_mode"] = False
        await safe_edit_or_send(
            query,
            context,
            (
                "Profile updated! What would you like to do next?"
                if single_edit_mode
                else "Profile completed! What would you like to do next?"
            ),
            reply_markup=build_main_menu_keyboard(
                include_profile_edit=True, include_back=False
            ),
        )

    # Group commands handlers
    elif query.data.startswith("group_"):
        await handle_group_callback(query, context)


async def handle_group_callback(query, context):
    """Handle group-related callback queries"""
    payload = query.data[len("group_") :]
    action, separator, value = payload.partition(":")
    group_name = unquote_plus(value) if separator and value else None
    if not separator:
        # Backward compatibility for old callback format: group_join_<name>
        legacy = query.data.split("_", 2)
        if len(legacy) >= 3:
            action = legacy[1]
            group_name = legacy[2]

    if action == "join" and group_name:
        context.user_data.pop("pending_action", None)
        ok, message = join_group(group_name, query.from_user.id)
        if ok:
            await safe_edit_or_send(
                query,
                context,
                f"Successfully joined {group_name}!",
                reply_markup=back_to_menu_markup(),
            )
        else:
            await safe_edit_or_send(
                query, context, message, reply_markup=back_to_menu_markup()
            )

    elif action == "delete":
        context.user_data.pop("pending_action", None)
        ok, message = delete_group(query.from_user.id)
        await safe_edit_or_send(
            query,
            context,
            message if not ok else "Group deleted!",
            reply_markup=back_to_menu_markup(),
        )

    elif action == "create_prompt":
        context.user_data["pending_action"] = "group_create"
        await safe_edit_or_send(
            query,
            context,
            "Send the group name you want to create.",
            reply_markup=back_to_menu_markup(),
        )

    elif action == "leave":
        context.user_data.pop("pending_action", None)
        ok, message = leave_group(query.from_user.id)
        if ok:
            await safe_edit_or_send(
                query,
                context,
                "Successfully left the group!",
                reply_markup=back_to_menu_markup(),
            )
        else:
            await safe_edit_or_send(
                query, context, message, reply_markup=back_to_menu_markup()
            )


async def group_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /group command"""
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "Usage: /group create [name] | /group join [name] | /group leave | /group delete | /group list",
            reply_markup=back_to_menu_markup(),
        )
        return

    action = context.args[0].lower()

    if action == "create":
        group_name = " ".join(context.args[1:]) if len(context.args) > 1 else None
        if not group_name:
            await update.message.reply_text(
                "Usage: /group create [group_name]", reply_markup=back_to_menu_markup()
            )
            return
        ok, message = create_group(group_name, update.effective_user.id)
        await update.message.reply_text(
            message if not ok else f"Group '{group_name}' created!",
            reply_markup=back_to_menu_markup(),
        )

    elif action == "list":
        groups = list_groups()
        if not groups:
            await update.message.reply_text(
                "No groups available.", reply_markup=back_to_menu_markup()
            )
        else:
            rows = build_group_join_rows(groups)
            await update.message.reply_text(
                "Select a group to join:",
                reply_markup=with_back_to_menu(rows),
            )

    elif action == "join":
        group_name = " ".join(context.args[1:]) if len(context.args) > 1 else None
        if not group_name:
            await update.message.reply_text(
                "Usage: /group join [group_name]", reply_markup=back_to_menu_markup()
            )
            return
        ok, message = join_group(group_name, update.effective_user.id)
        await update.message.reply_text(
            message if not ok else f"Joined '{group_name}'!",
            reply_markup=back_to_menu_markup(),
        )

    elif action == "leave":
        ok, message = leave_group(update.effective_user.id)
        await update.message.reply_text(
            message if not ok else "Left the group!",
            reply_markup=back_to_menu_markup(),
        )

    elif action == "delete":
        ok, message = delete_group(update.effective_user.id)
        await update.message.reply_text(
            message if not ok else "Group deleted!",
            reply_markup=back_to_menu_markup(),
        )

    else:
        await update.message.reply_text(
            "Unknown group action. Use: create, join, leave, delete, list.",
            reply_markup=back_to_menu_markup(),
        )


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle regular text messages with async Celery tasks"""
    logging.info("UPDATE: " + str(update))
    loading_message = await update.message.reply_text("Thinking...")
    pending_action = context.user_data.get("pending_action")
    user_text = update.message.text.strip()

    if pending_action == "group_create":
        if not user_text:
            await loading_message.edit_text(
                "Group name cannot be empty. Please send a valid group name.",
                reply_markup=back_to_menu_markup(),
            )
            return
        context.user_data.pop("pending_action", None)
        ok, response = create_group(user_text, update.effective_user.id)
        if ok:
            response = f"Group '{user_text}' created!"
    elif pending_action == "virtual_professor":
        context.user_data.pop("pending_action", None)
        try:
            course_info = load_course_info()
        except FileNotFoundError as exc:
            logging.exception("Failed to load course_info.md: %s", exc)
            await loading_message.edit_text(
                "Error loading course information. Please contact the course team.",
                reply_markup=back_to_menu_markup(),
            )
            return
        response = gpt.submit_virtual_professor(user_text, course_info)
    else:
        response = gpt.submit(user_text)

    save_chat_message(update.effective_user, user_text, response)
    await loading_message.edit_text(response, reply_markup=back_to_menu_markup())


if __name__ == "__main__":
    main()
