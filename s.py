import sqlite3
import secrets
from datetime import datetime, timedelta

import jdatetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = "8952875701:AAFZacIec2YPSIkA2K9vSFxnnbRdNiZb59g"

ADMIN_ID = 8815017184
SUPPORT_USERNAME = "@kaletek_Support"
DB_PATH = "bot.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده است.")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID تنظیم نشده است.")


# =========================================================
# PLANS
# =========================================================

PLANS = {
    "p50": {
        "name": "50 گیگ",
        "gb": 50,
        "days": 30,
        "price": 89000,
    },
    "p100": {
        "name": "100 گیگ",
        "gb": 100,
        "days": 30,
        "price": 149000,
    },
    "p200": {
        "name": "200 گیگ",
        "gb": 200,
        "days": 30,
        "price": 229000,
    },
}


# =========================================================
# DATABASE
# =========================================================

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

    row = cur.execute(
        "SELECT * FROM users WHERE user_id=?",
        (tg_user.id,)
    ).fetchone()

    if not row:
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
            UPDATE users
            SET username=?, first_name=?
            WHERE user_id=?
        """, (
            tg_user.username or "",
            tg_user.first_name or "",
            tg_user.id,
        ))

    con.commit()
    con.close()


def get_user(user_id):
    con = db()
    row = con.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()
    con.close()
    return row


def get_services(user_id):
    con = db()

    rows = con.execute("""
        SELECT *
        FROM services
        WHERE user_id=?
        ORDER BY id DESC
    """, (user_id,)).fetchall()

    con.close()
    return rows


def create_order(user_id, plan_key):
    plan = PLANS[plan_key]

    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO orders
        (user_id, plan_key, amount, created_at)
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

    while con.execute(
        "SELECT 1 FROM services WHERE code=?",
        (code,)
    ).fetchone():
        code = str(secrets.randbelow(9000) + 1000)

    cur = con.cursor()

    cur.execute("""
        INSERT INTO services
        (
            user_id,
            code,
            plan_key,
            config,
            total_gb,
            expires_at,
            purchased_at
        )
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


# =========================================================
# HELPERS
# =========================================================

def format_price(number):
    return f"{number:,}".replace(",", "٬") + " تومان"


def jalali_date(iso_date):
    dt = datetime.fromisoformat(iso_date)

    j = jdatetime.datetime.fromgregorian(
        datetime=dt
    )

    return j.strftime("%Y/%m/%d %H:%M")


def back_button(target="home"):
    return InlineKeyboardButton(
        "🔙 بازگشت",
        callback_data=target
    )


# =========================================================
# USER PANEL
# =========================================================

def main_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🛒 خرید سرویس",
                callback_data="buy"
            ),
            InlineKeyboardButton(
                "📦 سرویس‌های من",
                callback_data="services"
            ),
        ],

        [
            InlineKeyboardButton(
                "🔄 تمدید سرویس",
                callback_data="renew"
            ),
            InlineKeyboardButton(
                "👤 حساب من",
                callback_data="profile"
            ),
        ],

        [
            InlineKeyboardButton(
                "🎁 دعوت دوستان",
                callback_data="ref"
            ),
            InlineKeyboardButton(
                "📚 آموزش",
                callback_data="guide"
            ),
        ],

        [
            InlineKeyboardButton(
                "💬 پشتیبانی",
                callback_data="support"
            ),
        ],

    ])


def plans_menu(prefix="plan"):

    buttons = []

    for key, plan in PLANS.items():

        buttons.append([
            InlineKeyboardButton(
                f"⚡ {plan['name']} • {format_price(plan['price'])}",
                callback_data=f"{prefix}:{key}"
            )
        ])

    buttons.append([
        back_button("home")
    ])

    return InlineKeyboardMarkup(buttons)


# =========================================================
# ADMIN PANEL
# =========================================================

