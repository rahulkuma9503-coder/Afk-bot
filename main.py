import os
import time
import re
import logging
import asyncio
import threading
import random
import string
from datetime import datetime
from flask import Flask
from pyrogram import Client, filters, enums, idle
from pyrogram.types import (
    Message, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    InputMediaPhoto,
    CallbackQuery
)
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram.errors import PeerIdInvalid, ChatAdminRequired

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_USERNAME = os.getenv("BOT_USERNAME")
MONGODB_URI = os.getenv("MONGODB_URI")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
PORT = int(os.getenv("PORT", 8080))

# Bot start time for uptime calculation
START_TIME = time.time()

# Initialize MongoDB
mongo_client = AsyncIOMotorClient(MONGODB_URI)
db = mongo_client.afk_db
afk_collection = db.afk
users_collection = db.users  # For user stats
groups_collection = db.groups  # For tracking groups
broadcast_collection = db.broadcast_tmp  # For temporary broadcast data

# Helper functions
def get_readable_time(seconds: int) -> str:
    result = ''
    days, seconds = divmod(seconds, 86400)
    if days != 0:
        result += f'{days}d '
    hours, seconds = divmod(seconds, 3600)
    if hours != 0:
        result += f'{hours}h '
    minutes, seconds = divmod(seconds, 60)
    if minutes != 0:
        result += f'{minutes}m '
    seconds = int(seconds)
    result += f'{seconds}s'
    return result

def generate_random_id(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

async def add_afk(user_id: int, details: dict):
    await afk_collection.update_one(
        {"user_id": user_id},
        {"$set": details},
        upsert=True
    )

async def is_afk(user_id: int):
    data = await afk_collection.find_one({"user_id": user_id})
    if data:
        return True, data
    return False, {}

async def remove_afk(user_id: int):
    await afk_collection.delete_one({"user_id": user_id})

async def add_user(user_id: int):
    await users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"last_seen": datetime.now()}},
        upsert=True
    )

async def count_users():
    return await users_collection.count_documents({})

async def count_afk_users():
    return await afk_collection.count_documents({})

# Track groups
async def track_group(chat_id: int, chat_title: str):
    await groups_collection.update_one(
        {"chat_id": chat_id},
        {"$set": {
            "title": chat_title,
            "last_active": datetime.now()
        }},
        upsert=True
    )

async def count_groups():
    return await groups_collection.count_documents({})

async def get_all_groups():
    groups = []
    async for group in groups_collection.find({}):
        groups.append(group)
    return groups

# Create Flask server for health checks
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "AFK Bot is running! 🚀", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT)

# Bot initialization
class Bot(Client):
    def __init__(self):
        super().__init__(
            "afk_bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True
        )
    
    async def start(self):
        await super().start()
        logger.info("Bot client started successfully")
        
        # Send startup notification to owner
        if OWNER_ID:
            try:
                await self.send_message(
                    OWNER_ID,
                    "✅ AFK Bot Started Successfully!\n"
                    f"🤖 Username: @{BOT_USERNAME}"
                )
            except Exception as e:
                logger.error(f"Startup notification failed: {e}")
    
    async def stop(self):
        await super().stop()
        logger.info("Bot client stopped")

app = Bot()

# Track bot start time for uptime
BOT_START_TIME = time.time()

# Track when bot is added to a group
@app.on_message(filters.new_chat_members)
async def new_chat_members(_, message: Message):
    if message.new_chat_members:
        for member in message.new_chat_members:
            if member.id == (await app.get_me()).id:
                await track_group(
                    message.chat.id,
                    message.chat.title
                )
                logger.info(f"Bot added to group: {message.chat.title} ({message.chat.id})")

# Start command handler with new image and message
@app.on_message(filters.command(["start", "help"]))
async def start_command(_, message: Message):
    user = message.from_user
    uptime = get_readable_time(int(time.time() - BOT_START_TIME))
    
    # Track group if in a group
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        await track_group(
            message.chat.id,
            message.chat.title
        )
    
    # Add user to database for stats
    if user:
        await add_user(user.id)
    
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Add to Group ➕",
                    url=f"https://t.me/{BOT_USERNAME}?startgroup=true",
                )
            ],
            [
                InlineKeyboardButton("Help ❓", callback_data="help"),
                InlineKeyboardButton("Owner 👤", url="https://t.me/mr_rahul090"),
            ],
            [
                InlineKeyboardButton("Support Group", url="https://t.me/team_secrat_bots")
            ]
        ]
    )
    
    text = f"""
Hello! I'm AFK BOT.

Active since {uptime}

Use /help for more info.
"""
    
    # Send photo with caption and buttons
    await message.reply_photo(
        photo="https://i.ibb.co/kVYPDqRC/tmp5h-atl08.jpg",
        caption=text,
        reply_markup=keyboard
    )

