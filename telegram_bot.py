#!/usr/bin/env python3
"""
Telegram Bot for Multi-Account Instagram Reel Uploader
Railway-ready with persistent volume support
"""
import os
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, ChallengeRequired, ClientError

# ============ CONFIG ============
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Railway Volume support: /app/data agar volume attached hai
DATA_DIR = "/app/data" if os.path.exists("/app/data") else "."
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
DOWNLOADS_DIR = os.path.join(DATA_DIR, "downloads")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")

# Create directories
for d in [SESSIONS_DIR, DOWNLOADS_DIR, COVERS_DIR]:
    os.makedirs(d, exist_ok=True)

# ============ LOGGING ============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ============ CONVERSATION STATES ============
(
    SELECT_MODE, ASK_USERNAME, ASK_PASSWORD, ASK_TOTP_SEED,
    RECEIVE_VIDEO, RECEIVE_COVER, RECEIVE_CAPTION, CONFIRM_UPLOAD
) = range(8)

# ============ ACCOUNT MANAGEMENT ============
def load_accounts():
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_accounts(accounts):
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)

def get_session_path(username):
    return os.path.join(SESSIONS_DIR, f"{username}.json")

def login_account(account):
    """Login with session or fresh login using TOTP seed"""
    client = Client()
    client.delay_range = [1, 3]
    client.request_timeout = 30
    
    session_file = get_session_path(account['username'])
    
    # Try session first (bina password)
    if os.path.exists(session_file):
        try:
            client.load_settings(session_file)
            client.get_timeline_feed()
            logger.info(f"Session valid: {account['username']}")
            return client, "session"
        except Exception:
            logger.warning(f"Session expired: {account['username']}")
            os.remove(session_file)
    
    # Fresh login with TOTP
    verification_code = None
    if account.get('totp_seed'):
        try:
            verification_code = client.totp_generate_code(account['totp_seed'])
            logger.info(f"Generated TOTP code for {account['username']}")
        except Exception as e:
            logger.error(f"TOTP generation failed: {e}")
    
    client.login(
        account['username'],
        account['password'],
        verification_code=verification_code
    )
    client.dump_settings(session_file)
    logger.info(f"Fresh login successful: {account['username']}")
    return client, "fresh"

