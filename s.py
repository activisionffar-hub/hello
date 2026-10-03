import os
import sqlite3
import secrets
from datetime import datetime, timedelta

import jdatetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("8952875701:AAFZacIec2YPSIkA2K9vSFxnnbRdNiZb59g", "").strip()
ADMIN_ID = int(os.getenv("8815017184", "0") or 0)
SUPPORT_USERNAME = os.getenv("8815017184", "@kaletek_Support")
DB_PATH = os.getenv("DB_PATH", "bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده است.")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID تنظیم نشده است.")

# Plans: edit prices/names here
PLANS = {
    "p50":  {"name": "50 گیگ",  "gb": 50,  "days": 30, "price": 89000},
    "p100": {"name": "100 گیگ", "gb": 100, "days": 30, "price": 149000},
    "p200": {"name": "200 گیگ", "gb": 200, "days": 30, "price": 229000},
}

# =========================
# DATABASE
# =========================
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        ref_code TEXT UNIQUE,
        referred_by INTEGER,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        code TEXT UNIQUE NOT NULL,
        plan_key TEXT NOT NULL,
        config TEXT NOT NULL,
        total_gb INTEGER NOT NULL,
        used_gb REAL DEFAULT 0,
        expires_at TEXT NOT NULL,
        purchased_at TEXT NOT NULL,
        active INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        plan_key TEXT NOT NULL,
        amount INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TEXT NOT NULL
    )
    """)

    con.commit()
    con.close()

def ensure_user(tg_user, referred_by=None):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (tg_user.id,))
    exists = cur.fetchone()

    if not exists:
        ref_code = secrets.token_hex(4).upper()
        cur.execute("""
            INSERT INTO users
            (user_id, username, first_name, ref_code, referred_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            tg_user.id,
            tg_user.username or "",
            tg_user.first_name or "",
            ref_code,
            referred_by,
            datetime.now().isoformat(timespec="seconds"),
        ))
    else:
        cur.execute("""
            UPDATE users SET username=?, first_name=? WHERE user_id=?
        """, (tg_user.username or "", tg_user.first_name or "", tg_user.id))

    con.commit()
    con.close()

def get_user(user_id):
    con = db()
    row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row

def get_services(user_id):
    con = db()
    rows = con.execute("""
        SELECT * FROM services WHERE user_id=? ORDER BY id DESC
    """, (user_id,)).fetchall()
    con.close()
    return rows

def create_order(user_id, plan_key):
    plan = PLANS[plan_key]
    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO orders (user_id, plan_key, amount, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        plan_key,
        plan["price"],
        datetime.now().isoformat(timespec="seconds"),
    ))
    order_id = cur.lastrowid
    con.commit()
    con.close()
    return order_id