def admin_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📊 آمار",
                callback_data="admin_stats"
            ),
            InlineKeyboardButton(
                "📋 سفارش‌ها",
                callback_data="admin_orders"
            ),
        ],

        [
            InlineKeyboardButton(
                "👥 کاربران",
                callback_data="admin_users"
            ),
            InlineKeyboardButton(
                "📦 سرویس‌ها",
                callback_data="admin_services"
            ),
        ],

        [
            InlineKeyboardButton(
                "➕ تحویل سرویس",
                callback_data="admin_deliver"
            ),
        ],

        [
            InlineKeyboardButton(
                "🏠 پنل کاربری",
                callback_data="home"
            ),
        ],

    ])


# =========================================================
# TEXTS
# =========================================================

WELCOME = """
<b>🚀 VPN STORE</b>

━━━━━━━━━━━━━━━━━━

سلام 👋
به فروشگاه آنلاین سرویس خوش اومدی.

⚡ تحویل سریع
🔐 سرویس اختصاصی
📦 مدیریت سرویس‌ها
💳 خرید آسان
💬 پشتیبانی

از منوی زیر انتخاب کن:
"""


# =========================================================
# USER PAGES
# =========================================================

def services_text(user_id):

    services = get_services(user_id)

    if not services:
        return """
📦 <b>سرویس‌های من</b>

━━━━━━━━━━━━━━━━━━

📭 هنوز سرویسی برای حساب شما ثبت نشده.

برای خرید اولین سرویس روی
«🛒 خرید سرویس» بزنید.
"""

    lines = [
        "📦 <b>سرویس‌های من</b>",
        "━━━━━━━━━━━━━━━━━━"
    ]

    for service in services:

        status = (
            "🟢 فعال"
            if service["active"]
            else "🔴 غیرفعال"
        )

        plan = PLANS.get(
            service["plan_key"],
            {"name": service["plan_key"]}
        )

        lines.extend([
            f"🛰 <b>{plan['name']}</b>",
            f"🔑 کد سرویس: <code>{service['code']}</code>",
            f"📊 وضعیت: {status}",
            f"📦 حجم: {service['total_gb']} GB",
            f"📅 انقضا: {jalali_date(service['expires_at'])}",
            f"🛒 خرید: {jalali_date(service['purchased_at'])}",
            "━━━━━━━━━━━━━━━━━━",
        ])

    return "\n".join(lines)


def profile_text(user_id):

    user = get_user(user_id)
    services = get_services(user_id)

    active_services = sum(
        1 for x in services if x["active"]
    )

    username = (
        f"@{user['username']}"
        if user["username"]
        else "ندارد"
    )

    return f"""
👤 <b>حساب کاربری</b>

━━━━━━━━━━━━━━━━━━

🆔 شناسه:
<code>{user_id}</code>

👤 نام:
{user['first_name'] or '—'}

🔗 یوزرنیم:
{username}

📦 تعداد سرویس:
<b>{len(services)}</b>

🟢 سرویس فعال:
<b>{active_services}</b>

🎁 کد دعوت:
<code>{user['ref_code']}</code>

📅 عضویت:
{jalali_date(user['created_at'])}
"""


# =========================================================
# COMMANDS
# =========================================================

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

    ensure_user(
        user,
        referred_by
    )

    await update.message.reply_text(
        WELCOME,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu()
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )

        return

    await update.message.reply_text(
        """
👑 <b>پنل مدیریت</b>

━━━━━━━━━━━━━━━━━━

به پنل مدیریت فروشگاه خوش آمدید.

یک گزینه را انتخاب کنید:
""",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu()
    )


# =========================================================
# CALLBACKS
# =========================================================

