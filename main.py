import base64
import json
import logging
import datetime
import os
import requests
import threading
import time
from datetime import timedelta
from io import BytesIO
from threading import Timer
from collections import defaultdict
from telegram import Update, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from broadcast import stats, button_callback, broadcast  # Import from broadcast.py
from telegram.ext import CallbackQueryHandler
from primo import load_user_data, save_user_data, load_promo_codes, save_promo_code, generate_promo_code, log_user_data, balance, generate_promo, claim_promo, start, reset_all_counts, handle_group_addition, allow_group, disallow_group, load_group_data, save_group_data
import dall

# Initialize user data cache
user_data_cache = defaultdict(dict)

# Remove logging messages on the terminal
logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096
LOG_CHANNEL_ID = -1002224010991  # Replace with your log channel ID if needed
CHANNEL_ID = '-1002081366095'  # Replace with your channel's username or ID

# Dictionary to keep track of each user's conversation history
user_conversation_history = {}

BOT_USERNAME = 'Bingchattbot'  # Add this near your other constants

def get_access_token():
    url = "https://chatgpt-au.vulcanlabs.co/api/v1/token"
    headers = {
        "Host": "chatgpt-au.vulcanlabs.co",
        "x-vulcan-application-id": "com.smartwidgetlabs.chatgpt",
        "accept": "application/json",
        "user-agent": "Chat Smith Android, Version 3.6.2(548)",
        "x-vulcan-request-id": "9149487891712248906421",
        "content-type": "application/json; charset=utf-8",
        "accept-encoding": "gzip"
    }
    payload = {
        "device_id": "D82937F00D8C069D",
        "order_id": "",
        "product_id": "",
        "purchase_token": "",
        "subscription_id": ""
    }

    for _ in range(3):  # Retry up to 3 times
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            access_token = response.json().get("AccessToken")
            if access_token:
                return access_token
        time.sleep(20)  # Wait for 20 seconds before retrying

    return None  # Return None if all retries fail

def renew_token():
    global access_token
    while True:
        access_token = get_access_token()
        if access_token:
            print(f"Access Token: {access_token}")  # Print the token to the terminal
            break
        time.sleep(20)  # Wait for 20 seconds before retrying if token generation failed

    Timer(20 * 60, renew_token).start()  # Refresh token every 20 minutes