# Help callback handler
@app.on_callback_query(filters.regex("^help$"))
async def help_callback(_, query):
    await query.answer()
    help_text = """
**📖 AFK Bot Guide**

**To set AFK:**
- `/afk` or `brb` - Set basic AFK
- `/afk [reason]` or `brb [reason]` - Set AFK with reason
- Reply to a photo/GIF with `/afk` or `brb` - Set media AFK

**When AFK:**
- Bot will notify when you're mentioned
- Shows duration and reason you've been AFK
- Media AFK will display your image/GIF

**When back:**
- Send any message to disable AFK
- Bot will notify with AFK duration

**Other Commands:**
- /stats - Show bot statistics
"""
    
    await query.message.edit_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="back_to_start")]]
        ),
    )

# Back to start callback handler
@app.on_callback_query(filters.regex("^back_to_start$"))
async def back_callback(_, query):
    await query.answer()
    user = query.from_user
    uptime = get_readable_time(int(time.time() - BOT_START_TIME))
    
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Add to Group ➕",
                    url=f"https://t.me/{BOT_USERNAME}?startgroup=true",
                )
            ],
            [
                InlineKeyboardButton("Help ❓", callback_data="help"),
                InlineKeyboardButton("Owner 👤", url="https://t.me/mr_rahul090"),
            ],
            [
                InlineKeyboardButton("Support Group", url="https://t.me/team_secrat_bots")
            ]
        ]
    )
    
    text = f"""
Hello! I'm AFK BOT.

Active since {uptime}

Use /help for more info.
"""
    
    # Edit message with photo
    await query.message.edit_media(
        media=InputMediaPhoto(
            media="https://i.ibb.co/kVYPDqRC/tmp5h-atl08.jpg",
            caption=text
        ),
        reply_markup=keyboard
    )