async def callbacks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    q = update.callback_query

    await q.answer()

    user_id = q.from_user.id

    ensure_user(q.from_user)

    data = q.data

    # =====================================================
    # HOME
    # =====================================================

    if data == "home":

        await q.edit_message_text(
            WELCOME,
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu()
        )

        return

    # =====================================================
    # BUY
    # =====================================================

    if data == "buy":

        await q.edit_message_text(
            """
🛒 <b>خرید سرویس</b>

━━━━━━━━━━━━━━━━━━

پلن موردنظر خودت را انتخاب کن:

⚡ تحویل سریع
🔐 سرویس اختصاصی
📅 اعتبار ۳۰ روزه
""",
            parse_mode=ParseMode.HTML,
            reply_markup=plans_menu("plan")
        )

        return

    # =====================================================
    # PLAN
    # =====================================================

    if data.startswith("plan:"):

        plan_key = data.split(":", 1)[1]

        plan = PLANS.get(plan_key)

        if not plan:
            return

        order_id = create_order(
            user_id,
            plan_key
        )

        text = f"""
🧾 <b>سفارش #{order_id}</b>

━━━━━━━━━━━━━━━━━━

⚡ سرویس: <b>{plan['name']}</b>
📦 حجم: <b>{plan['gb']} GB</b>
⏱ اعتبار: <b>{plan['days']} روز</b>

💰 مبلغ:

<b>{format_price(plan['price'])}</b>

━━━━━━━━━━━━━━━━━━

برای ادامه روی «💳 پرداخت» بزن.
"""

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "💳 پرداخت",
                    callback_data=f"pay:{order_id}"
                )
            ],

            [
                back_button("buy")
            ],

        ])

        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

        return

    # =====================================================
    # PAYMENT
    # =====================================================

    if data.startswith("pay:"):

        order_id = data.split(":", 1)[1]

        await q.edit_message_text(

            f"""
💳 <b>پرداخت سفارش #{order_id}</b>

━━━━━━━━━━━━━━━━━━

این قسمت آماده اتصال به درگاه پرداخت است.

پس از اتصال درگاه:

1️⃣ پرداخت کاربر
2️⃣ تأیید تراکنش
3️⃣ تأیید سفارش
4️⃣ ساخت سرویس
5️⃣ ارسال کانفیگ

⚠️ در نسخه فعلی پرداخت واقعی فعال نیست.
""",

            parse_mode=ParseMode.HTML,

            reply_markup=InlineKeyboardMarkup([
                [
                    back_button("buy")
                ]
            ])
        )

        return

    # =====================================================
    # SERVICES
    # =====================================================

    if data == "services":

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🔄 تمدید",
                    callback_data="renew"
                )
            ],

            [
                InlineKeyboardButton(
                    "🛒 خرید سرویس",
                    callback_data="buy"
                )
            ],

            [
                back_button("home")
            ],

        ])

        await q.edit_message_text(
            services_text(user_id),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )

        return

    # =====================================================
    # RENEW
    # =====================================================

    if data == "renew":

        services = get_services(user_id)

        if not services:

            await q.edit_message_text(

                """
🔄 <b>تمدید سرویس</b>

━━━━━━━━━━━━━━━━━━

📭 شما هنوز سرویسی ندارید.

ابتدا یک سرویس خریداری کنید.
""",

                parse_mode=ParseMode.HTML,

                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🛒 خرید سرویس",
                            callback_data="buy"
                        )
                    ],
                    [
                        back_button("home")
                    ]
                ])
            )

            return

        await q.edit_message_text(

            """
🔄 <b>تمدید سرویس</b>

━━━━━━━━━━━━━━━━━━

پلن موردنظر برای تمدید را انتخاب کن:
""",

            parse_mode=ParseMode.HTML,

            reply_markup=plans_menu("renewplan")
        )

        return

    # =====================================================
    # RENEW PLAN
    # =====================================================

    if data.startswith("renewplan:"):

        plan_key = data.split(":", 1)[1]

        plan = PLANS.get(plan_key)

        if not plan:
            return

        order_id = create_order(
            user_id,
            plan_key
        )

        await q.edit_message_text(

            f"""
🔄 <b>تمدید سرویس</b>

━━━━━━━━━━━━━━━━━━

⚡ پلن: {plan['name']}
📦 حجم: {plan['gb']} GB
⏱ اعتبار: {plan['days']} روز

💰 مبلغ:
<b>{format_price(plan['price'])}</b>

🧾 سفارش:
<code>#{order_id}</code>
""",

            parse_mode=ParseMode.HTML,

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "💳 پرداخت",
                        callback_data=f"pay:{order_id}"
                    )
                ],

                [
                    back_button("renew")
                ],

            ])
        )

        return

    # =====================================================
    # PROFILE
    # =====================================================

    if data == "profile":

        await q.edit_message_text(

            profile_text(user_id),

            parse_mode=ParseMode.HTML,

            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "📦 سرویس‌های من",
                        callback_data="services"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🎁 دعوت دوستان",
                        callback_data="ref"
                    )
                ],

                [
                    back_button("home")
                ],

            ])
        )

        return

    # =====================================================
    # REFERRAL
    # =====================================================

    if data == "ref":

        bot_username = context.bot.username

        link = (
            f"https://t.me/"
            f"{bot_username}"
            f"?start={user_id}"
        )

        await q.edit_message_text(

            f"""
🎁 <b>دعوت دوستان</b>

━━━━━━━━━━━━━━━━━━

لینک اختصاصی شما:

<code>{link}</code>

━━━━━━━━━━━━━━━━━━

لینک را برای دوستانت ارسال کن.

هر کاربر جدیدی که از لینک تو وارد شود
در سیستم ثبت خواهد شد.
""",

            parse_mode=ParseMode.HTML,

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 منوی اصلی",
                        callback_data="home"
                    )
                ]
            ])
        )

        return

    # =====================================================
    # GUIDE
    # =====================================================

    if data == "guide":

        await q.edit_message_text(

            """
📚 <b>آموزش اتصال</b>

━━━━━━━━━━━━━━━━━━

بعد از خرید سرویس، کانفیگ از طریق ربات
برای شما ارسال می‌شود.

🔹 کانفیگ را کپی کنید.
🔹 آن را داخل برنامه سازگار با نوع کانفیگ وارد کنید.
🔹 سپس اتصال را فعال کنید.

اگر در اتصال مشکل داشتی، از بخش
«💬 پشتیبانی» با ما در ارتباط باش.
""",

            parse_mode=ParseMode.HTML,

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💬 پشتیبانی",
                        callback_data="support"
                    )
                ],
                [
                    back_button("home")
                ]
            ])
        )

        return

    # =====================================================
    # SUPPORT
    # =====================================================

    if data == "support":

        await q.edit_message_text(

            f"""
💬 <b>پشتیبانی</b>

━━━━━━━━━━━━━━━━━━

اگر در خرید یا سرویس مشکلی داری،
با پشتیبانی در ارتباط باش:

👤 {SUPPORT_USERNAME}

لطفاً هنگام ارسال پیام، شماره سفارش
یا کد سرویس را هم بفرست.
""",

            parse_mode=ParseMode.HTML,

            reply_markup=InlineKeyboardMarkup([
                [
                    back_button("home")
                ]
            ])
        )

        return

    # =====================================================
    # ADMIN SECURITY
    # =====================================================

    if user_id != ADMIN_ID:
        return

    # =====================================================
    # ADMIN HOME
    # =====================================================

    if data == "admin_home":

        await q.edit_message_text(

            """
👑 <b>پنل مدیریت</b>

━━━━━━━━━━━━━━━━━━

یک گزینه را انتخاب کنید:
""",

            parse_mode=ParseMode.HTML,

            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # ADMIN STATS
    # =====================================================

    if data == "admin_stats":

        con = db()

        users = con.execute(
            "SELECT COUNT(*) c FROM users"
        ).fetchone()["c"]

        services = con.execute(
            "SELECT COUNT(*) c FROM services"
        ).fetchone()["c"]

        active_services = con.execute(
            "SELECT COUNT(*) c FROM services WHERE active=1"
        ).fetchone()["c"]

        orders = con.execute(
            "SELECT COUNT(*) c FROM orders"
        ).fetchone()["c"]

        pending = con.execute(
            "SELECT COUNT(*) c FROM orders WHERE status='pending'"
        ).fetchone()["c"]

        paid = con.execute(
            "SELECT COUNT(*) c FROM orders WHERE status='paid'"
        ).fetchone()["c"]

        con.close()

        await q.edit_message_text(

            f"""
📊 <b>آمار فروشگاه</b>

━━━━━━━━━━━━━━━━━━

👥 کاربران:
<b>{users}</b>

📦 کل سرویس‌ها:
<b>{services}</b>

🟢 سرویس‌های فعال:
<b>{active_services}</b>

🧾 کل سفارش‌ها:
<b>{orders}</b>

💳 پرداخت‌شده:
<b>{paid}</b>

⏳ در انتظار پرداخت:
<b>{pending}</b>
""",

            parse_mode=ParseMode.HTML,

            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # ADMIN ORDERS
    # =====================================================

    if data == "admin_orders":

        con = db()

        rows = con.execute("""
            SELECT
                id,
                user_id,
                plan_key,
                amount,
                status,
                created_at
            FROM orders
            ORDER BY id DESC
            LIMIT 15
        """).fetchall()

        con.close()

        if not rows:

            text = "📋 هنوز سفارشی ثبت نشده."

        else:

            lines = [
                "📋 <b>آخرین سفارش‌ها</b>",
                "━━━━━━━━━━━━━━━━━━"
            ]

            for row in rows:

                plan = PLANS.get(
                    row["plan_key"],
                    {"name": row["plan_key"]}
                )

                lines.append(
                    f"🧾 <b>#{row['id']}</b>\n"
                    f"👤 <code>{row['user_id']}</code>\n"
                    f"⚡ {plan['name']}\n"
                    f"💰 {format_price(row['amount'])}\n"
                    f"📌 وضعیت: {row['status']}\n"
                    f"━━━━━━━━━━━━━━━━━━"
                )

            text = "\n".join(lines)

        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # ADMIN USERS
    # =====================================================

    if data == "admin_users":

        con = db()

        rows = con.execute("""
            SELECT user_id, username, first_name, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT 15
        """).fetchall()

        total = con.execute(
            "SELECT COUNT(*) c FROM users"
        ).fetchone()["c"]

        con.close()

        lines = [
            f"👥 <b>کاربران</b> — مجموع: {total}",
            "━━━━━━━━━━━━━━━━━━"
        ]

        for row in rows:

            username = (
                f"@{row['username']}"
                if row["username"]
                else "بدون یوزرنیم"
            )

            lines.append(
                f"👤 {row['first_name'] or 'بدون نام'}\n"
                f"🆔 <code>{row['user_id']}</code>\n"
                f"🔗 {username}\n"
                f"━━━━━━━━━━━━━━━━━━"
            )

        await q.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # ADMIN SERVICES
    # =====================================================

    if data == "admin_services":

        con = db()

        rows = con.execute("""
            SELECT
                id,
                user_id,
                code,
                plan_key,
                expires_at,
                active
            FROM services
            ORDER BY id DESC
            LIMIT 15
        """).fetchall()

        total = con.execute(
            "SELECT COUNT(*) c FROM services"
        ).fetchone()["c"]

        con.close()

        lines = [
            f"📦 <b>سرویس‌ها</b> — مجموع: {total}",
            "━━━━━━━━━━━━━━━━━━"
        ]

        for row in rows:

            plan = PLANS.get(
                row["plan_key"],
                {"name": row["plan_key"]}
            )

            status = (
                "🟢 فعال"
                if row["active"]
                else "🔴 غیرفعال"
            )

            lines.append(
                f"🛰 {plan['name']}\n"
                f"👤 <code>{row['user_id']}</code>\n"
                f"🔑 <code>{row['code']}</code>\n"
                f"{status}\n"
                f"📅 {jalali_date(row['expires_at'])}\n"
                f"━━━━━━━━━━━━━━━━━━"
            )

        await q.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # ADMIN DELIVERY
    # =====================================================

    if data == "admin_deliver":

        context.user_data["awaiting_delivery"] = True

        await q.edit_message_text(

            """
➕ <b>تحویل دستی سرویس</b>

━━━━━━━━━━━━━━━━━━

در پیام بعدی دقیقاً این قالب را بفرست:

<code>USER_ID|PLAN_KEY|CONFIG</code>

مثال:

<code>123456789|p50|vless://...</code>

━━━━━━━━━━━━━━━━━━

پلن‌ها:

<code>p50</code> → 50 گیگ
<code>p100</code> → 100 گیگ
<code>p200</code> → 200 گیگ
""",

            parse_mode=ParseMode.HTML,

            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 پنل مدیریت",
                        callback_data="admin_home"
                    )
                ]
            ])
        )

        return