def create_service(user_id, plan_key, config):
    plan = PLANS[plan_key]
    now = datetime.now()
    expires = now + timedelta(days=plan["days"])
    code = str(secrets.randbelow(9000) + 1000)

    con = db()
    # Ensure unique code
    while con.execute("SELECT 1 FROM services WHERE code=?", (code,)).fetchone():
        code = str(secrets.randbelow(9000) + 1000)

    cur = con.cursor()
    cur.execute("""
        INSERT INTO services
        (user_id, code, plan_key, config, total_gb, expires_at, purchased_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        code,
        plan_key,
        config,
        plan["gb"],
        expires.isoformat(timespec="seconds"),
        now.isoformat(timespec="seconds"),
    ))
    service_id = cur.lastrowid
    con.commit()
    con.close()
    return service_id, code

def format_price(n):
    return f"{n:,}".replace(",", "٬") + " تومان"

def jalali_date(iso_date):
    dt = datetime.fromisoformat(iso_date)
    j = jdatetime.datetime.fromgregorian(datetime=dt)
    return j.strftime("%Y/%m/%d %H:%M")

# =========================
# UI
# =========================
def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy"),
            InlineKeyboardButton("📦 سرویس‌های من", callback_data="services"),
        ],
        [
            InlineKeyboardButton("🔄 تمدید سرویس", callback_data="renew"),
            InlineKeyboardButton("🎁 دعوت دوستان", callback_data="ref"),
        ],
        [
            InlineKeyboardButton("💬 پشتیبانی", callback_data="support"),
        ],
    ])

def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 آمار", callback_data="admin_stats"),
            InlineKeyboardButton("📋 سفارش‌ها", callback_data="admin_orders"),
        ],
        [
            InlineKeyboardButton("➕ تحویل سرویس", callback_data="admin_deliver"),
        ],
    ])

def plans_menu(prefix="plan"):
    buttons = []
    for key, plan in PLANS.items():
        buttons.append([
            InlineKeyboardButton(
                f"⚡ {plan['name']} | {format_price(plan['price'])}",
                callback_data=f"{prefix}:{key}"
            )
        ])
    buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="home")])
    return InlineKeyboardMarkup(buttons)

# =========================
# TEXT
# =========================
WELCOME = """<b>🚀 VPN STORE</b>

به فروشگاه آنلاین سرویس خوش اومدی 👋

⚡ تحویل سریع
🔐 سرویس اختصاصی
📦 مدیریت سرویس‌ها
💬 پشتیبانی

از منوی زیر شروع کن:"""

def services_text(user_id):
    services = get_services(user_id)
    if not services:
        return "📦 <b>سرویس‌های من</b>\n\nهنوز سرویسی برای حسابت ثبت نشده است."

    lines = ["📦 <b>سرویس‌های من</b>", "━━━━━━━━━━━━━━"]
    for s in services:
        status = "🟢 فعال" if s["active"] else "🔴 غیرفعال"
        plan = PLANS.get(s["plan_key"], {"name": s["plan_key"]})
        lines += [
            f"🛰 <b>کانفیگ {plan['name']}</b>",
            f"کد سرویس: <code>{s['code']}</code>",
            f"وضعیت: {status}",
            f"حجم: {s['total_gb']:.2f} GB",
            f"پایان اعتبار: {jalali_date(s['expires_at'])}",
            f"تاریخ خرید: {jalali_date(s['purchased_at'])}",
            "━━━━━━━━━━━━━━",
        ]
    return "\n".join(lines)

# =========================
# COMMANDS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referred_by = None

    if context.args:
        try:
            candidate = int(context.args[0])
            if candidate != user.id:
                referred_by = candidate
        except ValueError:
            pass

    ensure_user(user, referred_by)

    await update.message.reply_text(
        WELCOME,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی ندارید.")
        return

    await update.message.reply_text(
        "🛠 <b>پنل مدیریت</b>\n\nیک گزینه را انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu(),
    )

# =========================
# CALLBACKS
# =========================
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    ensure_user(q.from_user)

    data = q.data

    if data == "home":
        await q.edit_message_text(
            WELCOME,
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
        return

    if data == "buy":
        await q.edit_message_text(
            "🛒 <b>انتخاب سرویس</b>\n\nحجم و قیمت موردنظر را انتخاب کن:",
            parse_mode=ParseMode.HTML,
            reply_markup=plans_menu("plan"),
        )
        return

    if data.startswith("plan:"):
        plan_key = data.split(":", 1)[1]
        plan = PLANS.get(plan_key)
        if not plan:
            return

        order_id = create_order(user_id, plan_key)

        text = f"""🧾 <b>سفارش #{order_id}</b>

⚡ سرویس: {plan['name']}
📦 حجم: {plan['gb']} GB
⏱ اعتبار: {plan['days']} روز
💰 مبلغ: <b>{format_price(plan['price'])}</b>

برای اتصال درگاه بانکی، این بخش را به درگاه خودت وصل کن.
فعلاً سفارش با وضعیت «در انتظار پرداخت» ثبت شده است."""

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 پرداخت", callback_data=f"pay:{order_id}")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="buy")],
        ])
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data.startswith("pay:"):
        order_id = data.split(":", 1)[1]
        await q.edit_message_text(
            f"""💳 <b>پرداخت سفارش #{order_id}</b>

این نسخه آماده اتصال به درگاه بانکی است.

بعد از اتصال درگاه:
1️⃣ کاربر پرداخت می‌کند
2️⃣ درگاه تراکنش را تأیید می‌کند
3️⃣ سفارش خودکار تأیید می‌شود
4️⃣ کانفیگ برای کاربر ارسال می‌شود

فعلاً برای جلوگیری از دریافت پول واقعی، پرداخت غیرفعال است.""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 فروشگاه", callback_data="buy")]
            ])
        )
        return

    if data == "services":
        await q.edit_message_text(
            services_text(user_id),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 تمدید", callback_data="renew")],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")],
            ]),
        )
        return

    if data == "renew":
        services = get_services(user_id)
        if not services:
            await q.edit_message_text(
                "📭 سرویسی برای تمدید پیدا نشد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy")]
                ])
            )
            return

        await q.edit_message_text(
            "🔄 <b>تمدید سرویس</b>\n\nپلن موردنظر را انتخاب کن:",
            parse_mode=ParseMode.HTML,
            reply_markup=plans_menu("renewplan"),
        )
        return

    if data.startswith("renewplan:"):
        plan_key = data.split(":", 1)[1]
        order_id = create_order(user_id, plan_key)
        plan = PLANS[plan_key]
        await q.edit_message_text(
            f"""🔄 <b>تمدید آماده شد</b>

سرویس: {plan['name']}
حجم: {plan['gb']} GB
اعتبار: {plan['days']} روز
مبلغ: <b>{format_price(plan['price'])}</b>

شماره سفارش: <code>#{order_id}</code>""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 پرداخت", callback_data=f"pay:{order_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="home")],
            ])
        )
        return

    if data == "ref":
        me = get_user(user_id)
        bot_username = context.bot.username
        link = f"https://t.me/{bot_username}?start={user_id}"
        await q.edit_message_text(
            f"""🎁 <b>دعوت دوستان</b>

لینک اختصاصی تو:

<code>{link}</code>

لینک را برای دوستانت بفرست.
سیستم ارجاع آماده اتصال به پاداش و کمیسیون است.""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")]
            ])
        )
        return

    if data == "support":
        await q.edit_message_text(
            f"""💬 <b>پشتیبانی</b>

اگر مشکلی در خرید یا سرویس داری، پیام بده:

👤 {SUPPORT_USERNAME}

لطفاً کد سرویس یا شماره سفارش را هم ارسال کن.""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="home")]
            ])
        )
        return

    # -------------------------
    # ADMIN
    # -------------------------
    if user_id != ADMIN_ID:
        return

    if data == "admin_stats":
        con = db()
        users = con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        services = con.execute("SELECT COUNT(*) c FROM services").fetchone()["c"]
        orders = con.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"]
        pending = con.execute(
            "SELECT COUNT(*) c FROM orders WHERE status='pending'"
        ).fetchone()["c"]
        con.close()

        await q.edit_message_text(
            f"""📊 <b>آمار ربات</b>

👥 کاربران: <b>{users}</b>
📦 سرویس‌ها: <b>{services}</b>
🧾 سفارش‌ها: <b>{orders}</b>
⏳ در انتظار پرداخت: <b>{pending}</b>""",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu(),
        )
        return

    if data == "admin_orders":
        con = db()
        rows = con.execute("""
            SELECT id, user_id, plan_key, amount, status, created_at
            FROM orders ORDER BY id DESC LIMIT 15
        """).fetchall()
        con.close()

        if not rows:
            text = "📋 سفارشی ثبت نشده."
        else:
            lines = ["📋 <b>آخرین سفارش‌ها</b>", "━━━━━━━━━━━━━━"]
            for r in rows:
                p = PLANS.get(r["plan_key"], {"name": r["plan_key"]})
                lines.append(
                    f"#{r['id']} | {p['name']} | {format_price(r['amount'])}\n"
                    f"👤 <code>{r['user_id']}</code> | {r['status']}"
                )
            text = "\n".join(lines)

        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu(),
        )
        return

    if data == "admin_deliver":
        context.user_data["awaiting_delivery"] = True
        await q.edit_message_text(
            """➕ <b>تحویل دستی سرویس</b>

در پیام بعدی دقیقاً این قالب را بفرست:

<code>USER_ID|PLAN_KEY|CONFIG</code>

مثال:

<code>123456789|p50|vless://...</code>

PLAN_KEY ها:
<code>p50</code>
<code>p100</code>
<code>p200</code>""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 پنل مدیریت", callback_data="home")]
            ])
        )
        return