# AFK handler
@app.on_message(filters.command(["afk"], prefixes=["/", "!"]) | filters.regex(r"^brb\b", re.IGNORECASE))
async def afk_handler(_, message: Message):
    if message.sender_chat:
        return
        
    user_id = message.from_user.id
    verifier, reasondb = await is_afk(user_id)
    
    # Track group if in a group
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        await track_group(
            message.chat.id,
            message.chat.title
        )
    
    # Add user to database for stats
    await add_user(user_id)
    
    # Extract command and reason from message
    if message.text and message.text.lower().startswith("brb"):
        parts = message.text.split(" ", 1)
        reason_text = parts[1] if len(parts) > 1 else None
    else:
        reason_text = " ".join(message.command[1:]) if len(message.command) > 1 else None
    
    # User is returning from AFK
    if verifier:
        await remove_afk(user_id)
        try:
            afktype = reasondb["type"]
            timeafk = reasondb["time"]
            data = reasondb["data"]
            reasonafk = reasondb["reason"]
            seenago = get_readable_time((int(time.time() - timeafk)))
            
            # Always show reason if it exists
            base_text = f"**{message.from_user.first_name}** is back online and was away for {seenago}"
            if reasonafk and str(reasonafk).lower() != "none":
                base_text += f"\n\nReason: `{reasonafk}`"
            
            if afktype == "animation":
                await message.reply_animation(
                    data,
                    caption=base_text,
                )
            elif afktype == "photo":
                await message.reply_photo(
                    photo=f"downloads/{user_id}.jpg",
                    caption=base_text,
                )
            else:
                await message.reply_text(
                    base_text,
                    disable_web_page_preview=True,
                )
        except Exception as e:
            logger.error(f"Error in AFK return: {e}")
            await message.reply_text(
                f"**{message.from_user.first_name}** is back online",
                disable_web_page_preview=True,
            )
        return

    # Setting new AFK status
    details = {
        "type": "text",
        "time": time.time(),
        "data": None,
        "reason": reason_text[:100] if reason_text else None,  # Truncate long reasons
    }

    # Handle media in the same message
    if message.animation:
        details = {
            "type": "animation",
            "time": time.time(),
            "data": message.animation.file_id,
            "reason": reason_text[:100] if reason_text else None,
        }
    elif message.photo:
        try:
            os.makedirs("downloads", exist_ok=True)
            await message.download(file_name=f"downloads/{user_id}.jpg")
            details = {
                "type": "photo",
                "time": time.time(),
                "data": None,
                "reason": reason_text[:100] if reason_text else None,
            }
        except Exception as e:
            logger.error(f"Error downloading photo: {e}")
            await message.reply_text("Failed to download media, using text AFK")
    # Handle reply to media
    elif message.reply_to_message:
        if message.reply_to_message.animation:
            details = {
                "type": "animation",
                "time": time.time(),
                "data": message.reply_to_message.animation.file_id,
                "reason": reason_text[:100] if reason_text else None,
            }
        elif message.reply_to_message.photo:
            try:
                os.makedirs("downloads", exist_ok=True)
                await message.reply_to_message.download(file_name=f"downloads/{user_id}.jpg")
                details = {
                    "type": "photo",
                    "time": time.time(),
                    "data": None,
                    "reason": reason_text[:100] if reason_text else None,
                }
            except Exception as e:
                logger.error(f"Error downloading photo: {e}")
                await message.reply_text("Failed to download media, using text AFK")
        elif (message.reply_to_message.sticker and 
              not message.reply_to_message.sticker.is_animated):
            try:
                os.makedirs("downloads", exist_ok=True)
                await message.reply_to_message.download(file_name=f"downloads/{user_id}.jpg")
                details = {
                    "type": "photo",
                    "time": time.time(),
                    "data": None,
                    "reason": reason_text[:100] if reason_text else None,
                }
            except Exception as e:
                logger.error(f"Error downloading sticker: {e}")
                await message.reply_text("Failed to download media, using text AFK")

    # Save AFK status to database
    await add_afk(user_id, details)
    response = f"**{message.from_user.first_name}** is now AFK"
    if details["reason"]:
        response += f"\n\nReason: `{details['reason']}`"
    await message.reply_text(response)

