#!/usr/bin/env python3
"""
Jatin Siingh Reel Uploader - Multi-Account Instagram Reel Bot
Created by: Jatin Siingh
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
BOT_TOKEN = "9118049489:AAHORiDWM_YAsQZuOeRD_CniM3LQXMPXrg0"

DATA_DIR = "/app/data" if os.path.exists("/app/data") else "."
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
DOWNLOADS_DIR = os.path.join(DATA_DIR, "downloads")
COVERS_DIR = os.path.join(DATA_DIR, "covers")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")

for d in [SESSIONS_DIR, DOWNLOADS_DIR, COVERS_DIR]:
    os.makedirs(d, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ============ CONVERSATION STATES ============
(
    SELECT_MODE, ASK_USERNAME, ASK_PASSWORD, ASK_COOKIE,
    RECEIVE_VIDEO, RECEIVE_COVER, RECEIVE_CAPTION, CONFIRM_UPLOAD,
    REMOVE_ACCOUNT_MENU
) = range(9)

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
    client = Client()
    client.delay_range = [1, 3]
    client.request_timeout = 30
    
    session_file = get_session_path(account['username'])
    
    if account.get('sessionid'):
        try:
            client.login_by_sessionid(account['sessionid'])
            client.dump_settings(session_file)
            return client, "cookie"
        except Exception as e:
            logger.warning(f"Cookie login failed: {e}")
    
    if os.path.exists(session_file):
        try:
            client.load_settings(session_file)
            client.get_timeline_feed()
            return client, "session_file"
        except Exception:
            os.remove(session_file)
    
    if account.get('password'):
        v_code = client.totp_generate_code(account['totp_seed']) if account.get('totp_seed') else None
        client.login(account['username'], account['password'], verification_code=v_code)
        client.dump_settings(session_file)
        return client, "password"
    
    raise Exception("Koi valid login method nahi mila.")

# ============ TELEGRAM HANDLERS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("➕ Add New Account", callback_data="add_account")],
        [InlineKeyboardButton("📤 Upload Reel", callback_data="upload_reel")],
        [InlineKeyboardButton("📊 Account Status", callback_data="status")],
        [InlineKeyboardButton("🗑 Remove Account", callback_data="remove_account")],
    ]
    await update.message.reply_text(
        "👑 **Jatin Siingh Reel Uploader** 👑\n\n"
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
        await query.edit_message_text("📝 **Naya Account Add Karo**\n\nUsername bhejo (bina @ ke):")
        return ASK_USERNAME
    
    elif action == "upload_reel":
        accounts = load_accounts()
        if not accounts:
            await query.edit_message_text("❌ Koi account nahi hai. Pehle account add karo.")
            return ConversationHandler.END
        
        context.user_data['accounts'] = accounts
        await query.edit_message_text(f"✅ {len(accounts)} account(s) loaded.\n\nAb **video** bhejo (MP4, 10MB tak):")
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
        
        await query.edit_message_text("📊 **Account Status**\n\n" + "\n".join(lines), parse_mode="Markdown")
        return ConversationHandler.END
    
    elif action == "remove_account":
        accounts = load_accounts()
        if not accounts:
            await query.edit_message_text("❌ Koi account nahi hai.")
            return ConversationHandler.END
        
        keyboard = []
        for acc in accounts:
            keyboard.append([InlineKeyboardButton(f"❌ Remove {acc['username']}", callback_data=f"rm_{acc['username']}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")])
        
        await query.edit_message_text("🗑 **Kis account ko remove karna hai?**", reply_markup=InlineKeyboardMarkup(keyboard))
        return REMOVE_ACCOUNT_MENU
    
    return SELECT_MODE

async def remove_account_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_to_menu":
        await start(update, context)
        return SELECT_MODE
    
    username = query.data.replace("rm_", "")
    accounts = load_accounts()
    accounts = [a for a in accounts if a['username'] != username]
    save_accounts(accounts)
    
    # Delete session file
    session_file = get_session_path(username)
    if os.path.exists(session_file):
        os.remove(session_file)
    
    await query.edit_message_text(f"✅ `{username}` ka account aur session remove ho gaya!", parse_mode="Markdown")
    return ConversationHandler.END

# ============ ADD ACCOUNT FLOW ============
async def ask_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_username'] = update.message.text.strip().replace('@', '')
    await update.message.reply_text("🔑 Ab **password** bhejo (Agar sirf cookie use karna hai to `none` likho):")
    return ASK_PASSWORD

async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data['new_password'] = None if text.lower() == 'none' else text
    await update.message.reply_text("🍪 Ab **Instagram SessionID (Cookie)** bhejo:\n\n(Agar password use kar rahe ho to `none` likho)")
    return ASK_COOKIE

async def ask_cookie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    sessionid = None if text.lower() == 'none' else text
    
    username = context.user_data.get('new_username')
    password = context.user_data.get('new_password')
    
    if not username or (not password and not sessionid):
        await update.message.reply_text("❌ Data missing. /start karke dobara try karo.")
        return ConversationHandler.END
    
    account = {"username": username, "password": password, "sessionid": sessionid, "totp_seed": None, "enabled": True}
    
    await update.message.reply_text(f"🔄 `{username}` login try ho raha hai...", parse_mode="Markdown")
    
    try:
        client, method = login_account(account)
        accounts = load_accounts()
        accounts = [a for a in accounts if a['username'] != username]
        accounts.append(account)
        save_accounts(accounts)
        
        await update.message.reply_text(f"✅ **Login Successful!**\n\nAccount: `{username}`\nMethod: {method}\nSession saved.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ **Login Failed**\n\n`{str(e)[:300]}`", parse_mode="Markdown")
    
    return ConversationHandler.END

# ============ VIDEO UPLOAD FLOW ============
async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video
    if not video:
        await update.message.reply_text("❌ Video bhejo (MP4 format).")
        return RECEIVE_VIDEO
    
    if video.file_size > 10 * 1024 * 1024:
        await update.message.reply_text(f"❌ Video 10MB se badi hai.")
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
    # Japanese text / formatting issues fix
    caption = update.message.text if update.message.text else update.message.caption
    if not caption:
        await update.message.reply_text("❌ Caption nahi mila, dobara bhejo.")
        return RECEIVE_CAPTION
    
    context.user_data['caption'] = caption
    
    keyboard = [
        [InlineKeyboardButton("✅ Haan, Upload Karo", callback_data="confirm_upload")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_upload")],
    ]
    # Yahan caption dikhate waqt Markdown use nahi kiya taaki Japanese text break na ho
    await update.message.reply_text(
        f"📋 **Confirm Upload**\n\nCaption: {caption[:100]}...\n\nUpload karna hai?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CONFIRM_UPLOAD

async def confirm_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_upload":
        for key in ['video_path', 'cover_path']:
            p = context.user_data.get(key)
            if p and os.path.exists(p): os.remove(p)
        await query.edit_message_text("❌ Upload cancelled.")
        return ConversationHandler.END
    
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
            await update.message.reply_text(f"🔄 [{i+1}/{total}] `{username}` pe upload ho raha hai...", parse_mode="Markdown")
            
            client, method = login_account(account)
            
            try:
                media = client.clip_upload(
                    Path(video_path),
                    caption,
                    thumbnail=Path(cover_path) if cover_path and os.path.exists(cover_path) else None
                )
            except Exception as upload_err:
                if "login_required" in str(upload_err).lower() and account.get('password'):
                    logger.warning("Cookie upload fail, password fallback...")
                    client = Client()
                    v_code = client.totp_generate_code(account['totp_seed']) if account.get('totp_seed') else None
                    client.login(account['username'], account['password'], verification_code=v_code)
                    client.dump_settings(get_session_path(username))
                    media = client.clip_upload(Path(video_path), caption, thumbnail=Path(cover_path) if cover_path and os.path.exists(cover_path) else None)
                else:
                    raise upload_err
            
            results.append(f"✅ `{username}`: Uploaded (ID: {media.pk})")
            success_count += 1
            if i < total - 1: await asyncio.sleep(5)
                
        except Exception as e:
            results.append(f"❌ `{username}`: Failed - {str(e)[:100]}")
            logger.error(f"Upload failed for {username}: {e}")
    
    for p in [video_path, cover_path]:
        if p and os.path.exists(p): os.remove(p)
    
    report = (
        f"📊 **Upload Complete**\n\n"
        f"Total: {total} | ✅ Success: {success_count} | ❌ Failed: {total - success_count}\n\n"
        + "\n".join(results)
    )
    await update.message.reply_text(report, parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for key in ['video_path', 'cover_path']:
        p = context.user_data.get(key)
        if p and os.path.exists(p): os.remove(p)
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
            ASK_COOKIE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_cookie)],
            RECEIVE_VIDEO: [MessageHandler(filters.VIDEO, receive_video)],
            RECEIVE_COVER: [MessageHandler(filters.PHOTO, receive_cover)],
            RECEIVE_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_caption)],
            CONFIRM_UPLOAD: [CallbackQueryHandler(confirm_upload)],
            REMOVE_ACCOUNT_MENU: [CallbackQueryHandler(remove_account_selected)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    
    app.add_handler(conv_handler)
    logger.info("Jatin Siingh Reel Uploader Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