# =========================
# ADMIN DELIVERY MESSAGE
# =========================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.user_data.get("awaiting_delivery"):
        return

    raw = update.message.text.strip()
    parts = raw.split("|", 2)

    if len(parts) != 3:
        await update.message.reply_text(
            "❌ فرمت اشتباه است.\n\n"
            "مثال:\n"
            "<code>123456789|p50|vless://...</code>",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        user_id = int(parts[0])
    except ValueError:
        await update.message.reply_text("❌ USER_ID باید عدد باشد.")
        return

    plan_key = parts[1].strip()
    config = parts[2].strip()

    if plan_key not in PLANS:
        await update.message.reply_text("❌ PLAN_KEY نامعتبر است.")
        return

    service_id, code = create_service(user_id, plan_key, config)
    context.user_data["awaiting_delivery"] = False
    plan = PLANS[plan_key]

    await update.message.reply_text(
        f"""✅ <b>سرویس ساخته شد</b>

کاربر: <code>{user_id}</code>
کد سرویس: <code>{code}</code>
پلن: {plan['name']}

کانفیگ برای کاربر ارسال می‌شود.""",
        parse_mode=ParseMode.HTML
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"""🎉 <b>سرویس شما آماده شد</b>

🛰 سرویس: {plan['name']}
📦 حجم: {plan['gb']} GB
⏱ اعتبار: {plan['days']} روز
🔑 کد سرویس: <code>{code}</code>

<b>کانفیگ:</b>
<code>{config}</code>

از بخش «📦 سرویس‌های من» هم می‌توانی اطلاعات سرویس را ببینی.""",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ سرویس ساخته شد ولی ارسال به کاربر ناموفق بود: {e}")

# =========================
# ERROR
# =========================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("BOT ERROR:", repr(context.error))

# =========================
# MAIN
# =========================
def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)

    print("VPN Store Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