# AFK watcher
@app.on_message(
    filters.group & ~filters.bot & ~filters.me & ~filters.service,
    group=1
)
async def afk_watcher(_, message: Message):
    if not message.from_user:
        return
        
    userid = message.from_user.id
    user_name = message.from_user.first_name

    # Track group
    await track_group(
        message.chat.id,
        message.chat.title
    )
    
    # Add user to database for stats
    await add_user(userid)

    # Check if user is returning from AFK
    verifier, reasondb = await is_afk(userid)
    if verifier:
        # Skip if it's an AFK command
        if any(cmd in (message.text or message.caption or "").lower() 
               for cmd in ["/afk", "!afk", "brb"]):
            return
            
        # Remove AFK status and notify
        await remove_afk(userid)
        try:
            afktype = reasondb["type"]
            timeafk = reasondb["time"]
            data = reasondb["data"]
            reasonafk = reasondb["reason"]
            seenago = get_readable_time((int(time.time() - timeafk)))
            
            # Always show reason if it exists
            base_text = f"**{user_name}** is back online and was away for {seenago}"
            if reasonafk and str(reasonafk).lower() != "none":
                base_text += f"\n\nReason: `{reasonafk}`"
            
            if afktype == "animation":
                await message.reply_animation(
                    data,
                    caption=base_text,
                )
            elif afktype == "photo":
                await message.reply_photo(
                    photo=f"downloads/{userid}.jpg",
                    caption=base_text,
                )
            else:
                await message.reply_text(
                    base_text,
                    disable_web_page_preview=True,
                )
        except Exception as e:
            logger.error(f"Error in AFK return watcher: {e}")
            await message.reply_text(f"**{user_name}** is back online")

    # Check if replying to AFK user
    if message.reply_to_message and message.reply_to_message.from_user:
        try:
            replied_user = message.reply_to_message.from_user
            verifier, reasondb = await is_afk(replied_user.id)
            
            if verifier:
                afktype = reasondb["type"]
                timeafk = reasondb["time"]
                data = reasondb["data"]
                reasonafk = reasondb["reason"]
                seenago = get_readable_time((int(time.time() - timeafk)))
                
                # Always show reason if it exists
                base_text = f"**{replied_user.first_name}** is AFK since {seenago}"
                if reasonafk and str(reasonafk).lower() != "none":
                    base_text += f"\n\nReason: `{reasonafk}`"
                
                if afktype == "animation":
                    await message.reply_animation(data, caption=base_text)
                elif afktype == "photo":
                    await message.reply_photo(
                        photo=f"downloads/{replied_user.id}.jpg",
                        caption=base_text
                    )
                else:
                    await message.reply_text(base_text)
        except Exception as e:
            logger.error(f"Error in AFK reply watcher: {e}")

    # Check mentioned users
    if message.entities and message.text:
        for entity in message.entities:
            if entity.type == enums.MessageEntityType.MENTION:
                try:
                    mentioned_text = message.text[entity.offset:entity.offset + entity.length]
                    mentioned_username = mentioned_text[1:]
                    
                    if mentioned_username.lower() == BOT_USERNAME.lower():
                        continue
                    
                    try:
                        user = await app.get_users(mentioned_username)
                    except PeerIdInvalid:
                        continue
                        
                    if user.id == message.from_user.id:
                        continue
                        
                    verifier, reasondb = await is_afk(user.id)
                    if verifier:
                        afktype = reasondb["type"]
                        timeafk = reasondb["time"]
                        data = reasondb["data"]
                        reasonafk = reasondb["reason"]
                        seenago = get_readable_time((int(time.time() - timeafk)))
                        
                        # Always show reason if it exists
                        base_text = f"**{user.first_name}** is AFK since {seenago}"
                        if reasonafk and str(reasonafk).lower() != "none":
                            base_text += f"\n\nReason: `{reasonafk}`"
                        
                        if afktype == "animation":
                            await message.reply_animation(data, caption=base_text)
                        elif afktype == "photo":
                            await message.reply_photo(
                                photo=f"downloads/{user.id}.jpg",
                                caption=base_text
                            )
                        else:
                            await message.reply_text(base_text)
                except Exception as e:
                    logger.error(f"Error handling mention: {e}")
                    
            elif entity.type == enums.MessageEntityType.TEXT_MENTION:
                try:
                    user = entity.user
                    if user.id == message.from_user.id:
                        continue
                        
                    verifier, reasondb = await is_afk(user.id)
                    if verifier:
                        afktype = reasondb["type"]
                        timeafk = reasondb["time"]
                        data = reasondb["data"]
                        reasonafk = reasondb["reason"]
                        seenago = get_readable_time((int(time.time() - timeafk)))
                        
                        # Always show reason if it exists
                        base_text = f"**{user.first_name}** is AFK since {seenago}"
                        if reasonafk and str(reasonafk).lower() != "none":
                            base_text += f"\n\nReason: `{reasonafk}`"
                        
                        if afktype == "animation":
                            await message.reply_animation(data, caption=base_text)
                        elif afktype == "photo":
                            await message.reply_photo(
                                photo=f"downloads/{user.id}.jpg",
                                caption=base_text
                            )
                        else:
                            await message.reply_text(base_text)
                except Exception as e:
                    logger.error(f"Error handling text mention: {e}")

# Helper function for user broadcasting
async def broadcast_to_users(message, broadcast_type, text=None, replied_msg=None):
    total = 0
    success = 0
    failed = 0
    
    users = await users_collection.distinct("user_id")
    total_users = len(users)
    
    status = await message.reply_text(f"📤 Broadcasting to {total_users} users...")
    
    for user_id in users:
        try:
            if text:
                # Send text message
                await app.send_message(chat_id=user_id, text=text)
            elif replied_msg:
                # Handle replied message
                if broadcast_type == "bcast":
                    await app.copy_message(
                        chat_id=user_id,
                        from_chat_id=replied_msg.chat.id,
                        message_id=replied_msg.id
                    )
                else:  # fcast
                    await app.forward_messages(
                        chat_id=user_id,
                        from_chat_id=replied_msg.chat.id,
                        message_ids=replied_msg.id
                    )
            success += 1
        except Exception as e:
            failed += 1
            logger.error(f"Failed to send to {user_id}: {e}")
        
        total += 1
        if total % 100 == 0:
            await status.edit_text(f"👤 User broadcast: {total}/{total_users}")
    
    return total_users, success, failed, status