def send_message(access_token, user_message, conversation_history):
    url = "https://prod-smith.vulcanlabs.co/api/v6/chat"
    headers = {
        "Host": "prod-smith.vulcanlabs.co",
        "x-firebase-appcheck": "AppCheck",
        "authorization": f"Bearer {access_token}",
        "x-vulcan-application-id": "com.smartwidgetlabs.chatgpt",
        "accept": "application/json",
        "user-agent": "Chat Smith Android, Version 3.6.2(548)",
        "x-vulcan-request-id": "9149487891712225875945",
        "content-type": "application/json; charset=utf-8",
        "accept-encoding": "gzip"
    }
    data = {
        "model": "gpt-4o",
        "user": "D83837F00D8C069D",
        "messages": [{"role": "system", "content": "Your name is Question Ai. You specialize in math, general knowledge, science, etc. and many different subjects. You also specialize in programming. You can answer questions using photos uploaded by users. Sometimes you ask them to send a photo of the question. You always give short and general answers, but if you are asked for clarification, you answer in a long paragraph.you always send the programming code snippets without explanation and comments and explains only when user ask for it.Don't use latex formatting"}] + conversation_history + [
            {"role": "user", "content": user_message}
        ],
        "nsfw_check": True
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        response_json = response.json()
        try:
            assistant_message = response_json['choices'][0]['Message']['content']
            # Regenerate token if the response is empty
            if not assistant_message:
                renew_token()
                assistant_message = send_message(access_token, user_message, conversation_history)
            return assistant_message
        except KeyError:
            return None
    else:
        return None

def check_channel_membership(user_id, bot):
    try:
        member_status = bot.get_chat_member(CHANNEL_ID, user_id).status
        return member_status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Error checking channel membership: {e}")
        return False

def set_log_channel(update: Update, context: CallbackContext) -> None:
    global LOG_CHANNEL_ID
    if str(update.message.from_user.id) == OWNER_ID:
        if len(context.args) == 1:
            LOG_CHANNEL_ID = context.args[0]

def handle_message(update: Update, context: CallbackContext) -> None:
    # First check if message is from a group
    if update.message.chat.type in ['group', 'supergroup']:
        chat_id = str(update.message.chat.id)
        user_id = str(update.message.from_user.id)
        
        # Load group data
        groups = load_group_data()
        
        # Check if group exists and is allowed
        if chat_id not in groups or not groups[chat_id].get('is_allowed', False):
            return  # Silently ignore messages in unauthorized groups
        
        # Check if user has started the bot in DM using primo's cache
        from primo import user_data_cache as primo_cache
        if user_id not in primo_cache:  # Changed this line
            keyboard = [[InlineKeyboardButton(
                "Start me in DM first", 
                url=f"https://t.me/{BOT_USERNAME}?start=true"
            )]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                "⚠️ Please start me in direct message first!\n"
                "Click the button below to start a chat with me in DM."
            )
            update.message.reply_text(message, reply_markup=reply_markup)
            return
    
    user_id = str(update.message.from_user.id)
    
    # First check primo's cache
    from primo import user_data_cache as primo_cache
    user = primo_cache.get(user_id)
    
    # If not found in primo's cache, check JSON file
    if user is None:
        user_data = load_user_data()
        user = user_data.get(user_id)
        if user is not None:
            # Update primo's cache if found in file
            primo_cache[user_id] = user.copy()
            print(f"User {user_id} loaded from file to cache")  # Debug print
    
    if user is not None:
        # Ensure conversation history is always a list
        if user_id not in user_conversation_history:
            user_conversation_history[user_id] = []

        # Check request limits and channel membership
        if user.get('request_count', 0) >= 20 and user.get('subscription', 'inactive') != 'active':
            message = (
                f"⚠️ You've reached the daily limit of 20 questions.\n\n"
                f"♻️ Your limit will reset soon. Please check back later after a few hours!\n"
                f"💎 Want unlimited access? Contact @yucant to upgrade to premium!"
            )
            update.message.reply_text(message)
            return

        if user.get('subscription', 'inactive') != 'active' and not check_channel_membership(user_id, context.bot):
            join_button = InlineKeyboardButton("Join Channel", url=f"https://t.me/BotCommunityHub")
            reply_markup = InlineKeyboardMarkup([[join_button]])
            update.message.reply_text(
                "You must join our channel to use this bot. Please join and then send a message to start using the bot.",
                reply_markup=reply_markup
            )
            return

        user_message = update.message.text
        placeholder_message = update.message.reply_text("📝")

        # Update request count in both caches
        user['request_count'] = user.get('request_count', 0) + 1
        user['last_request_time'] = datetime.datetime.now().isoformat()
        user_data_cache[user_id] = user.copy()
        from primo import user_data_cache as primo_cache
        primo_cache[user_id] = user.copy()

        # Send the message to the assistant
        assistant_message = send_message(access_token, user_message, user_conversation_history[user_id])
        if assistant_message:
            user_conversation_history[user_id].append({"role": "user", "content": user_message})
            user_conversation_history[user_id].append({"role": "assistant", "content": assistant_message})

            # Handle response length and send it back to the user
            if len(assistant_message) <= MAX_MESSAGE_LENGTH:
                context.bot.edit_message_text(
                    text=assistant_message,
                    chat_id=update.message.chat_id,
                    message_id=placeholder_message.message_id,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # Handle long messages by saving to a file
                file_path = f'response_{user_id}.txt'
                with open(file_path, 'w') as file:
                    file.write(assistant_message)

                context.bot.delete_message(
                    chat_id=update.message.chat_id,
                    message_id=placeholder_message.message_id
                )

                with open(file_path, 'rb') as file:
                    update.message.reply_document(file)

                os.remove(file_path)

            # Save the updated user data to the cache
            user_data_cache[user_id] = user

            # Reset conversation history based on subscription status
            if user.get('subscription', 'inactive') == 'active':
                # Premium users get 35 messages each (70 total)
                if len(user_conversation_history[user_id]) >= 70:
                    user_conversation_history[user_id] = []
                    update.message.reply_text("Conversation history has been reset (reached premium limit of 35 exchanges).")
            else:
                # Free users get 6 messages each (12 total)
                if len(user_conversation_history[user_id]) >= 12:
                    user_conversation_history[user_id] = []
                    update.message.reply_text("Conversation history has been reset (reached free limit of 6 exchanges).")
        else:
            context.bot.edit_message_text(
                text="Sorry, there was an error processing your request.",
                chat_id=update.message.chat_id,
                message_id=placeholder_message.message_id
            )
        # Log user and bot conversation
        if LOG_CHANNEL_ID:
            log_message = f"User {update.message.from_user.id} sent: {user_message}\nBot replied: {assistant_message}"
            context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message)

    else:
        update.message.reply_text("Please start the bot using /start before using it.")
        return

def handle_image(update: Update, context: CallbackContext):
    # First check if message is from a group
    if update.message.chat.type in ['group', 'supergroup']:
        chat_id = str(update.message.chat.id)
        user_id = str(update.message.from_user.id)
        
        # Load group data
        groups = load_group_data()
        
        # Check if group exists and is allowed
        if chat_id not in groups or not groups[chat_id].get('is_allowed', False):
            return  # Silently ignore messages in unauthorized groups
            
        # Check if user has started the bot in DM using primo's cache
        from primo import user_data_cache as primo_cache
        if user_id not in primo_cache:
            keyboard = [[InlineKeyboardButton(
                "Start me in DM first", 
                url=f"https://t.me/{BOT_USERNAME}?start=true"
            )]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                "⚠️ Please start me in direct message first!\n"
                "Click the button below to start a chat with me in DM."
            )
            update.message.reply_text(message, reply_markup=reply_markup)
            return

    # Define your image-to-text API details
    API_URL = "https://ai-service-prod.compscilib.com/image-to-text"
    HEADERS = {
        "Connection": "keep-alive",
        "sec-ch-ua": "\"Not/A)Brand\";v=\"8\", \"Chromium\";v=\"126\", \"Google Chrome\";v=\"126\"",
        "sec-ch-ua-platform": "\"Android\"",
        "sec-ch-ua-mobile": "?1",
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://www.compscilib.com",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://www.compscilib.com/",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    user_id = str(update.message.from_user.id)
    
    # First check primo's cache
    from primo import user_data_cache as primo_cache
    user = primo_cache.get(user_id)
    
    # If not found in primo's cache, check JSON file
    if user is None:
        user_data = load_user_data()
        user = user_data.get(user_id)
        if user is not None:
            # Update primo's cache if found in file
            primo_cache[user_id] = user.copy()
    
    if user is None:
        update.message.reply_text("Please start the bot using /start before using it.")
        return

    # Check request limits and channel membership
    if user.get('request_count', 0) >= 20 and user.get('subscription', 'inactive') != 'active':
        message = (
            f"⚠️ You've reached the daily limit of 20 questions.\n\n"
            f"♻️ Your limit will reset soon. Please check back later after a few hours!\n"
            f"💎 Want unlimited access? Contact @yucant to upgrade to premium!"
        )
        update.message.reply_text(message)
        return

    # Update request count in both caches
    user['request_count'] = user.get('request_count', 0) + 1
    user['last_request_time'] = datetime.datetime.now().isoformat()
    user_data_cache[user_id] = user.copy()
    primo_cache[user_id] = user.copy()  # Update primo's cache too

    if user.get('subscription', 'inactive') != 'active' and not check_channel_membership(user_id, context.bot):
        join_button = InlineKeyboardButton("Join Channel", url=f"https://t.me/BotCommunityHub")
        reply_markup = InlineKeyboardMarkup([[join_button]])
        update.message.reply_text(
            "You must join our channel to use this bot. Please join and then send a message to start using the bot.",
            reply_markup=reply_markup
        )
        return

    # Download and encode the photo
    photo = update.message.photo[-1]
    file = context.bot.get_file(photo.file_id)
    photo_bytes = BytesIO()
    file.download(out=photo_bytes)
    photo_bytes.seek(0)

    encoded_string = base64.b64encode(photo_bytes.read()).decode('utf-8')

    data = {
        "files": [f"data:image/jpeg;base64,{encoded_string}"]
    }

    # Send the encoded image to the new API
    response = requests.post(API_URL, headers=HEADERS, json=data)

    if response.status_code == 200:
        response_text = response.text
        formatted_text = response_text.replace('\n\n', ' ')
        formatted_text += " Explain in plain text format, don't use latex format, don't use frac \\int or $ in your answer"

        # Ensure conversation history is always a list
        if user_id not in user_conversation_history:
            user_conversation_history[user_id] = []

        progress_message = update.message.reply_text("✨")
        gpt_response = send_message(access_token, formatted_text, user_conversation_history[user_id])

        update.message.reply_text(gpt_response)
        context.bot.delete_message(chat_id=progress_message.chat_id, message_id=progress_message.message_id)

        if LOG_CHANNEL_ID:
            log_message = f"User {update.message.from_user.id} sent: {formatted_text}\nBot replied: {gpt_response}"
            context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message)

        user_conversation_history[user_id].append({"role": "user", "content": formatted_text})
        user_conversation_history[user_id].append({"role": "assistant", "content": gpt_response})

        # Reset conversation history based on subscription status
        if user.get('subscription', 'inactive') == 'active':
            # Premium users get 35 messages each (70 total)
            if len(user_conversation_history[user_id]) >= 70:
                user_conversation_history[user_id] = []
                update.message.reply_text("Conversation history has been reset (reached premium limit of 35 exchanges).")
        else:
            # Free users get 6 messages each (12 total)
            if len(user_conversation_history[user_id]) >= 12:
                user_conversation_history[user_id] = []
                update.message.reply_text("Conversation history has been reset (reached free limit of 6 exchanges).")

        # Make sure to update both caches again if needed
        user_data_cache[user_id] = user.copy()
        primo_cache[user_id] = user.copy()
    else:
        update.message.reply_text("Failed to process the image. Please try again later.")

def reset_conversation(update: Update, context: CallbackContext) -> None:
    user_id = str(update.message.from_user.id)
    user_conversation_history[user_id] = []
    update.message.reply_text("Conversation history has been reset.")

def reset_request_count():
    while True:
        time.sleep(60)
        user_data = load_user_data()
        now = datetime.datetime.now()
        for user_id, data in user_data.items():
            last_request_time = datetime.datetime.fromisoformat(data.get('last_request_time')) if data.get('last_request_time') else None
            if last_request_time and now - last_request_time >= timedelta(minutes=60):
                data['request_count'] = 0
                data['last_request_time'] = None
        save_user_data(user_data)


def main():
    global access_token
    access_token = get_access_token()
    if access_token:
        print(f"Initial Access Token: {access_token}")
    else:
        renew_token()  # Ensure the token is renewed if initial generation fails

    Timer(20 * 60, renew_token).start()  # Refresh token every 20 minutes

    # Start the thread to reset user request count
    reset_thread = threading.Thread(target=reset_request_count)
    reset_thread.daemon = True
    reset_thread.start()

    updater = Updater('6283505564:AAHofRWeAZ0LbKbRaIADQX-LYig-xONHiss', use_context=True)

    dispatcher = updater.dispatcher
    dispatcher.add_handler(CommandHandler('stats', stats, run_async=True))
    dispatcher.add_handler(CommandHandler('broadcast', broadcast, pass_args=True, run_async=True))
    dispatcher.add_handler(CommandHandler('start', start, run_async=True))
    # Callback query handler for buttons
    dispatcher.add_handler(CallbackQueryHandler(button_callback , run_async=True))
    dispatcher.add_handler(CommandHandler('balance', balance, run_async=True))
    dispatcher.add_handler(CommandHandler('gencharlie037', generate_promo, run_async=True))
    dispatcher.add_handler(CommandHandler('claim', claim_promo, pass_args=True, run_async=True))
    dispatcher.add_handler(CommandHandler('reset', reset_conversation, run_async=True))
    dispatcher.add_handler(CommandHandler('resetcount', reset_all_counts, run_async=True))
    dispatcher.add_handler(CommandHandler('setlogchannel', set_log_channel, pass_args=True, run_async=True))
    dispatcher.add_handler(CommandHandler('dalle3', dall.dalle3, pass_args=True, run_async=True))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message, run_async=True))
    dispatcher.add_handler(MessageHandler(Filters.photo, handle_image, run_async=True))
    dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, handle_group_addition))
    dispatcher.add_handler(CommandHandler('allowgroup', allow_group))
    dispatcher.add_handler(CommandHandler('disallowgroup', disallow_group))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
    
