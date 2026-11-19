import asyncio
# Python 3.14+ Event Loop Fix (Pyrogram import se pehle set karna zaroori hai)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

import os
import re
import time
import json
import threading
import urllib.request
from flask import Flask
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import (
    FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
    PasswordHashInvalid
)
from pyrogram.raw import functions

# ===================== CONFIGURATION =====================
BOT_PASSWORD = os.environ.get("BOT_PASSWORD", "Boss@2011123")
API_ID = int(os.environ.get("API_ID", "3167980"))
API_HASH = os.environ.get("API_HASH", "7b7838599c637648e6d164054208d2eb")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YAHAN_APNA_BOT_TOKEN_DALO")
MASTER_SESSION = os.environ.get("MASTER_SESSION", "YAHAN_APNA_MASTER_STRING_SESSION_DALO")
# =========================================================

# Render 24/7 Keep-Alive Web Server
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Media Transfer Bot is Active 24/7!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port, use_reloader=False)

# Old Webhook Auto-Cleaner (taaki /start kabhi na atke)
def clear_old_webhook(token):
    if not token or "YAHAN_" in token:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=true"
        urllib.request.urlopen(url, timeout=10).read()
        print("✅ Old Telegram Webhook Cleared!")
    except Exception as e:
        print(f"⚠️ Webhook clear notice: {e}")

bot = Client(
    "PersonalMediaBot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=32,
    max_concurrent_transmissions=8
)

master_user = None
if MASTER_SESSION and "YAHAN_" not in MASTER_SESSION and len(MASTER_SESSION) > 20:
    master_user = Client(
        "MasterReader",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=MASTER_SESSION,
        workers=32,
        max_concurrent_transmissions=8
    )

DB_FILE = "bot_config.json"
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

user_states = {}
active_tasks = {}

# ===================== DATABASE & AUTH HELPERS =====================
def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "authorized_users" not in data:
                    data["authorized_users"] = []
                if "users" not in data:
                    data["users"] = {}
                return data
        except Exception:
            pass
    return {"authorized_users": [], "users": {}}

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def is_authorized(uid: int) -> bool:
    db = load_db()
    return uid in db.get("authorized_users", [])

def authorize_user(uid: int):
    db = load_db()
    if uid not in db["authorized_users"]:
        db["authorized_users"].append(uid)
        save_db(db)

def get_user_cfg(uid: int) -> dict:
    db = load_db()
    suid = str(uid)
    if suid not in db["users"]:
        db["users"][suid] = {"target_chat": None, "session_string": None, "mode": None}
        save_db(db)
    return db["users"][suid]

def set_user_cfg(uid: int, key: str, value):
    db = load_db()
    suid = str(uid)
    if suid not in db["users"]:
        db["users"][suid] = {"target_chat": None, "session_string": None, "mode": None}
    db["users"][suid][key] = value
    save_db(db)

def reset_user_cfg(uid: int):
    db = load_db()
    suid = str(uid)
    db["users"][suid] = {"target_chat": None, "session_string": None, "mode": None}
    save_db(db)

# ===================== FORMATTING & UI HELPERS =====================
def main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Public", callback_data="mode_public"),
            InlineKeyboardButton("🔒 Private", callback_data="mode_private")
        ]
    ])

def dest_choice_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Channel / Group Jode", callback_data="dest_channel"),
            InlineKeyboardButton("📥 Yahi Bheje", callback_data="dest_here")
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
    ])

def private_type_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Sidha Channel / Group Link Dalo", callback_data="priv_full")],
        [InlineKeyboardButton("1️⃣ Pahla Link Dalo (Starting Post)", callback_data="priv_first")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_home")]
    ])

def format_size(size):
    if not size:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size >= 1024 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.2f} {units[i]}"