# Helper function for group broadcasting
async def broadcast_to_groups(message, broadcast_type, text=None, replied_msg=None, exclude_chat_id=None, pin_message=False):
    total = 0
    success = 0
    failed = 0
    
    groups = await get_all_groups()
    total_groups = len(groups)
    
    status = await message.reply_text(f"📤 Broadcasting to {total_groups} groups...")
    
    for group in groups:
        try:
            # Skip excluded chat
            if exclude_chat_id and group["chat_id"] == exclude_chat_id:
                continue
                
            sent_msg = None
            if text:
                # Send text message
                sent_msg = await app.send_message(
                    chat_id=group["chat_id"],
                    text=text
                )
            elif replied_msg:
                # Handle replied message
                if broadcast_type == "bcast":
                    sent_msg = await app.copy_message(
                        chat_id=group["chat_id"],
                        from_chat_id=replied_msg.chat.id,
                        message_id=replied_msg.id
                    )
                else:  # fcast
                    sent_msg = await app.forward_messages(
                        chat_id=group["chat_id"],
                        from_chat_id=replied_msg.chat.id,
                        message_ids=replied_msg.id
                    )
            
            # Pin message in group if requested (only works in groups, not DMs)
            if pin_message and sent_msg and group["chat_id"] < 0:  # Group IDs are negative
                try:
                    await app.pin_chat_message(
                        chat_id=group["chat_id"],
                        message_id=sent_msg.id
                    )
                except ChatAdminRequired:
                    logger.warning(f"Bot lacks permission to pin in group {group['chat_id']}")
                except Exception as e:
                    logger.error(f"Pin message failed in group {group['chat_id']}: {e}")
            
            success += 1
        except Exception as e:
            failed += 1
            logger.error(f"Failed to send to group {group['chat_id']}: {e}")
        
        total += 1
        if total % 10 == 0:
            await status.edit_text(f"👥 Group broadcast: {total}/{total_groups}")
    
    return total_groups, success, failed, status

# Broadcast command with inline options
@app.on_message(filters.command(["bcast", "fcast"]) & filters.user(OWNER_ID))
async def broadcast_menu(_, message: Message):
    # Create a unique ID for this broadcast session
    broadcast_id = generate_random_id()
    
    # Track group if in a group
    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        await track_group(
            message.chat.id,
            message.chat.title
        )
    
    # Extract message content
    text_content = None
    replied_msg = None
    
    if message.reply_to_message:
        replied_msg = message.reply_to_message
    elif message.text and len(message.command) > 1:
        # Remove command and join the rest
        text_content = " ".join(message.command[1:])
    
    # Save broadcast data temporarily
    await broadcast_collection.update_one(
        {"broadcast_id": broadcast_id},
        {"$set": {
            "command": message.command[0].lower(),
            "text": text_content,
            "replied_msg_id": replied_msg.id if replied_msg else None,
            "replied_chat_id": replied_msg.chat.id if replied_msg else None,
            "original_chat_id": message.chat.id,
            "original_msg_id": message.id,
            "timestamp": datetime.now()
        }},
        upsert=True
    )
    
    # Create inline keyboard with the requested options
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📍 Pin", callback_data=f"broadcast_option:{broadcast_id}:pin"),
            InlineKeyboardButton("👥 Group", callback_data=f"broadcast_option:{broadcast_id}:group")
        ],
        [
            InlineKeyboardButton("👤 User", callback_data=f"broadcast_option:{broadcast_id}:user")
        ],
        [
            InlineKeyboardButton("🚀 Send Now", callback_data=f"broadcast_confirm:{broadcast_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"broadcast_cancel:{broadcast_id}")
        ]
    ])
    
    text = "🔔 **Broadcast Options**\n\n"
    if text_content:
        text += f"Message: {text_content[:100]}{'...' if len(text_content) > 100 else ''}\n\n"
    elif replied_msg:
        text += "Message: Replied content\n\n"
    else:
        text += "⚠️ No message content provided\n\n"
    
    text += "Select options:"
    
    await message.reply_text(
        text,
        reply_markup=keyboard
    )