# =========================================================
# ADMIN DELIVERY
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    if not context.user_data.get(
        "awaiting_delivery"
    ):
        return

    raw = update.message.text.strip()

    parts = raw.split("|", 2)

    if len(parts) != 3:

        await update.message.reply_text(
            """
❌ فرمت اشتباه است.

فرمت صحیح:

<code>USER_ID|PLAN_KEY|CONFIG</code>
""",
            parse_mode=ParseMode.HTML
        )

        return

    try:

        user_id = int(
            parts[0].strip()
        )

    except ValueError:

        await update.message.reply_text(
            "❌ USER_ID باید عدد باشد."
        )

        return

    plan_key = parts[1].strip()
    config = parts[2].strip()

    if plan_key not in PLANS:

        await update.message.reply_text(
            "❌ PLAN_KEY نامعتبر است."
        )

        return

    service_id, code = create_service(
        user_id,
        plan_key,
        config
    )

    context.user_data[
        "awaiting_delivery"
    ] = False

    plan = PLANS[plan_key]

    await update.message.reply_text(

        f"""
✅ <b>سرویس ساخته شد</b>

━━━━━━━━━━━━━━━━━━

👤 کاربر:
<code>{user_id}</code>

🔑 کد سرویس:
<code>{code}</code>

⚡ پلن:
{plan['name']}

🆔 Service ID:
<code>{service_id}</code>

📨 کانفیگ برای کاربر ارسال می‌شود.
""",

        parse_mode=ParseMode.HTML
    )

    try:

        await context.bot.send_message(

            chat_id=user_id,

            text=f"""
🎉 <b>سرویس شما آماده شد</b>

━━━━━━━━━━━━━━━━━━

🛰 سرویس:
<b>{plan['name']}</b>

📦 حجم:
<b>{plan['gb']} GB</b>

⏱ اعتبار:
<b>{plan['days']} روز</b>

🔑 کد سرویس:
<code>{code}</code>

━━━━━━━━━━━━━━━━━━

<b>🔐 کانفیگ:</b>

<code>{config}</code>

━━━━━━━━━━━━━━━━━━

برای مشاهده سرویس‌های خودت،
وارد بخش «📦 سرویس‌های من» شو.
""",

            parse_mode=ParseMode.HTML
        )

    except Exception as e:

        await update.message.reply_text(
            f"""
⚠️ سرویس ساخته شد،
اما ارسال به کاربر ناموفق بود.

خطا:
<code>{str(e)}</code>
""",
            parse_mode=ParseMode.HTML
        )


# =========================================================
# ERROR
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print(
        "BOT ERROR:",
        repr(context.error)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            callbacks
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "VPN Store Bot is running..."
    )

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
