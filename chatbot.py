'''
This program requires the following modules:
- python-telegram-bot==22.5
- urllib3==2.6.2
'''
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters
import configparser
import logging
from ChatGPT_HKBU import ChatGPT
gpt = None

AGE_OPTIONS = ['Under 18', '18-20', '21-23', '24-26', '27+']
GENDER_OPTIONS = ['Male', 'Female', 'Prefer not to say']
HOBBY_OPTIONS = ['Programming', 'Sports', 'Art', 'Music']

# In-memory placeholder storage. Replace with MongoDB in the future.
USER_PROFILE_DB = {}

def get_user_profile(user_id):
    return USER_PROFILE_DB.get(user_id)


def save_user_profile(user_id, profile):
    USER_PROFILE_DB[user_id] = profile


def ensure_user_profile(user_id):
    profile = get_user_profile(user_id)
    if profile is None:
        profile = {
            'completed': False,
            'questionnaire': {
                'age': None,
                'gender': None,
                'hobbies': []
            }
        }
        save_user_profile(user_id, profile)
    return profile


def get_questionnaire(user_id):
    return ensure_user_profile(user_id)['questionnaire']


async def safe_edit_or_send(query, context, text, reply_markup=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        msg = str(e)
        if 'message to edit not found' in msg.lower():
            chat_id = query.message.chat.id if query.message else query.from_user.id
            await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        else:
            raise


def set_questionnaire(user_id, questionnaire):
    profile = ensure_user_profile(user_id)
    profile['questionnaire'] = questionnaire
    profile['completed'] = False
    save_user_profile(user_id, profile)


def mark_profile_completed(user_id):
    profile = ensure_user_profile(user_id)
    profile['completed'] = True
    save_user_profile(user_id, profile)


def main():
    # Configure logging so you can see initialization and error messages
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.INFO)
    
    # Load the configuration data from file
    logging.info('INIT: Loading configuration...')
    config = configparser.ConfigParser()
    config.read('config.ini')

    global gpt
    gpt = ChatGPT(config)

    # Create an Application for your bot
    logging.info('INIT: Connecting the Telegram bot...')
    app = ApplicationBuilder().token(config['TELEGRAM']['ACCESS_TOKEN']).build()

    # Register handlers
    logging.info('INIT: Registering bot handlers...')
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, callback))

    # Start the bot
    logging.info('INIT: Initialization done!')
    app.run_polling()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = get_user_profile(user_id)

    if profile and profile.get('completed'):
        keyboard = [
            [InlineKeyboardButton('Find people similar to you', callback_data='find_similar')],
            [InlineKeyboardButton('Browse groups', callback_data='browse_groups')]
        ]
        text = 'Welcome back! What would you like to do next?'
    else:
        keyboard = [[InlineKeyboardButton('Create profile', callback_data='create_profile')]]
        text = 'Welcome to our bot! Create your profile so we can match you with the best study group.'

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)

async def ask_age(query, context, error=None):
    user_id = query.from_user.id
    questionnaire = get_questionnaire(user_id)
    selected = questionnaire.get('age')
    keyboard = [
        [InlineKeyboardButton(('✅ ' if option == selected else '') + option, callback_data=f'age:{option}')]
        for option in AGE_OPTIONS
    ]
    keyboard.append([InlineKeyboardButton('Next', callback_data='next_gender')])
    text = 'Question 1/3: What is your age range?'
    if error:
        text += f'\n\n{error}'
    await safe_edit_or_send(query, context, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def ask_gender(query, context, error=None):
    user_id = query.from_user.id
    questionnaire = get_questionnaire(user_id)
    selected = questionnaire.get('gender')
    keyboard = [
        [InlineKeyboardButton(('✅ ' if option == selected else '') + option, callback_data=f'gender:{option}')]
        for option in GENDER_OPTIONS
    ]
    keyboard.append([InlineKeyboardButton('Next', callback_data='next_hobbies')])
    text = 'Question 2/3: What is your gender?'
    if error:
        text += f'\n\n{error}'
    await safe_edit_or_send(query, context, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def ask_hobbies(query, context):
    user_id = query.from_user.id
    questionnaire = get_questionnaire(user_id)
    selected = set(questionnaire.get('hobbies', []))
    keyboard = [
        [InlineKeyboardButton(('✅ ' if option in selected else '') + option, callback_data=f'hobby:{option}')]
        for option in HOBBY_OPTIONS
    ]
    keyboard.append([InlineKeyboardButton('Done', callback_data='done_questionnaire')])
    text = 'Question 3/3: Select your hobbies. Tap each item to toggle it, then press Done.'
    await safe_edit_or_send(query, context, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'create_profile':
        user_id = query.from_user.id
        set_questionnaire(user_id, {'age': None, 'gender': None, 'hobbies': []})
        await ask_age(query, context)
    elif query.data == 'find_similar':
        await safe_edit_or_send(query, context, 'Finding people similar to you...')
    elif query.data == 'browse_groups':
        await safe_edit_or_send(query, context, 'Browsing groups for you...')
    elif query.data.startswith('age:'):
        user_id = query.from_user.id
        age = query.data.split(':', 1)[1]
        questionnaire = get_questionnaire(user_id)
        questionnaire['age'] = age
        set_questionnaire(user_id, questionnaire)
        await ask_age(query, context)
    elif query.data == 'next_gender':
        user_id = query.from_user.id
        questionnaire = get_questionnaire(user_id)
        if not questionnaire.get('age'):
            await ask_age(query, context, error='Please select your age range before continuing.')
        else:
            await ask_gender(query, context)
    elif query.data.startswith('gender:'):
        user_id = query.from_user.id
        gender = query.data.split(':', 1)[1]
        questionnaire = get_questionnaire(user_id)
        questionnaire['gender'] = gender
        set_questionnaire(user_id, questionnaire)
        await ask_gender(query, context)
    elif query.data == 'next_hobbies':
        user_id = query.from_user.id
        questionnaire = get_questionnaire(user_id)
        if not questionnaire.get('gender'):
            await ask_gender(query, context, error='Please select your gender before continuing.')
        else:
            await ask_hobbies(query, context)
    elif query.data.startswith('hobby:'):
        user_id = query.from_user.id
        hobby = query.data.split(':', 1)[1]
        questionnaire = get_questionnaire(user_id)
        hobbies = questionnaire.setdefault('hobbies', [])
        if hobby in hobbies:
            hobbies.remove(hobby)
        else:
            hobbies.append(hobby)
        set_questionnaire(user_id, questionnaire)
        await ask_hobbies(query, context)
    elif query.data == 'done_questionnaire':
        user_id = query.from_user.id
        questionnaire = get_questionnaire(user_id)
        mark_profile_completed(user_id)
        print('Questionnaire answers for', user_id, questionnaire)
        await safe_edit_or_send(
            query,
            context,
            'Thank you! Your answers have been recorded. We will use them to find a good group for you.'
        )

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # await update.message.reply_text(response)
    logging.info("UPDATE: " + str(update))
    loading_message = await update.message.reply_text('Thinking...')

    # send the user message to the ChatGPT client
    response = gpt.submit(update.message.text)

    # send the response to the Telegram box client
    await loading_message.edit_text(response)

if __name__ == '__main__':
    main()