# Callback handler for broadcast options
@app.on_callback_query(filters.regex(r"^broadcast_option:(\w+):(\w+)$"))
async def broadcast_option_handler(_, query: CallbackQuery):
    await query.answer()
    data = query.data.split(":")
    broadcast_id = data[1]
    option = data[2]
    
    # Get current broadcast data
    broadcast_data = await broadcast_collection.find_one({"broadcast_id": broadcast_id})
    if not broadcast_data:
        await query.message.edit_text("❌ Broadcast session expired or invalid")
        return
    
    # Toggle option
    current_options = broadcast_data.get("options", [])
    if option in current_options:
        current_options.remove(option)
    else:
        current_options.append(option)
    
    # Update database
    await broadcast_collection.update_one(
        {"broadcast_id": broadcast_id},
        {"$set": {"options": current_options}}
    )
    
    # Update message text to show selected options
    text = "🔔 **Broadcast Options**\n\n"
    if broadcast_data.get("text"):
        text += f"Message: {broadcast_data['text'][:100]}{'...' if len(broadcast_data['text']) > 100 else ''}\n\n"
    elif broadcast_data.get("replied_msg_id"):
        text += "Message: Replied content\n\n"
    else:
        text += "⚠️ No message content provided\n\n"
    
    text += "**Selected Options:**\n"
    text += f"- 📍 Pin: {'✅' if 'pin' in current_options else '❌'}\n"
    text += f"- 👥 Group: {'✅' if 'group' in current_options else '❌'}\n"
    text += f"- 👤 User: {'✅' if 'user' in current_options else '❌'}\n\n"
    text += "Select options:"
    
    # Create updated keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📍 Pin", callback_data=f"broadcast_option:{broadcast_id}:pin"),
            InlineKeyboardButton("👥 Group", callback_data=f"broadcast_option:{broadcast_id}:group")
        ],
        [
            InlineKeyboardButton("👤 User", callback_data=f"broadcast_option:{broadcast_id}:user")
        ],
        [
            InlineKeyboardButton("🚀 Send Now", callback_data=f"broadcast_confirm:{broadcast_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"broadcast_cancel:{broadcast_id}")
        ]
    ])
    
    await query.message.edit_text(text, reply_markup=keyboard)