def format_time(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def make_bar(pct):
    pct = max(0, min(100, int(pct)))
    filled = pct // 10
    return f"[{'▓' * filled}{'░' * (10 - filled)}] {pct}%"

def parse_tg_link(link):
    link = link.strip().split("?")[0].rstrip("/")
    # Private links: https://t.me/c/1234567890/15 or https://t.me/c/1234567890/5/15
    m_priv = re.match(r"https?://t\.me/c/(\d+)(?:/(\d+))?(?:/(\d+))?", link)
    if m_priv:
        chat_id = int("-100" + m_priv.group(1))
        if m_priv.group(3):
            return chat_id, int(m_priv.group(3)), int(m_priv.group(2))
        elif m_priv.group(2):
            return chat_id, int(m_priv.group(2)), None
        return chat_id, 1, None

    # Public links: https://t.me/username or https://t.me/username/15 or https://t.me/username/5/15
    m_pub = re.match(r"https?://t\.me/([a-zA-Z0-9_]+)(?:/(\d+))?(?:/(\d+))?", link)
    if m_pub and m_pub.group(1) not in ["joinchat", "s", "addstickers", "boost"]:
        username = m_pub.group(1)
        if m_pub.group(3):
            return username, int(m_pub.group(3)), int(m_pub.group(2))
        elif m_pub.group(2):
            return username, int(m_pub.group(2)), None
        return username, 1, None

    # Raw ID (-100xxxx) or Invite Link
    if link.startswith("-100") or link.lstrip("-").isdigit():
        return int(link), 1, None
    return link, 1, None

async def get_topic_title(client, peer_id, topic_id):
    try:
        peer = await client.resolve_peer(peer_id)
        res = await client.invoke(
            functions.channels.GetForumTopicsByID(channel=peer, topics=[topic_id])
        )
        if res and res.topics:
            return res.topics[0].title
    except Exception:
        pass
    return f"Topic_{topic_id}"

# ===================== HIGH-SPEED LIVE TRANSFER ENGINE =====================
async def run_transfer(
    status_msg: Message,
    uid: int,
    reader_client: Client,
    source_chat,
    start_id: int,
    dest_chat: int,
    topic_mode: bool = False,
    source_topic_id: int = None,
    need_stop_reader: bool = False
):
    active_tasks[uid] = True
    downloaded_count = 0
    uploaded_count = 0
    skipped_count = 0
    total_bytes_transferred = 0
    start_time = time.time()
    dest_topic_id = None

    live_state = {
        "phase": "Scanning...",
        "file_pct": 0,
        "speed": "0 KB/s",
        "file_curr": 0,
        "file_total": 0,
        "last_edit": 0.0
    }

    try:
        chat_obj = await reader_client.get_chat(source_chat)
        source_id = chat_obj.id
        source_title = chat_obj.title or str(source_id)

        # Forum Topic Auto-Clone
        if topic_mode:
            if not source_topic_id:
                await status_msg.edit_text("❌ **Is link mein Topic ID nahi mili!** Topic ke andar ke post ka link dalein.")
                return
            topic_name = await get_topic_title(reader_client, source_id, source_topic_id)
            try:
                created = await bot.create_forum_topic(chat_id=dest_chat, title=topic_name)
                dest_topic_id = created.id
            except Exception as e:
                await status_msg.edit_text(
                    f"❌ **Destination Group mein Topic nahi ban paya!**\n"
                    f"1. Destination group mein **Topics ON** rakhein.\n"
                    f"2. Bot ko admin banakar **Manage Topics** permission dein.\n\n"
                    f"Error: `{e}`"
                )
                return

        # Find latest post ID
        last_id = 0
        async for m in reader_client.get_chat_history(source_id, limit=1):
            last_id = m.id
            break

        if last_id == 0 or start_id > last_id:
            await status_msg.edit_text("⚠️ Is link ke baad koi post nahi mili.")
            return

        total_range = (last_id - start_id) + 1
        processed = 0

        async def update_live_dashboard(force=False):
            now = time.time()
            if not force and (now - live_state["last_edit"]) < 2.5:
                return
            live_state["last_edit"] = now

            elapsed = max(1.0, now - start_time)
            overall_pct = (processed / total_range) * 100
            posts_per_sec = processed / elapsed
            remaining_posts = max(0, total_range - processed)
            eta_sec = (remaining_posts / posts_per_sec) if posts_per_sec > 0 else 0

            text = (
                f"⚡ **LIVE HIGH-SPEED MEDIA TRANSFER**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📂 **Source:** `{source_title}`\n"
                f"📊 **Overall:** `{make_bar(overall_pct)}`\n"
                f"🔢 **Posts Scanned:** `{processed:,} / {total_range:,}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 **Status:** `{live_state['phase']}`\n"
                f"📶 **File Progress:** `{make_bar(live_state['file_pct'])}` (`{format_size(live_state['file_curr'])} / {format_size(live_state['file_total'])}`)\n"
                f"🚀 **Live Net Speed:** `{live_state['speed']}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📥 **Downloaded:** `{downloaded_count:,}` | 📤 **Uploaded:** `{uploaded_count:,}`\n"
                f"⏭️ **Skipped:** `{skipped_count:,}` | 📦 **Data:** `{format_size(total_bytes_transferred)}`\n"
                f"⏱️ **Elapsed:** `{format_time(elapsed)}` | ⏳ **ETA:** `{format_time(eta_sec)}`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )
            try:
                await status_msg.edit_text(text)
            except FloodWait as fw:
                live_state["last_edit"] = time.time() + fw.value
            except Exception:
                pass

        def make_progress_cb(phase_label, t0):
            def progress_cb(current, total):
                now = time.time()
                dt = max(0.05, now - t0)
                speed_bps = current / dt
                live_state["phase"] = phase_label
                live_state["file_curr"] = current
                live_state["file_total"] = total
                live_state["file_pct"] = int((current / total) * 100) if total else 0
                live_state["speed"] = f"{format_size(speed_bps)}/s"
            return progress_cb

        await update_live_dashboard(force=True)

        # 200-200 messages batch loop (supports 5,000 to 100,000+ posts fast)
        for batch_start in range(start_id, last_id + 1, 200):
            if not active_tasks.get(uid):
                await status_msg.edit_text("🛑 **Transfer Rok Diya Gaya (/reset).**")
                return

            batch_ids = list(range(batch_start, min(batch_start + 200, last_id + 1)))
            while True:
                try:
                    messages = await reader_client.get_messages(source_id, batch_ids)
                    break
                except FloodWait as fw:
                    live_state["phase"] = f"Telegram Wait ({fw.value}s)..."
                    await update_live_dashboard(force=True)
                    await asyncio.sleep(fw.value + 1)

            if not isinstance(messages, list):
                messages = [messages]

            for msg in messages:
                if not active_tasks.get(uid):
                    await status_msg.edit_text("🛑 **Transfer Rok Diya Gaya (/reset).**")
                    return

                processed += 1

                if not msg or msg.empty or msg.service:
                    skipped_count += 1
                    await update_live_dashboard()
                    continue

                if topic_mode:
                    msg_thread = getattr(msg, "message_thread_id", None)
                    if msg_thread != source_topic_id and msg.id != source_topic_id:
                        skipped_count += 1
                        await update_live_dashboard()
                        continue

                has_media = any([
                    msg.photo, msg.video, msg.document, msg.audio,
                    msg.voice, msg.animation, msg.video_note
                ])

                if not has_media:
                    skipped_count += 1
                    await update_live_dashboard()
                    continue

                file_path = None
                try:
                    # 1. Fast Download with live speed & progress
                    dl_start = time.time()
                    live_state["phase"] = "Downloading..."
                    live_state["file_pct"] = 0
                    await update_live_dashboard()

                    while True:
                        try:
                            file_path = await reader_client.download_media(
                                msg,
                                file_name=f"{DOWNLOAD_DIR}/{uid}_",
                                progress=make_progress_cb("Downloading...", dl_start)
                            )
                            break
                        except FloodWait as fw:
                            live_state["phase"] = f"FloodWait ({fw.value}s)..."
                            await update_live_dashboard(force=True)
                            await asyncio.sleep(fw.value + 1)

                    if not file_path or not os.path.exists(file_path):
                        skipped_count += 1
                        continue

                    fsize = os.path.getsize(file_path)
                    downloaded_count += 1
                    total_bytes_transferred += fsize

                    # 2. Fast Upload with live speed & progress
                    ul_start = time.time()
                    live_state["phase"] = "Uploading..."
                    live_state["file_pct"] = 0
                    await update_live_dashboard()

                    caption = msg.caption.html if msg.caption else ""
                    send_kwargs = {
                        "chat_id": dest_chat,
                        "caption": caption,
                        "parse_mode": enums.ParseMode.HTML,
                        "progress": make_progress_cb("Uploading...", ul_start)
                    }
                    if dest_topic_id:
                        send_kwargs["message_thread_id"] = dest_topic_id

                    while True:
                        try:
                            if msg.photo:
                                await bot.send_photo(photo=file_path, **send_kwargs)
                            elif msg.video:
                                await bot.send_video(
                                    video=file_path,
                                    duration=msg.video.duration or 0,
                                    width=msg.video.width or 0,
                                    height=msg.video.height or 0,
                                    supports_streaming=True,
                                    **send_kwargs
                                )
                            elif msg.audio:
                                await bot.send_audio(audio=file_path, **send_kwargs)
                            elif msg.voice:
                                await bot.send_voice(voice=file_path, **send_kwargs)
                            elif msg.animation:
                                await bot.send_animation(animation=file_path, **send_kwargs)
                            else:
                                await bot.send_document(document=file_path, **send_kwargs)
                            break
                        except FloodWait as fw:
                            live_state["phase"] = f"Upload Wait ({fw.value}s)..."
                            await update_live_dashboard(force=True)
                            await asyncio.sleep(fw.value + 1)

                    uploaded_count += 1
                    await update_live_dashboard()
                    await asyncio.sleep(0.35)  # High-speed safe interval

                except Exception:
                    skipped_count += 1
                finally:
                    # Immediate storage cleanup
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception:
                            pass

        total_time = format_time(time.time() - start_time)
        await status_msg.edit_text(
            f"🎉 **TRANSFER 100% COMPLETE!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📂 **Source:** `{source_title}`\n"
            f"📊 **Progress:** `[▓▓▓▓▓▓▓▓▓▓] 100%`\n"
            f"📥 **Downloaded:** `{downloaded_count:,}`\n"
            f"📤 **Uploaded:** `{uploaded_count:,}`\n"
            f"⏭️ **Skipped:** `{skipped_count:,}`\n"
            f"📦 **Total Data:** `{format_size(total_bytes_transferred)}`\n"
            f"⏱️ **Total Time:** `{total_time}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ **Error Aaya:** `{e}`")
    finally:
        active_tasks.pop(uid, None)
        if need_stop_reader and reader_client:
            try:
                await reader_client.stop()
            except Exception:
                pass

# ===================== HOME MENU HELPER =====================
async def send_home_menu(message: Message, uid: int, prefix_text: str = ""):
    user_states.pop(uid, None)
    cfg = get_user_cfg(uid)
    saved_ch = f"`{cfg['target_chat']}`" if cfg.get("target_chat") else "❌ Set Nahi Hai"
    login_st = "✅ Logged In" if cfg.get("session_string") else "❌ Not Logged In"

    text = (
        f"{prefix_text}"
        f"👋 **Media Transfer Bot Ready!**\n\n"
        f"📌 **Saved Channel/Group:** {saved_ch}\n"
        f"🔐 **Private Account:** {login_st}\n\n"
        f"**Commands:**\n"
        f"• `/id` — Channel / Group / Topic ID nikalein\n"
        f"• `/setchannel` — Permanent Channel / Group set karein\n"
        f"• `/grouptransfer` — Group se direct transfer karein\n"
        f"• `/grouptopictransfer` — Topic Group clone + transfer karein\n"
        f"• `/reset` — Saari settings & login reset karein\n\n"
        f"👇 **Neeche se Mode chunein:**"
    )
    await message.reply_text(text, reply_markup=main_menu_kb())

# ===================== COMMANDS =====================
@bot.on_message(filters.command("id"))
async def cmd_id(client, message: Message):
    # Group/Channel mein direct ID dega; Private mein password check karega
    if message.chat.type == enums.ChatType.PRIVATE:
        uid = message.from_user.id
        if not is_authorized(uid):
            user_states[uid] = {"step": "awaiting_password"}
            await message.reply_text("🔐 **Bot Locked Hai!**\nAccess ke liye **Password** dalein:")
            return

    chat = message.chat
    thread_id = getattr(message, "message_thread_id", None)
    text = (
        f"🆔 **Chat Details:**\n"
        f"• **Name:** `{chat.title or chat.first_name}`\n"
        f"• **Type:** `{chat.type.name}`\n"
        f"• **Chat ID:** `{chat.id}`"
    )
    if thread_id:
        text += f"\n• **Topic Thread ID:** `{thread_id}`"
    await message.reply_text(text)

@bot.on_message(filters.command("start") & filters.private)
async def cmd_start(client, message: Message):
    uid = message.from_user.id
    if not is_authorized(uid):
        user_states[uid] = {"step": "awaiting_password"}
        await message.reply_text(
            "🔐 **Bot Password Protected Hai!**\n\n"
            "Kripya aage badhne ke liye **Password** dalein:"
        )
        return
    await send_home_menu(message, uid)

@bot.on_message(filters.command("setchannel") & filters.private)
async def cmd_setchannel(client, message: Message):
    uid = message.from_user.id
    if not is_authorized(uid):
        user_states[uid] = {"step": "awaiting_password"}
        await message.reply_text("🔐 Pehle **Password** dalein:")
        return
    user_states[uid] = {"step": "awaiting_setchannel"}
    await message.reply_text(
        "📌 **Apne Channel ya Group ka ID bhejein** (`-100xxxx`):\n\n"
        "*(Pehle bot ko us channel/group mein **Admin** banayein aur wahan `/id` likh kar ID nikal lein)*"
    )

@bot.on_message(filters.command("grouptransfer") & filters.private)
async def cmd_grouptransfer(client, message: Message):
    uid = message.from_user.id
    if not is_authorized(uid):
        user_states[uid] = {"step": "awaiting_password"}
        await message.reply_text("🔐 Pehle **Password** dalein:")
        return
    cfg = get_user_cfg(uid)
    if cfg.get("target_chat"):
        user_states[uid] = {"step": "awaiting_grouptransfer_link", "dest": cfg["target_chat"]}
        await message.reply_text(
            f"✅ **Saved Destination:** `{cfg['target_chat']}`\n\n"
            f"🔗 Ab **Group ka Link** dalein jahan se media nikalna hai:"
        )
    else:
        user_states[uid] = {"step": "grouptransfer_choose_dest"}
        await message.reply_text(
            "⚠️ Abhi koi channel/group set nahi hai (`/setchannel`).\n"
            "Kahan transfer karna chahte hain?",
            reply_markup=dest_choice_kb()
        )

@bot.on_message(filters.command("grouptopictransfer") & filters.private)
async def cmd_grouptopictransfer(client, message: Message):
    uid = message.from_user.id
    if not is_authorized(uid):
        user_states[uid] = {"step": "awaiting_password"}
        await message.reply_text("🔐 Pehle **Password** dalein:")
        return
    cfg = get_user_cfg(uid)
    if not cfg.get("target_chat"):
        await message.reply_text(
            "⚠️ Pehle `/setchannel` se apna **Destination Topic Group** set karein!\n"
            "*(Us group mein **Topics ON** rakhein aur bot ko **Manage Topics** admin permission dein)*"
        )
        return
    user_states[uid] = {"step": "awaiting_topic_link", "dest": cfg["target_chat"]}
    await message.reply_text(
        f"🗂️ **Group Topic Transfer Mode**\n"
        f"📌 **Destination Group:** `{cfg['target_chat']}`\n\n"
        f"🔗 Ab source Topic Group ke **kisi bhi ek file/post ka link** dalein.\n"
        f"Bot wahi **exact Topic** aapke group mein banakar poora material upload kar dega!"
    )

@bot.on_message(filters.command("reset") & filters.private)
async def cmd_reset(client, message: Message):
    uid = message.from_user.id
    if not is_authorized(uid):
        user_states[uid] = {"step": "awaiting_password"}
        await message.reply_text("🔐 Pehle **Password** dalein:")
        return
    active_tasks.pop(uid, None)
    user_states.pop(uid, None)
    reset_user_cfg(uid)
    await message.reply_text(
        "♻️ **Bot Poori Tarah Reset & Refresh Ho Gaya Hai!**\n"
        "• Saved Channel/Group hata diya gaya hai.\n"
        "• Telegram Login session clear kar diya gaya hai.\n"
        "• Chal rahe tasks rok diye gaye hain.",
        reply_markup=main_menu_kb()
    )

# ===================== CALLBACK BUTTONS =====================
@bot.on_callback_query()
async def handle_callbacks(client, cb):
    uid = cb.from_user.id
    if not is_authorized(uid):
        await cb.answer("🔐 Pehle /start karke Password dalein!", show_alert=True)
        return

    cfg = get_user_cfg(uid)
    q = cb.data

    if q == "back_home":
        user_states.pop(uid, None)
        await cb.message.edit_text("👇 **Mode chunein:**", reply_markup=main_menu_kb())

    elif q in ["mode_public", "mode_private"]:
        mode = "public" if q == "mode_public" else "private"
        set_user_cfg(uid, "mode", mode)

        if cfg.get("target_chat"):
            dest = cfg["target_chat"]
            if mode == "public":
                user_states[uid] = {"step": "awaiting_public_link", "dest": dest}
                await cb.message.edit_text(
                    f"📢 **Public Mode** | 🎯 Destination: `{dest}`\n\n"
                    f"🔗 Ab **Public Channel ya Group ka Link** dalein:"
                )
            else:
                await proceed_private_flow(cb.message, uid, dest)
        else:
            user_states[uid] = {"step": "choosing_dest", "mode": mode}
            await cb.message.edit_text(
                f"{'📢 Public' if mode == 'public' else '🔒 Private'} Mode Chuna Gaya.\n\n"
                f"Media kahan bhejna hai?",
                reply_markup=dest_choice_kb()
            )

    elif q in ["dest_channel", "dest_here"]:
        st = user_states.get(uid, {})
        mode = st.get("mode") or cfg.get("mode") or "public"
        is_grouptransfer = st.get("step") == "grouptransfer_choose_dest"

        if q == "dest_channel":
            user_states[uid] = {
                "step": "awaiting_inline_channel_id",
                "mode": mode,
                "is_grouptransfer": is_grouptransfer
            }
            await cb.message.edit_text(
                "➕ **Apne Channel ya Group ka ID bhejein** (`-100xxxx`):\n"
                "*(Bot ko usme admin banakar `/id` likhein aur ID yahan bhejein)*"
            )
        else:
            dest = uid
            if is_grouptransfer:
                user_states[uid] = {"step": "awaiting_grouptransfer_link", "dest": dest}
                await cb.message.edit_text("🔗 Ab **Group ka Link** dalein:")
            elif mode == "public":
                user_states[uid] = {"step": "awaiting_public_link", "dest": dest}
                await cb.message.edit_text("🔗 Ab **Public Channel ya Group ka Link** dalein:")
            else:
                await proceed_private_flow(cb.message, uid, dest)

    elif q in ["priv_full", "priv_first"]:
        st = user_states.get(uid, {})
        dest = st.get("dest") or cfg.get("target_chat") or uid
        if q == "priv_full":
            user_states[uid] = {"step": "awaiting_priv_full_link", "dest": dest}
            await cb.message.edit_text(
                "🔗 **Sidha Channel ya Group ka Link / ID dalein:**\n"
                "*(Shuru se end tak poora media download hokar upload hoga)*"
            )
        else:
            user_states[uid] = {"step": "awaiting_priv_first_link", "dest": dest}
            await cb.message.edit_text(
                "1️⃣ **Pahla Link Dalo (Channel ya Group ke pehle post ka link):**\n"
                "Jaise: `https://t.me/c/123456789/10`\n"
                "*(Is post se lekar aakhiri post tak poora media nikal jayega)*"
            )

async def proceed_private_flow(msg_obj: Message, uid: int, dest: int):
    cfg = get_user_cfg(uid)
    if cfg.get("session_string"):
        user_states[uid] = {"step": "priv_menu", "dest": dest}
        await msg_obj.edit_text(
            f"🔒 **Private Mode Ready** | 🎯 Destination: `{dest}`\n\n"
            f"👇 Neeche se option chunein:",
            reply_markup=private_type_kb()
        )
    else:
        user_states[uid] = {"step": "login_phone", "dest": dest}
        await msg_obj.edit_text(
            "🔐 **Telegram Login Zaroori Hai (Private Channel/Group ke liye)**\n\n"
            "📱 Apna **Phone Number** country code ke saath bhejein:\n"
            "Example: `+919876543210`"
        )

# ===================== TEXT & INPUT HANDLER =====================
@bot.on_message(filters.private & filters.text & ~filters.command(["start", "id", "setchannel", "grouptransfer", "grouptopictransfer", "reset"]))
async def handle_inputs(client, message: Message):
    uid = message.from_user.id
    text = message.text.strip()

    # Password Check Gate
    if not is_authorized(uid):
        if text == BOT_PASSWORD:
            authorize_user(uid)
            # Security ke liye password message delete karne ki koshish
            try:
                await message.delete()
            except Exception:
                pass
            await send_home_menu(message, uid, prefix_text="✅ **Password Verified! Ab baar-baar password nahi dalna padega.**\n\n")
        else:
            user_states[uid] = {"step": "awaiting_password"}
            await message.reply_text("❌ **Galat Password!** Sahi password dalein:")
        return

    st = user_states.get(uid)
    if not st:
        return

    step = st.get("step")

    # 1. /setchannel ID Save
    if step == "awaiting_setchannel":
        try:
            chat_id = int(text)
            chat = await bot.get_chat(chat_id)
            set_user_cfg(uid, "target_chat", chat.id)
            user_states.pop(uid, None)
            await message.reply_text(
                f"✅ **Channel/Group Set Ho Gaya!**\n"
                f"• **Naam:** `{chat.title}`\n"
                f"• **ID:** `{chat.id}`\n\n"
                f"Ab jab tak `/reset` nahi karoge, saara media sidha isi mein jayega!",
                reply_markup=main_menu_kb()
            )
        except Exception as e:
            await message.reply_text(f"❌ Invalid ID ya Bot isme Admin nahi hai.\nError: `{e}`")

    # 2. Inline Channel Jode
    elif step == "awaiting_inline_channel_id":
        try:
            chat_id = int(text)
            chat = await bot.get_chat(chat_id)
            set_user_cfg(uid, "target_chat", chat.id)
            mode = st.get("mode", "public")
            if st.get("is_grouptransfer"):
                user_states[uid] = {"step": "awaiting_grouptransfer_link", "dest": chat.id}
                await message.reply_text(f"✅ Set: `{chat.title}`\n\n🔗 Ab **Group ka Link** dalein:")
            elif mode == "public":
                user_states[uid] = {"step": "awaiting_public_link", "dest": chat.id}
                await message.reply_text(f"✅ Set: `{chat.title}`\n\n🔗 Ab **Public Channel/Group ka Link** dalein:")
            else:
                m = await message.reply_text(f"✅ Set: `{chat.title}`")
                await proceed_private_flow(m, uid, chat.id)
        except Exception as e:
            await message.reply_text(f"❌ Bot ko pehle us channel/group mein admin banayein.\nError: `{e}`")

    # 3. Telegram Login Steps (Phone -> OTP -> 2FA)
    elif step == "login_phone":
        phone = text.replace(" ", "")
        status = await message.reply_text("⏳ OTP bheja ja raha hai...")
        temp_client = Client(f"temp_login_{uid}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await temp_client.connect()
        try:
            sent_code = await temp_client.send_code(phone)
            user_states[uid] = {
                "step": "login_otp",
                "dest": st["dest"],
                "phone": phone,
                "phone_code_hash": sent_code.phone_code_hash,
                "client": temp_client
            }
            await status.edit_text(
                "📩 **Telegram par OTP aaya hoga!**\n"
                "OTP ko space dekar bhejein (jaise `1 2 3 4 5`):"
            )
        except Exception as e:
            await temp_client.disconnect()
            user_states.pop(uid, None)
            await status.edit_text(f"❌ OTP bhejne mein error: `{e}`")

    elif step == "login_otp":
        otp = text.replace(" ", "")
        temp_client: Client = st["client"]
        status = await message.reply_text("⏳ Verify ho raha hai...")
        try:
            await temp_client.sign_in(st["phone"], st["phone_code_hash"], otp)
            ss = await temp_client.export_session_string()
            await temp_client.disconnect()
            set_user_cfg(uid, "session_string", ss)
            user_states[uid] = {"step": "priv_menu", "dest": st["dest"]}
            await status.edit_text(
                "✅ **Telegram Login Successful!**\n\n👇 Ab option chunein:",
                reply_markup=private_type_kb()
            )
        except SessionPasswordNeeded:
            user_states[uid]["step"] = "login_2fa"
            await status.edit_text("🔐 **2-Step Verification Password** dalein:")
        except PhoneCodeInvalid:
            await status.edit_text("❌ Galat OTP! Dobara sahi OTP dalein:")
        except Exception as e:
            await temp_client.disconnect()
            user_states.pop(uid, None)
            await status.edit_text(f"❌ Login fail: `{e}`")

    elif step == "login_2fa":
        temp_client: Client = st["client"]
        status = await message.reply_text("⏳ Password check ho raha hai...")
        try:
            await temp_client.check_password(text)
            ss = await temp_client.export_session_string()
            await temp_client.disconnect()
            set_user_cfg(uid, "session_string", ss)
            user_states[uid] = {"step": "priv_menu", "dest": st["dest"]}
            await status.edit_text(
                "✅ **Telegram Login Successful!**\n\n👇 Ab option chunein:",
                reply_markup=private_type_kb()
            )
        except PasswordHashInvalid:
            await status.edit_text("❌ Galat Password! Dobara dalein:")
        except Exception as e:
            await temp_client.disconnect()
            user_states.pop(uid, None)
            await status.edit_text(f"❌ Error: `{e}`")

    # 4. Public Link / Group Transfer Execution
    elif step in ["awaiting_public_link", "awaiting_grouptransfer_link"]:
        dest = st["dest"]
        user_states.pop(uid, None)
        source_chat, start_id, _ = parse_tg_link(text)
        status = await message.reply_text("⏳ Channel/Group connect ho raha hai...")

        cfg = get_user_cfg(uid)
        if cfg.get("session_string"):
            reader = Client(f"reader_{uid}", api_id=API_ID, api_hash=API_HASH, session_string=cfg["session_string"], in_memory=True, workers=32, max_concurrent_transmissions=8)
            await reader.start()
            asyncio.create_task(run_transfer(status, uid, reader, source_chat, start_id, dest, need_stop_reader=True))
        elif master_user:
            asyncio.create_task(run_transfer(status, uid, master_user, source_chat, start_id, dest, need_stop_reader=False))
        else:
            await status.edit_text("❌ Pehle Private mode se 1 baar Telegram login karein ya `MASTER_SESSION` dalein.")

    # 5. Private Full Link / First Link Execution
    elif step in ["awaiting_priv_full_link", "awaiting_priv_first_link"]:
        dest = st["dest"]
        user_states.pop(uid, None)
        cfg = get_user_cfg(uid)
        if not cfg.get("session_string"):
            await message.reply_text("❌ Pehle Telegram login karein!")
            return

        source_chat, start_id, _ = parse_tg_link(text)
        if step == "awaiting_priv_full_link":
            start_id = 1

        status = await message.reply_text("⏳ Private Channel/Group connect ho raha hai...")
        reader = Client(f"reader_{uid}", api_id=API_ID, api_hash=API_HASH, session_string=cfg["session_string"], in_memory=True, workers=32, max_concurrent_transmissions=8)
        await reader.start()
        asyncio.create_task(run_transfer(status, uid, reader, source_chat, start_id, dest, need_stop_reader=True))

    # 6. /grouptopictransfer Execution
    elif step == "awaiting_topic_link":
        dest = st["dest"]
        user_states.pop(uid, None)
        source_chat, _, topic_id = parse_tg_link(text)

        if not topic_id:
            await message.reply_text(
                "❌ **Is link mein Topic ID nahi hai!**\n"
                "Kisi Topic ke andar jakar kisi file/message ka link copy karein (jaise `https://t.me/c/xxxx/12/45`)."
            )
            return

        status = await message.reply_text("⏳ Topic scan ho raha hai aur destination mein wahi topic banaya ja raha hai...")
        cfg = get_user_cfg(uid)
        if cfg.get("session_string"):
            reader = Client(f"reader_{uid}", api_id=API_ID, api_hash=API_HASH, session_string=cfg["session_string"], in_memory=True, workers=32, max_concurrent_transmissions=8)
            await reader.start()
            asyncio.create_task(
                run_transfer(status, uid, reader, source_chat, 1, dest, topic_mode=True, source_topic_id=topic_id, need_stop_reader=True)
            )
        elif master_user:
            asyncio.create_task(
                run_transfer(status, uid, master_user, source_chat, 1, dest, topic_mode=True, source_topic_id=topic_id, need_stop_reader=False)
            )
        else:
            await status.edit_text("❌ Pehle Private mode mein login karein ya `MASTER_SESSION` set karein.")

# ===================== STARTUP =====================
async def main():
    clear_old_webhook(BOT_TOKEN)
    threading.Thread(target=run_web, daemon=True).start()
    if master_user:
        await master_user.start()
        print("✅ Master User Session Connected!")
    await bot.start()
    print("✅ Password-Protected High-Speed Bot Started!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    loop.run_until_complete(main())
