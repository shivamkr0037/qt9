import json
import string
import random
import logging
import datetime
import shutil
import glob
import os
from filelock import FileLock
from collections import defaultdict
from threading import Timer
from telegram.ext import CallbackContext
from telegram import Update, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

user_file = 'user_data.json'
promo_file = 'promo_codes.json'
LOG_CHANNEL_ID = '-1002224010991'  # Replace with your log channel ID
GROUP_DATA_FILE = 'group_data.json'
BOT_USERNAME = 'Bingchattbot'  # Replace with your bot's username
ADMIN_ID = '5625250646'
# In-memory cache for user data
user_data_cache = defaultdict(dict)

# Global variable for the flush timer
flush_timer = None

def load_user_data():
    try:
        with open(user_file, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error("Corrupted JSON file detected, attempting recovery...")
        try:
            # Try to load from most recent backup
            backup_files = sorted(glob.glob(f"{user_file}.*.backup"))
            if backup_files:
                with open(backup_files[-1], 'r') as f:
                    data = json.load(f)
                # Save recovered data
                save_user_data(data)
                return data
        except Exception as e:
            logger.error(f"Recovery failed: {e}")
            return {}
    except FileNotFoundError:
        return {}
def validate_user_data(data):
    required_fields = {'user_id', 'request_count', 'subscription'}
    
    for user_id, user_data in data.items():
        if not all(field in user_data for field in required_fields):
            logger.error(f"Invalid data structure for user {user_id}")
            return False
        
        # Validate data types
        if not isinstance(user_data.get('request_count'), int):
            user_data['request_count'] = 0
            
        if not isinstance(user_data.get('subscription'), str):
            user_data['subscription'] = 'inactive'
            
    return True

def save_user_data(data):
    lock = FileLock("user_data.json.lock")
    with lock:
        try:
            if not isinstance(data, dict):
                raise ValueError("Data must be a dictionary.")
                
            if not validate_user_data(data):
                raise ValueError("Invalid data structure")
                
            with open(user_file, 'w') as f:
                json.dump(data, f, indent=4)
                
        except (IOError, ValueError) as e:
            logger.error(f"Error saving user data: {e}")



def load_promo_codes():
    try:
        with open(promo_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_promo_code(promo_code):
    promo_codes = load_promo_codes()
    expiry_date = (datetime.datetime.now() + datetime.timedelta(days=30)).strftime('%Y-%m-%d')
    promo_codes.append({'code': promo_code, 'expiry': expiry_date, 'used': False})
    with open(promo_file, 'w') as f:
        json.dump(promo_codes, f, indent=4)

def save_promo_codes(promo_codes):
    with open(promo_file, 'w') as f:
        json.dump(promo_codes, f, indent=4)

def generate_promo_code():
    prefix = 'GPT-'
    suffix = '-GPT'
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return prefix + random_chars + suffix

def log_user_data(update: Update, context: CallbackContext):
    # If command is used in group, prompt for DM
    if update.message.chat.type in ['group', 'supergroup']:
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

    # Only proceed with user registration if in private chat
    user_id = str(update.message.from_user.id)
    if user_id not in user_data_cache:
        user_data_cache[user_id] = {
            'user_id': user_id,
            'request_count': 0,
            'last_request_time': None,
            'subscription': 'inactive',
            'sub_end': None
        }
        print(f"New user added to cache: {user_id}")
        context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=f"A new user with user ID {user_id} has started the bot.")
    
    update.message.reply_text(
        'Welcome to Question Ai! 🤖 I\'m here to assist you with all sorts of questions, from math and science to general knowledge and programming. '
        'To get started, just send me your questions in text format or cropped image and ask for help. Let\'s embark on a learning journey together! 🚀'
    )

def balance(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    user = user_data_cache.get(user_id, {})
    subscription_status = user.get('subscription', 'inactive')

    if subscription_status == 'active':
        subscription_end_str = user.get('sub_end', '')
        subscription_end_date = datetime.datetime.strptime(subscription_end_str, '%Y-%m-%d')
        days_left = (subscription_end_date - datetime.datetime.now()).days
        
        if days_left < 0:
            user['subscription'] = 'inactive'
            user['request_count'] = 0
            user['sub_end'] = None
            response = (
                f"🟣 **Your Subscription**:\n"
                f"   ⤷ You have no active subscription. Please contact the admin by clicking [here](https://t.me/yucant) to buy. 💬\n"
                f"🟣 **Your Questions Pack**:\n"
                f"   ⤷ Questions left: {20 - user.get('request_count', 0)}/20"
            )
        else:
            response = (
                f"🟣 **Your Subscription**:\n"
                f"    Subscribed ✅\n"
                f"   ⤷ Days Left: {days_left}\n"
                f"🟣 **Your Questions Pack**:\n"
                f"   ⤷ Questions left: Unlimited ♾️"
            )
    else:
        response = (
            f"🟣 **Your Subscription**:\n"
            f"   ⤷ You have no active subscription. Please contact the admin by clicking [here](https://t.me/yucant) to buy. 💬\n"
            f"🟣 **Your Questions Pack**:\n"
            f"   ⤷ Questions left: {20 - user.get('request_count', 0)}/20"
        )
    
    update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)

def generate_promo(update: Update, context: CallbackContext):
    promo_code = generate_promo_code()
    save_promo_code(promo_code)
    update.message.reply_text(
        f"Here is your promo code: `{promo_code}`. Use it to claim your premium subscription. Please copy and paste this: `/claim {promo_code}`.",
        parse_mode=ParseMode.MARKDOWN
    )

def claim_promo(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    promo_code = context.args[0]
    user = user_data_cache.get(user_id, {})
    subscription_status = user.get('subscription', 'inactive')

    if subscription_status == 'active':
        update.message.reply_text("You already have an active premium subscription. You cannot claim another promo code.")
        return

    promo_codes = load_promo_codes()
    promo_details = next((item for item in promo_codes if item['code'] == promo_code and not item['used']), None)
    if promo_details:
        if datetime.datetime.now() <= datetime.datetime.strptime(promo_details['expiry'], '%Y-%m-%d'):
            user['subscription'] = 'active'
            user['sub_end'] = promo_details['expiry']
            promo_details['used'] = True
            save_promo_codes(promo_codes)
            update.message.reply_text("Congratulations! You are now a pro user. Please do /balance to check your status.")
        else:
            update.message.reply_text("Sorry, this promo code has expired.")
    else:
        update.message.reply_text("Sorry, the promo code is either invalid or has already been claimed.")

def start(update: Update, context: CallbackContext):
    log_user_data(update, context)

def backup_user_data():
    try:
        # Keep last 5 backups with timestamps
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = f"{user_file}.{timestamp}.backup"
        shutil.copy(user_file, backup_file)
        
        # Remove old backups (keep only last 5)
        backup_files = sorted(glob.glob(f"{user_file}.*.backup"))
        for old_backup in backup_files[:-5]:  # Keep last 5
            os.remove(old_backup)
            
    except IOError as e:
        logger.error(f"Error managing backups: {e}")

def flush_cache_to_file():
    global user_data_cache, flush_timer
    try:
        # Cancel existing timer if it exists
        if flush_timer is not None:
            flush_timer.cancel()

        if user_data_cache:
            # Load existing data from file
            existing_data = load_user_data()
            
            # Update existing data with cache data (preserve old data)
            existing_data.update(dict(user_data_cache))
            
            # Save the merged data back to file
            save_user_data(existing_data)
            
            logger.info(f"Cache flushed to file. Users in cache: {len(user_data_cache)}")
            print(f"Cache flushed to file. Current cache contents: {dict(user_data_cache)}")
            print(f"Total users in file after flush: {len(existing_data)}")
    except Exception as e:
        logger.error(f"Error in flush_cache_to_file: {e}")
        print(f"Error flushing cache: {e}")
    finally:
        # Create new timer
        flush_timer = Timer(600.0, flush_cache_to_file)
        flush_timer.daemon = True
        flush_timer.start()

# When loading the bot, load existing data into cache
def initialize_cache():
    global user_data_cache
    existing_data = load_user_data()
    for user_id, data in existing_data.items():
        user_data_cache[user_id] = data
    print(f"Initialized cache with {len(existing_data)} existing users")

# Call this when the bot starts
initialize_cache()

# Initialize the timer when the module loads
flush_timer = Timer(600.0, flush_cache_to_file)
flush_timer.daemon = True
flush_timer.start()

# Schedule backup every hour
Timer(3600, backup_user_data).start()

def print_cache_status():
    print("\nCache Status:")
    print(f"Users in cache: {len(user_data_cache)}")
    print(f"Cache contents: {dict(user_data_cache)}")
    
    file_data = load_user_data()
    print(f"\nFile Status:")
    print(f"Users in file: {len(file_data)}")
    print(f"File contents: {file_data}")

# Call this periodically or add as a command handler
Timer(600, print_cache_status).start()

def reset_all_counts(update: Update, context: CallbackContext):
    user_id = str(update.message.from_user.id)
    # Add your admin/owner ID here for security
    ADMIN_ID = "629986639"  # Replace with your actual Telegram ID
    
    if user_id != ADMIN_ID:
        update.message.reply_text("⚠️ Sorry, only the bot admin can use this command.")
        return
        
    try:
        # Reset counts in cache
        for user_data in user_data_cache.values():
            user_data['request_count'] = 0
            user_data['last_request_time'] = None
            
        # Reset counts in file
        file_data = load_user_data()
        for user_data in file_data.values():
            user_data['request_count'] = 0
            user_data['last_request_time'] = None
        save_user_data(file_data)
        
        # Force an immediate cache flush
        flush_cache_to_file()
        
        update.message.reply_text(
            "✅ Successfully reset request counts for all users!\n"
            f"📊 Users affected: {len(user_data_cache)}"
        )
        
        # Log the action
        context.bot.send_message(
            chat_id=LOG_CHANNEL_ID,
            text=f"🔄 Admin ({user_id}) manually reset all user request counts."
        )
        
    except Exception as e:
        logger.error(f"Error in reset_all_counts: {e}")
        update.message.reply_text("❌ An error occurred while resetting counts. Please check logs.")

def load_group_data():
    try:
        with open(GROUP_DATA_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_group_data(data):
    with open(GROUP_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def handle_group_addition(update: Update, context: CallbackContext):
    # Skip if not a group chat
    if update.message.chat.type not in ['group', 'supergroup']:
        return

    chat = update.message.chat
    chat_id = str(chat.id)
    
    # Load existing group data
    groups = load_group_data()
    
    # Check if group is already registered
    if chat_id not in groups:
        group_info = {
            'name': chat.title,
            'added_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'link': chat.invite_link if chat.invite_link else 'Private Group',
            'is_allowed': False
        }
        groups[chat_id] = group_info
        save_group_data(groups)
        
        # Send notification to log channel
        log_message = (
            f"🔔 Bot added to new group!\n"
            f"📝 Group Name: {chat.title}\n"
            f"🆔 Group ID: {chat_id}\n"
            f"🔗 Invite Link: {chat.invite_link if chat.invite_link else 'Private Group'}\n"
            f"⏰ Added Time: {group_info['added_time']}"
        )
        context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_message, parse_mode=ParseMode.MARKDOWN)
        
        # Create "Start in DM" button
        keyboard = [[InlineKeyboardButton(
            "Start me in DM first", 
            url=f"https://t.me/{BOT_USERNAME}?start=true"
        )]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Send welcome message in group
        welcome_message = (
            "Thanks for adding me! 👋\n"
            "To use me in this group, please:\n"
            "1️⃣ Start me in DM first (click button below)\n"
            "2️⃣ Group admin must use /allowgroup to enable group usage\n\n"
            "❗️ Group admins can use /disallowgroup to disable group usage"
        )
        update.message.reply_text(welcome_message, reply_markup=reply_markup)

def allow_group(update: Update, context: CallbackContext):
    if update.message.chat.type not in ['group', 'supergroup']:
        update.message.reply_text("This command can only be used in groups!")
        return
        
    # Check if user is admin
    user_id = update.effective_user.id
    chat_id = str(update.message.chat.id)
    
    try:
        user_status = context.bot.get_chat_member(chat_id, user_id).status
        if user_status not in ['creator', 'administrator']:
            update.message.reply_text("⚠️ Only group administrators can use this command!")
            return
            
        groups = load_group_data()
        if chat_id in groups:
            groups[chat_id]['is_allowed'] = True
            save_group_data(groups)
            update.message.reply_text("✅ Bot has been enabled for this group!")
        else:
            update.message.reply_text("❌ Please remove and add the bot to the group again!")
            
    except Exception as e:
        logger.error(f"Error in allow_group: {e}")
        update.message.reply_text("An error occurred. Please try again later.")

def disallow_group(update: Update, context: CallbackContext):
    if update.message.chat.type not in ['group', 'supergroup']:
        update.message.reply_text("This command can only be used in groups!")
        return
        
    # Check if user is admin
    user_id = update.effective_user.id
    chat_id = str(update.message.chat.id)
    
    try:
        user_status = context.bot.get_chat_member(chat_id, user_id).status
        if user_status not in ['creator', 'administrator']:
            update.message.reply_text("⚠️ Only group administrators can use this command!")
            return
            
        groups = load_group_data()
        if chat_id in groups:
            groups[chat_id]['is_allowed'] = False
            save_group_data(groups)
            update.message.reply_text("❌ Bot has been disabled for this group!")
        else:
            update.message.reply_text("❌ Please remove and add the bot to the group again!")
            
    except Exception as e:
        logger.error(f"Error in disallow_group: {e}")
        update.message.reply_text("An error occurred. Please try again later.")
