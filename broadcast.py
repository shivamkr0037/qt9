import time
import random
import logging
import json
from collections import defaultdict
from telegram import Update, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackContext

# Import necessary functions from primo.py (adjust the import path as needed)
from primo import load_user_data, load_group_data, ADMIN_ID

# Initialize logging
logger = logging.getLogger(__name__)

# Ensure ADMIN_ID is defined; if not, define it here
ADMIN_ID = "5625250646"  # Replace with your actual Telegram ID as a string

def stats(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_ID:
        update.message.reply_text("⚠️ Sorry, only the bot admin can use this command.")
        return

    # Load user and group data
    user_data = load_user_data()
    group_data = load_group_data()

    total_users = len(user_data)
    total_groups = len(group_data)

    message = (
        f"� **Bot Statistics**:\n"
        f"👤 **Total Users**: {total_users}\n"
        f"👥 **Total Groups**: {total_groups}\n"
    )

    # Add a refresh button
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="refresh_stats")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

def button_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = str(query.from_user.id)
    query.answer()

    if user_id != ADMIN_ID:
        query.edit_message_text("⚠️ Sorry, only the bot admin can use this button.")
        return

    if query.data == "refresh_stats":
        # Load data again
        user_data = load_user_data()
        group_data = load_group_data()

        total_users = len(user_data)
        total_groups = len(group_data)

        message = (
            f"📊 **Bot Statistics**:\n"
            f"👤 **Total Users**: {total_users}\n"
            f"👥 **Total Groups**: {total_groups}\n"
        )

        # Add the refresh button again
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="refresh_stats")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    elif query.data == "confirm_broadcast":
        # Retrieve broadcast data from the bot's persistence
        broadcast_data = context.bot_data.get('broadcast_data')
        if not broadcast_data:
            query.edit_message_text("No broadcast data found.")
            return

        targets = broadcast_data.get('targets', [])
        message_text = broadcast_data.get('message_text', '')
        flags = broadcast_data.get('flags', [])
        reply_markup = broadcast_data.get('reply_markup', None)

        success_count = 0
        for target_id in targets:
            try:
                context.bot.send_message(chat_id=target_id, text=message_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
                success_count += 1
                if '-delay' in flags:
                    time.sleep(1)  # Sequential messaging delay
            except Exception as e:
                logger.error(f"Failed to send message to {target_id}: {e}")
                continue

        query.edit_message_text(f"✅ Broadcast completed. Message sent to {success_count} chats.")

        # Clean up
        context.bot_data.pop('broadcast_data', None)

def broadcast(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if user_id != ADMIN_ID:
        update.message.reply_text("⚠️ Sorry, only the bot admin can use this command.")
        return

    args = context.args
    if not args:
        update.message.reply_text("Please provide arguments. Usage: /broadcast -user|-group [rN] <message>")
        return

    # Parse the flags and message
    flags = []
    message_text = []
    random_count = None

    iterator = iter(args)
    for arg in iterator:
        if arg.startswith('-'):
            flags.append(arg)
        elif arg.startswith('r'):
            try:
                random_count = int(arg[1:])
            except ValueError:
                update.message.reply_text(f"Invalid random count: {arg}")
                return
        else:
            message_text.append(arg)
            message_text.extend(list(iterator))  # Append the rest of the message
            break

    message_text = ' '.join(message_text)

    if not message_text:
        update.message.reply_text("Please provide a message to broadcast.")
        return

    # Load user and group data
    user_data = load_user_data()
    group_data = load_group_data()

    # Determine targets
    targets = set()
    if '-user' in flags:
        targets.update(user_data.keys())
    if '-group' in flags:
        targets.update(group_data.keys())

    if not targets:
        update.message.reply_text("Please specify -user, -group, or both.")
        return

    # Handle random broadcasting
    targets = list(targets)
    if random_count is not None:
        targets = random.sample(targets, min(random_count, len(targets)))

    # Extract button text and link from message (if provided)
    # Format: {button}Button Text{link}https://example.com
    button_text = None
    button_link = None

    if '{button}' in message_text and '{link}' in message_text:
        try:
            text_before_button = message_text.split('{button}')[0]
            button_part = message_text.split('{button}')[1]
            button_text = button_part.split('{link}')[0]
            button_link = button_part.split('{link}')[1]
            message_text = text_before_button.strip()
        except IndexError:
            update.message.reply_text("Failed to parse button or link in the message.")
            return

    # Prepare the reply markup if button is included
    if button_text and button_link:
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(button_text.strip(), url=button_link.strip())]])
    else:
        reply_markup = None

    # Store the broadcast data in bot_data for use in the callback
    context.bot_data['broadcast_data'] = {
        'targets': targets,
        'message_text': message_text,
        'flags': flags,
        'reply_markup': reply_markup
    }

    # Prepare a sample message with a broadcast button
    keyboard = [[InlineKeyboardButton("Broadcast", callback_data="confirm_broadcast")]]
    preview_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text(
        f"🚀 **Broadcast Preview**:\n\n{message_text}\n\nClick 'Broadcast' to send.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=preview_markup
    )