# ============ TELEGRAM HANDLERS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Add New Account", callback_data="add_account")],
        [InlineKeyboardButton("📤 Upload Reel", callback_data="upload_reel")],
        [InlineKeyboardButton("📊 Account Status", callback_data="status")],
    ]
    await update.message.reply_text(
        "🤖 **Instagram Reel Uploader Bot**\n\n"
        "Kya karna hai?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELECT_MODE

async def mode_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    
    if action == "add_account":
        await query.edit_message_text(
            "📝 **Naya Account Add Karo**\n\n"
            "Username bhejo (bina @ ke):"
        )
        return ASK_USERNAME
    
    elif action == "upload_reel":
        accounts = load_accounts()
        if not accounts:
            await query.edit_message_text("❌ Koi account nahi hai. Pehle account add karo.")
            return ConversationHandler.END
        
        context.user_data['accounts'] = accounts
        await query.edit_message_text(
            f"✅ {len(accounts)} account(s) loaded.\n\n"
            "Ab **video** bhejo (MP4, 10MB tak):"
        )
        return RECEIVE_VIDEO
    
    elif action == "status":
        accounts = load_accounts()
        if not accounts:
            await query.edit_message_text("❌ Koi account nahi hai.")
            return ConversationHandler.END
        
        lines = []
        for acc in accounts:
            session_file = get_session_path(acc['username'])
            status = "✅ Logged In" if os.path.exists(session_file) else "❌ Not Logged In"
            lines.append(f"• `{acc['username']}`: {status}")
        
        await query.edit_message_text(
            "📊 **Account Status**\n\n" + "\n".join(lines),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    return SELECT_MODE

# ============ ADD ACCOUNT FLOW ============
async def ask_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_username'] = update.message.text.strip().replace('@', '')
    await update.message.reply_text("🔑 Ab **password** bhejo:")
    return ASK_PASSWORD

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_password'] = update.message.text.strip()
    # Delete password message for security
    try:
        await update.message.delete()
    except:
        pass
    await update.message.reply_text(
        "🔐 Ab **2FA Seed** bhejo:\n\n"
        "(Agar 2FA nahi hai to `none` likho)"
    )
    return ASK_TOTP_SEED

async def ask_totp_seed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seed_text = update.message.text.strip()
    seed = None if seed_text.lower() == 'none' else seed_text
    
    username = context.user_data['new_username']
    password = context.user_data['new_password']
    
    account = {
        "username": username,
        "password": password,
        "totp_seed": seed,
        "enabled": True
    }
    
    await update.message.reply_text(f"🔄 `{username}` login try ho raha hai...", parse_mode="Markdown")
    
    try:
        client, method = login_account(account)
        
        # Save account
        accounts = load_accounts()
        accounts = [a for a in accounts if a['username'] != username]
        accounts.append(account)
        save_accounts(accounts)
        
        await update.message.reply_text(
            f"✅ **Login Successful!**\n\n"
            f"Account: `{username}`\n"
            f"Method: {method}\n"
            f"Session saved.\n\n"
            f"Ab video upload kar sakte ho.",
            parse_mode="Markdown"
        )
    except ChallengeRequired as e:
        await update.message.reply_text(
            f"❌ **Challenge Required**\n\n"
            f"Instagram ne verification maanga hai.\n"
            f"Pehle browser/app se manually login karo, phir retry karo.\n\n"
            f"Error: {str(e)[:200]}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ **Login Failed**\n\n`{str(e)[:300]}`", parse_mode="Markdown")
    
    return ConversationHandler.END

# ============ VIDEO UPLOAD FLOW ============
async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video
    if not video:
        await update.message.reply_text("❌ Video bhejo (MP4 format).")
        return RECEIVE_VIDEO
    
    # 10MB check
    if video.file_size > 10 * 1024 * 1024:
        await update.message.reply_text(
            f"❌ Video 10MB se badi hai ({video.file_size / 1024 / 1024:.1f}MB).\n"
            f"Chhoti video bhejo."
        )
        return RECEIVE_VIDEO
    
    file = await video.get_file()
    video_path = os.path.join(DOWNLOADS_DIR, f"{update.effective_user.id}_{int(datetime.now().timestamp())}.mp4")
    await file.download_to_drive(video_path)
    
    context.user_data['video_path'] = video_path
    await update.message.reply_text("✅ Video saved!\n\nAb **cover image** bhejo (JPG):")
    return RECEIVE_COVER

async def receive_cover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        await update.message.reply_text("❌ Cover image bhejo (photo).")
        return RECEIVE_COVER
    
    file = await photo.get_file()
    cover_path = os.path.join(COVERS_DIR, f"{update.effective_user.id}_{int(datetime.now().timestamp())}.jpg")
    await file.download_to_drive(cover_path)
    
    context.user_data['cover_path'] = cover_path
    await update.message.reply_text("✅ Cover saved!\n\nAb **caption** bhejo:")
    return RECEIVE_CAPTION

async def receive_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.text.strip()
    if not caption:
        await update.message.reply_text("❌ Caption khali nahi ho sakta.")
        return RECEIVE_CAPTION
    
    context.user_data['caption'] = caption
    
    keyboard = [
        [InlineKeyboardButton("✅ Haan, Upload Karo", callback_data="confirm_upload")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_upload")],
    ]
    await update.message.reply_text(
        f"📋 **Confirm Upload**\n\n"
        f"Caption: {caption[:100]}{'...' if len(caption) > 100 else ''}\n\n"
        f"Upload karna hai?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CONFIRM_UPLOAD

async def confirm_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_upload":
        # Cleanup
        video_path = context.user_data.get('video_path')
        cover_path = context.user_data.get('cover_path')
        for p in [video_path, cover_path]:
            if p and os.path.exists(p):
                os.remove(p)
        await query.edit_message_text("❌ Upload cancelled.")
        return ConversationHandler.END
    
    # Start upload
    await query.edit_message_text("🔄 Upload shuru ho raha hai...")
    await start_upload(update, context)
    return ConversationHandler.END

async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accounts = context.user_data.get('accounts', [])
    video_path = context.user_data.get('video_path')
    cover_path = context.user_data.get('cover_path')
    caption = context.user_data.get('caption', '')
    
    if not accounts or not video_path:
        await update.message.reply_text("❌ Data missing. Dobara try karo.")
        return
    
    results = []
    total = len(accounts)
    success_count = 0
    
    for i, account in enumerate(accounts):
        username = account['username']
        try:
            await update.message.reply_text(
                f"🔄 [{i+1}/{total}] `{username}` pe upload ho raha hai...",
                parse_mode="Markdown"
            )
            
            client, method = login_account(account)
            media = client.clip_upload(
                Path(video_path),
                caption,
                thumbnail=Path(cover_path) if cover_path and os.path.exists(cover_path) else None
            )
            
            results.append(f"✅ `{username}`: Uploaded (ID: {media.pk})")
            success_count += 1
            logger.info(f"Uploaded to {username}: {media.pk}")
            
            # Small delay between accounts
            if i < total - 1:
                await asyncio.sleep(5)
                
        except Exception as e:
            results.append(f"❌ `{username}`: Failed - {str(e)[:100]}")
            logger.error(f"Upload failed for {username}: {e}")
    
    # Cleanup
    for p in [video_path, cover_path]:
        if p and os.path.exists(p):
            os.remove(p)
    
    # Final report
    report = (
        f"📊 **Upload Complete**\n\n"
        f"Total: {total} | ✅ Success: {success_count} | ❌ Failed: {total - success_count}\n\n"
        + "\n".join(results)
    )
    await update.message.reply_text(report, parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Cleanup files
    for key in ['video_path', 'cover_path']:
        p = context.user_data.get(key)
        if p and os.path.exists(p):
            os.remove(p)
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ============ MAIN ============
def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("TELEGRAM_BOT_TOKEN set nahi hai!")
        return
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_MODE: [CallbackQueryHandler(mode_selected)],
            ASK_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_username)],
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_password)],
            ASK_TOTP_SEED: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_totp_seed)],
            RECEIVE_VIDEO: [MessageHandler(filters.VIDEO, receive_video)],
            RECEIVE_COVER: [MessageHandler(filters.PHOTO, receive_cover)],
            RECEIVE_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_caption)],
            CONFIRM_UPLOAD: [CallbackQueryHandler(confirm_upload)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    
    app.add_handler(conv_handler)
    
    logger.info("Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