# Callback handler for broadcast confirmation
@app.on_callback_query(filters.regex(r"^broadcast_confirm:(\w+)$"))
async def broadcast_confirm_handler(_, query: CallbackQuery):
    await query.answer()
    broadcast_id = query.data.split(":")[1]
    
    # Get broadcast data
    broadcast_data = await broadcast_collection.find_one({"broadcast_id": broadcast_id})
    if not broadcast_data:
        await query.message.edit_text("❌ Broadcast session expired or invalid")
        return
    
    # Get selected options
    options = broadcast_data.get("options", [])
    command = broadcast_data["command"]
    chat_id = broadcast_data["original_chat_id"]
    
    # Send in current group if applicable
    current_msg = None
    replied_msg = None
    if broadcast_data.get("text") or broadcast_data.get("replied_msg_id"):
        try:
            if broadcast_data.get("text"):
                # Send text message
                current_msg = await app.send_message(
                    chat_id=chat_id,
                    text=broadcast_data["text"]
                )
            elif broadcast_data.get("replied_msg_id"):
                # Get the replied message object
                replied_msg = await app.get_messages(
                    broadcast_data["replied_chat_id"],
                    broadcast_data["replied_msg_id"]
                )
                
                # Send replied message
                if command == "bcast":
                    current_msg = await app.copy_message(
                        chat_id=chat_id,
                        from_chat_id=replied_msg.chat.id,
                        message_id=replied_msg.id
                    )
                else:  # fcast
                    current_msg = await app.forward_messages(
                        chat_id=chat_id,
                        from_chat_id=replied_msg.chat.id,
                        message_ids=replied_msg.id
                    )
        except Exception as e:
            logger.error(f"Current chat broadcast failed: {e}")
            await query.message.edit_text(f"❌ Failed to send in current chat: {e}")
    
    # Broadcast to groups if requested
    group_success = False
    group_stats = ""
    if "group" in options:
        try:
            if broadcast_data.get("text"):
                total_groups, success, failed, status = await broadcast_to_groups(
                    query.message, 
                    command,
                    text=broadcast_data["text"],
                    exclude_chat_id=chat_id,  # Exclude current chat
                    pin_message=("pin" in options)
                )
            else:
                total_groups, success, failed, status = await broadcast_to_groups(
                    query.message, 
                    command,
                    replied_msg=replied_msg,
                    exclude_chat_id=chat_id,  # Exclude current chat
                    pin_message=("pin" in options)
                )
                
            group_stats = (
                f"\n👥 **Group Broadcast Stats**\n"
                f"• Total groups: {total_groups}\n"
                f"• Successful: {success}\n"
                f"• Failed: {failed}"
            )
            group_success = True
        except Exception as e:
            logger.error(f"Group broadcast failed: {e}")
            group_stats = f"\n❌ Group broadcast failed: {e}"
    
    # Broadcast to users if requested
    user_success = False
    user_stats = ""
    if "user" in options:
        try:
            if broadcast_data.get("text"):
                total_users, success, failed, status = await broadcast_to_users(
                    query.message, 
                    command,
                    text=broadcast_data["text"]
                )
            else:
                total_users, success, failed, status = await broadcast_to_users(
                    query.message, 
                    command,
                    replied_msg=replied_msg
                )
                
            user_stats = (
                f"\n👤 **User Broadcast Stats**\n"
                f"• Total users: {total_users}\n"
                f"• Successful: {success}\n"
                f"• Failed: {failed}"
            )
            user_success = True
        except Exception as e:
            logger.error(f"User broadcast failed: {e}")
            user_stats = f"\n❌ User broadcast failed: {e}"
    
    # Create result message
    result_text = "✅ **Broadcast Completed**\n\n"
    if current_msg:
        result_text += f"📍 Current chat message: Sent\n"
    result_text += f"👥 Group broadcast: {'Sent' if group_success else 'Skipped'}\n"
    result_text += f"👤 User broadcast: {'Sent' if user_success else 'Skipped'}"
    result_text += group_stats
    result_text += user_stats
    
    # Add button to view in current chat if applicable
    keyboard = None
    if current_msg and chat_id:
        if str(chat_id).startswith("-100"):
            # Format group chat ID for URL
            chat_id_str = str(chat_id).replace('-100', '')
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔍 View in Group", 
                    url=f"https://t.me/c/{chat_id_str}/{current_msg.id}"
                )]
            ])
        else:
            # Private chat
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔍 View Message", 
                    url=f"https://t.me/c/{chat_id}/{current_msg.id}"
                )]
            ])
    
    await query.message.edit_text(result_text, reply_markup=keyboard)
    
    # Clean up temporary data
    await broadcast_collection.delete_one({"broadcast_id": broadcast_id})

# Callback handler for broadcast cancellation
@app.on_callback_query(filters.regex(r"^broadcast_cancel:(\w+)$"))
async def broadcast_cancel_handler(_, query: CallbackQuery):
    await query.answer("Broadcast cancelled")
    broadcast_id = query.data.split(":")[1]
    
    # Delete temporary data
    await broadcast_collection.delete_one({"broadcast_id": broadcast_id})
    await query.message.edit_text("❌ Broadcast cancelled")

# Stats command
@app.on_message(filters.command("stats"))
async def stats_command(_, message: Message):
    uptime = get_readable_time(int(time.time() - BOT_START_TIME))
    total_users = await users_collection.count_documents({})
    afk_users = await afk_collection.count_documents({})
    total_groups = await groups_collection.count_documents({})
    
    stats_text = (
        f"🤖 **Bot Statistics**\n"
        f"• Uptime: `{uptime}`\n"
        f"• Total Users: `{total_users}`\n"
        f"• AFK Users: `{afk_users}`\n"
        f"• Groups Added: `{total_groups}`"
    )
    
    await message.reply_text(stats_text)

# Main execution
async def main():
    # Create downloads directory if not exists
    os.makedirs("downloads", exist_ok=True)
    logger.info("Created downloads directory")
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info(f"Flask server started on port {PORT}")
    
    # Start the Telegram bot
    await app.start()
    logger.info("Telegram bot is now running...")
    
    # Keep the bot running
    await idle()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        loop.run_until_complete(app.stop())
        logger.info("Bot stopped")