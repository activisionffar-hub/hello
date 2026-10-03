
import sqlite3
import secrets
from datetime import datetime, timedelta
from html import escape

import jdatetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
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


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = "8952875701:AAFZacIec2YPSIkA2K9vSFxnnbRdNiZb59g"

ADMIN_ID = 8815017184
SUPPORT_USERNAME = "@kaletek_Support"
DB_PATH = "bot.db"

# شماره کارت و نام صاحب کارت را اینجا وارد کن
CARD_NUMBER = "5892 1014 0005 4561"
CARD_HOLDER = "ابوالفضل اختری فر"

# اگر برای پشتیبانی استیکر داری، file_id آن را اینجا بگذار
SUPPORT_STICKER_ID = "PASTE_STICKER_FILE_ID_HERE"

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


def ensure_column(con, table, column, definition):
    columns = [
        row["name"]
        for row in con.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    ]

    if column not in columns:
        con.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


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

    # سازگاری با دیتابیس قبلی
    ensure_column(
        con,
        "users",
        "wallet_balance",
        "INTEGER DEFAULT 0"
    )

    ensure_column(
        con,
        "users",
        "referral_gb_balance",
        "INTEGER DEFAULT 0"
    )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referral_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER NOT NULL,
            invited_user_id INTEGER UNIQUE NOT NULL,
            reward_gb INTEGER NOT NULL DEFAULT 3,
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
            active INTEGER DEFAULT 1,
            config_name TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_key TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            config_name TEXT
        )
    """)

    ensure_column(con, "services", "config_name", "TEXT")
    ensure_column(con, "orders", "config_name", "TEXT")

    # رسیدهای مربوط به خرید/سفارش
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payment_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            admin_id INTEGER,
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        )
    """)

    # درخواست‌های شارژ کیف پول
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            receipt_file_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            admin_id INTEGER,
            created_at TEXT NOT NULL,
            reviewed_at TEXT
        )
    """)

    # لاگ تراکنش‌های کیف پول
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            type TEXT NOT NULL,
            reference_id INTEGER,
            description TEXT,
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

    is_new = row is None

    if not row:
        ref_code = secrets.token_hex(4).upper()

        while cur.execute(
            "SELECT 1 FROM users WHERE ref_code=?",
            (ref_code,)
        ).fetchone():
            ref_code = secrets.token_hex(4).upper()

        cur.execute("""
            INSERT INTO users
            (
                user_id,
                username,
                first_name,
                ref_code,
                referred_by,
                created_at,
                wallet_balance
            )
            VALUES (?, ?, ?, ?, ?, ?, 0)
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
            SET username=?,
                first_name=?
            WHERE user_id=?
        """, (
            tg_user.username or "",
            tg_user.first_name or "",
            tg_user.id,
        ))

    con.commit()
    con.close()
    return is_new

def add_referral_reward(inviter_id, invited_user_id):
    if not inviter_id or inviter_id == invited_user_id:
        return False

    con = db()
    try:
        inviter = con.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (inviter_id,)
        ).fetchone()
        if not inviter:
            return False

        cur = con.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO referral_rewards
            (inviter_id, invited_user_id, reward_gb, created_at)
            VALUES (?, ?, 3, ?)
        """, (inviter_id, invited_user_id, datetime.now().isoformat(timespec="seconds")))

        if cur.rowcount == 1:
            cur.execute(
                "UPDATE users SET referral_gb_balance = COALESCE(referral_gb_balance, 0) + 3 WHERE user_id=?",
                (inviter_id,)
            )
            con.commit()
            return True
        con.commit()
        return False
    finally:
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
        (
            user_id,
            plan_key,
            amount,
            created_at
        )
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


def set_order_config_name(order_id, user_id, config_name):
    name = (config_name or "").strip()[:40]
    if not name:
        return False
    con = db()
    cur = con.execute(
        "UPDATE orders SET config_name=? WHERE id=? AND user_id=?",
        (name, order_id, user_id)
    )
    con.commit()
    con.close()
    return cur.rowcount == 1


def get_order_config_name(user_id, plan_key):
    con = db()
    row = con.execute(
        """SELECT config_name FROM orders
           WHERE user_id=? AND plan_key=? AND status='paid'
             AND config_name IS NOT NULL AND TRIM(config_name) != ''
           ORDER BY id DESC LIMIT 1""",
        (user_id, plan_key)
    ).fetchone()
    con.close()
    return row["config_name"] if row else None


def create_service(user_id, plan_key, config, config_name=None):
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
            purchased_at,
            config_name
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        code,
        plan_key,
        config,
        plan["gb"],
        expires.isoformat(timespec="seconds"),
        now.isoformat(timespec="seconds"),
        config_name,
    ))

    service_id = cur.lastrowid

    con.commit()
    con.close()

    return service_id, code


# =========================================================
# PAYMENT / WALLET DATABASE FUNCTIONS
# =========================================================

def has_pending_order_receipt(order_id):
    con = db()

    row = con.execute("""
        SELECT id
        FROM payment_receipts
        WHERE order_id=?
          AND status='pending'
        LIMIT 1
    """, (order_id,)).fetchone()

    con.close()
    return row is not None


def create_payment_receipt(order_id, user_id, amount, file_id):
    con = db()

    cur = con.cursor()

    cur.execute("""
        INSERT INTO payment_receipts
        (
            order_id,
            user_id,
            amount,
            file_id,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, 'pending', ?)
    """, (
        order_id,
        user_id,
        amount,
        file_id,
        datetime.now().isoformat(timespec="seconds"),
    ))

    receipt_id = cur.lastrowid

    cur.execute("""
        UPDATE orders
        SET status='receipt_pending'
        WHERE id=?
          AND status IN ('pending', 'rejected')
    """, (order_id,))

    con.commit()
    con.close()

    return receipt_id


def approve_payment_receipt(receipt_id, admin_id):
    """
    تأیید رسید خرید:
    مبلغ رسید دقیقاً به کیف پول کاربر اضافه می‌شود.
    با UPDATE شرطی status='pending' از دوباره شارژ شدن جلوگیری می‌شود.
    """
    con = db()

    try:
        con.execute("BEGIN")

        receipt = con.execute("""
            SELECT *
            FROM payment_receipts
            WHERE id=?
        """, (receipt_id,)).fetchone()

        if not receipt:
            con.rollback()
            return None, None, "not_found"

        cur = con.execute("""
            UPDATE payment_receipts
            SET status='approved',
                admin_id=?,
                reviewed_at=?
            WHERE id=?
              AND status='pending'
        """, (
            admin_id,
            datetime.now().isoformat(timespec="seconds"),
            receipt_id,
        ))

        if cur.rowcount != 1:
            con.rollback()
            return None, None, "already_processed"

        con.execute("""
            UPDATE users
            SET wallet_balance=COALESCE(wallet_balance, 0) + ?
            WHERE user_id=?
        """, (
            receipt["amount"],
            receipt["user_id"],
        ))

        con.execute("""
            UPDATE orders
            SET status='paid'
            WHERE id=?
        """, (receipt["order_id"],))

        con.execute("""
            INSERT INTO wallet_transactions
            (
                user_id,
                amount,
                type,
                reference_id,
                description,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            receipt["user_id"],
            receipt["amount"],
            "deposit_order",
            receipt["order_id"],
            f"شارژ کیف پول بابت سفارش #{receipt['order_id']}",
            datetime.now().isoformat(timespec="seconds"),
        ))

        balance_row = con.execute("""
            SELECT wallet_balance
            FROM users
            WHERE user_id=?
        """, (receipt["user_id"],)).fetchone()

        new_balance = (
            balance_row["wallet_balance"]
            if balance_row
            else receipt["amount"]
        )

        con.commit()

        return receipt, new_balance, "approved"

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


def reject_payment_receipt(receipt_id, admin_id):
    con = db()

    try:
        con.execute("BEGIN")

        receipt = con.execute("""
            SELECT *
            FROM payment_receipts
            WHERE id=?
        """, (receipt_id,)).fetchone()

        if not receipt:
            con.rollback()
            return None, "not_found"

        cur = con.execute("""
            UPDATE payment_receipts
            SET status='rejected',
                admin_id=?,
                reviewed_at=?
            WHERE id=?
              AND status='pending'
        """, (
            admin_id,
            datetime.now().isoformat(timespec="seconds"),
            receipt_id,
        ))

        if cur.rowcount != 1:
            con.rollback()
            return None, "already_processed"

        con.execute("""
            UPDATE orders
            SET status='rejected'
            WHERE id=?
        """, (receipt["order_id"],))

        con.commit()

        return receipt, "rejected"

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


def has_pending_wallet_deposit(user_id):
    con = db()

    row = con.execute("""
        SELECT id
        FROM wallet_deposits
        WHERE user_id=?
          AND status='pending'
        LIMIT 1
    """, (user_id,)).fetchone()

    con.close()
    return row is not None


def create_wallet_deposit(user_id, amount, file_id):
    con = db()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO wallet_deposits
        (
            user_id,
            amount,
            receipt_file_id,
            status,
            created_at
        )
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        user_id,
        amount,
        file_id,
        datetime.now().isoformat(timespec="seconds"),
    ))

    deposit_id = cur.lastrowid

    con.commit()
    con.close()

    return deposit_id


def approve_wallet_deposit(deposit_id, admin_id):
    """
    شارژ کیف پول با مبلغ دلخواه مشتری.
    فقط یک بار می‌تواند موفق شود.
    """
    con = db()

    try:
        con.execute("BEGIN")

        deposit = con.execute("""
            SELECT *
            FROM wallet_deposits
            WHERE id=?
        """, (deposit_id,)).fetchone()

        if not deposit:
            con.rollback()
            return None, None, "not_found"

        cur = con.execute("""
            UPDATE wallet_deposits
            SET status='approved',
                admin_id=?,
                reviewed_at=?
            WHERE id=?
              AND status='pending'
        """, (
            admin_id,
            datetime.now().isoformat(timespec="seconds"),
            deposit_id,
        ))

        if cur.rowcount != 1:
            con.rollback()
            return None, None, "already_processed"

        con.execute("""
            UPDATE users
            SET wallet_balance=COALESCE(wallet_balance, 0) + ?
            WHERE user_id=?
        """, (
            deposit["amount"],
            deposit["user_id"],
        ))

        con.execute("""
            INSERT INTO wallet_transactions
            (
                user_id,
                amount,
                type,
                reference_id,
                description,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            deposit["user_id"],
            deposit["amount"],
            "wallet_deposit",
            deposit_id,
            f"شارژ کیف پول #{deposit_id}",
            datetime.now().isoformat(timespec="seconds"),
        ))

        balance_row = con.execute("""
            SELECT wallet_balance
            FROM users
            WHERE user_id=?
        """, (deposit["user_id"],)).fetchone()

        new_balance = (
            balance_row["wallet_balance"]
            if balance_row
            else deposit["amount"]
        )

        con.commit()

        return deposit, new_balance, "approved"

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


def reject_wallet_deposit(deposit_id, admin_id):
    con = db()

    try:
        con.execute("BEGIN")

        deposit = con.execute("""
            SELECT *
            FROM wallet_deposits
            WHERE id=?
        """, (deposit_id,)).fetchone()

        if not deposit:
            con.rollback()
            return None, "not_found"

        cur = con.execute("""
            UPDATE wallet_deposits
            SET status='rejected',
                admin_id=?,
                reviewed_at=?
            WHERE id=?
              AND status='pending'
        """, (
            admin_id,
            datetime.now().isoformat(timespec="seconds"),
            deposit_id,
        ))

        if cur.rowcount != 1:
            con.rollback()
            return None, "already_processed"

        con.commit()

        return deposit, "rejected"

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()


# =========================================================
# WALLET PURCHASE / RENEWAL
# =========================================================

def pay_order_with_wallet(order_id, user_id):
    """پرداخت سفارش با کیف پول؛ عملیات اتمیک و ضد دوباره‌پرداخت."""
    con = db()
    try:
        con.execute("BEGIN")

        order = con.execute("""
            SELECT * FROM orders
            WHERE id=? AND user_id=?
        """, (order_id, user_id)).fetchone()

        if not order:
            con.rollback()
            return None, None, "not_found"

        if order["status"] == "paid":
            con.rollback()
            return order, None, "already_paid"

        if order["status"] == "receipt_pending":
            con.rollback()
            return order, None, "receipt_pending"

        user = con.execute(
            "SELECT wallet_balance FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()

        balance = int((user["wallet_balance"] if user else 0) or 0)

        if balance < order["amount"]:
            con.rollback()
            return order, balance, "insufficient"

        cur = con.execute("""
            UPDATE users
            SET wallet_balance = wallet_balance - ?
            WHERE user_id=? AND COALESCE(wallet_balance,0) >= ?
        """, (order["amount"], user_id, order["amount"]))

        if cur.rowcount != 1:
            con.rollback()
            return order, balance, "insufficient"

        cur = con.execute("""
            UPDATE orders
            SET status='paid'
            WHERE id=? AND user_id=? AND status IN ('pending','rejected')
        """, (order_id, user_id))

        if cur.rowcount != 1:
            con.rollback()
            return order, balance, "already_processed"

        con.execute("""
            INSERT INTO wallet_transactions
            (user_id, amount, type, reference_id, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            -order["amount"],
            "purchase",
            order_id,
            f"پرداخت سفارش #{order_id} از کیف پول",
            datetime.now().isoformat(timespec="seconds"),
        ))

        new_balance = balance - order["amount"]
        con.commit()
        return order, new_balance, "paid"
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# =========================================================
# HELPERS
# =========================================================

def format_price(number):
    return f"{int(number):,} تومان"


def jalali_date(iso_date):
    dt = datetime.fromisoformat(iso_date)
    j = jdatetime.datetime.fromgregorian(datetime=dt)

    return j.strftime("%Y/%m/%d %H:%M")


def back_button(target="home"):
    return InlineKeyboardButton(
        "🔙 بازگشت",
        callback_data=target
    )


# =========================================================
# MAIN USER PANEL
# =========================================================

def user_panel():
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "👤 پروفایل و کیف پول"
                ),
                KeyboardButton(
                    "🛒 فروشگاه اشتراک‌ها"
                ),
            ],
            [
                KeyboardButton(
                    "📡 سرویس های من"
                ),
                KeyboardButton(
                    "💰 شارژ کیف پول"
                ),
            ],
            [
                KeyboardButton(
                    "🎁 دعوت و دریافت رایگان"
                ),
            ],
            [
                KeyboardButton(
                    "📖 آموزش و راهنما"
                ),
                KeyboardButton(
                    "🛟 تماس با پشتیبانی"
                ),
            ],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=(
            "یک گزینه را انتخاب کنید..."
        )
    )


async def user_reply(update, context, *args, **kwargs):
    """ارسال پیام معمولی به کاربر؛ پیام‌های قبلی حذف نمی‌شوند."""
    return await update.message.reply_text(*args, **kwargs)


# =========================================================
# INLINE PLANS
# =========================================================

def plans_menu(prefix="plan"):
    buttons = []

    for key, plan in PLANS.items():
        buttons.append([
            InlineKeyboardButton(
                f"⚡ {plan['name']} • "
                f"{format_price(plan['price'])}",
                callback_data=f"{prefix}:{key}"
            )
        ])

    buttons.append([
        back_button("home")
    ])

    return InlineKeyboardMarkup(buttons)


# =========================================================
# ADMIN MENU
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
                "💰 شارژهای کیف پول",
                callback_data="admin_wallet"
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
# WELCOME
# =========================================================

WELCOME = """
🖥 <b>پنل کاربری</b>

━━━━━━━━━━━━━━━━━━

سلام 👋

به فروشگاه آنلاین سرویس خوش اومدی.

⚡ تحویل سریع
🔐 سرویس اختصاصی
📦 مدیریت سرویس‌ها
💳 خرید آسان
💰 کیف پول
💬 پشتیبانی

از منوی پایین انتخاب کن:
"""


# =========================================================
# SERVICES TEXT
# =========================================================

def services_text(user_id):
    services = get_services(user_id)

    if not services:
        return """
📡 <b>سرویس های من</b>

━━━━━━━━━━━━━━━━━━

📭 هنوز سرویسی برای حساب شما ثبت نشده.

برای خرید اولین سرویس روی
«🛒 فروشگاه اشتراک‌ها» بزنید.
"""

    lines = [
        "📡 <b>سرویس های من</b>",
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
            f"🏷 نام کانفیگ: <b>{escape(str(service['config_name'] or plan['name']))}</b>",
            f"🔑 کد سرویس: "
            f"<code>{escape(str(service['code']))}</code>",
            f"📊 وضعیت: {status}",
            f"📦 حجم: {service['total_gb']} GB",
            f"📅 انقضا: "
            f"{jalali_date(service['expires_at'])}",
            f"🛒 خرید: "
            f"{jalali_date(service['purchased_at'])}",
            "━━━━━━━━━━━━━━━━━━",
        ])

    return "\n".join(lines)


# =========================================================
# PROFILE
# =========================================================

def profile_text(user_id):
    user = get_user(user_id)
    services = get_services(user_id)

    if not user:
        return "❌ اطلاعات حساب پیدا نشد."

    active_services = [service for service in services if service["active"]]
    total_gb = sum(float(service["total_gb"] or 0) for service in services)

    invited_count = 0
    con = db()
    row = con.execute(
        "SELECT COUNT(*) AS c FROM users WHERE referred_by=?",
        (user_id,)
    ).fetchone()
    if row:
        invited_count = row["c"]
    con.close()

    balance = int(user["wallet_balance"] or 0)
    account_level = "همکار تجاری"

    if active_services:
        subscription_status = "فعال و آماده استفاده"
        subscription_lines = []
        now = datetime.now()

        for service in active_services:
            plan = PLANS.get(
                service["plan_key"],
                {"name": service["plan_key"]}
            )
            try:
                purchased_at = datetime.fromisoformat(service["purchased_at"])
                elapsed_days = max(0, (now - purchased_at).days)
            except Exception:
                elapsed_days = 0

            subscription_lines.extend([
                f"📦 <b>نوع اشتراک:</b> {escape(str(plan['name']))}",
                f"🏷 <b>نام کانفیگ:</b> {escape(str(service['config_name'] or plan['name']))}",
                f"📊 <b>حجم کانفیگ:</b> {service['total_gb']} GB",
                f"⏱ <b>مدت از زمان خرید:</b> {elapsed_days} روز",
                f"🛒 <b>تاریخ خرید:</b> {jalali_date(service['purchased_at'])}",
                f"📅 <b>تاریخ انقضا:</b> {jalali_date(service['expires_at'])}",
                "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
            ])
        subscription_details = "\n" + "\n".join(subscription_lines).rstrip("┄")
    else:
        subscription_status = "بدون اشتراک فعال"
        subscription_details = "\n📭 هنوز اشتراک فعالی برای حساب شما ثبت نشده است."

    return f"""
💳 <b>پروفایل کاربری شما</b>
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
🙂 نام: {escape(user['first_name'] or '—')}
🖥 شناسه کاربری: <code>{user_id}</code>
😀 سطح حساب: {account_level}
📊 ترافیک کل دریافتی: {total_gb:g} GB
💰 موجودی کیف پول: {format_price(balance)}
👥 تعداد دعوت‌شدگان: {invited_count} نفر
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
⚡️ <b>وضعیت اشتراک: {subscription_status}</b>
{subscription_details}
"""

# =========================================================
# PAYMENT TEXT / KEYBOARDS
# =========================================================

def card_payment_text(title, amount, extra=""):
    extra_block = f"\n{extra.strip()}\n" if extra.strip() else ""
    return f"""
<b>✦ Kaletek</b>

💳 <b>{title}</b>
━━━━━━━━━━━━━━━━━━

💰 <b>مبلغ پرداخت</b>
<b>{format_price(amount)}</b>
{extra_block}
💳 <b>اطلاعات پرداخت</b>

🏦 <b>شماره کارت:</b> <code>{escape(CARD_NUMBER)}</code>
👤 <b>به نام: {escape(CARD_HOLDER)}</b>

━━━━━━━━━━━━━━━━━━

📌 پس از واریز، تصویر واضح رسید را از طریق
دکمه «📤 ارسال رسید» ارسال کن.

⏳ درخواستت پس از بررسی ادمین نهایی می‌شود.
"""


def order_payment_keyboard(order_id, include_wallet=True):
    rows = []
    if include_wallet:
        rows.append([
            InlineKeyboardButton(
                "💰 پرداخت با کیف پول",
                callback_data=f"walletpay:{order_id}"
            )
        ])
    rows.append([
        InlineKeyboardButton(
            "💳 پرداخت با کارت و ارسال رسید",
            callback_data=f"pay:{order_id}"
        )
    ])
    rows.append([back_button("buy")])
    return InlineKeyboardMarkup(rows)


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    referred_by = None

    if context.args:
        try:
            candidate = int(context.args[0])

            if candidate != user.id:
                referred_by = candidate

        except ValueError:
            pass

    is_new_user = ensure_user(user, referred_by)

    if is_new_user and referred_by:
        rewarded = add_referral_reward(referred_by, user.id)
        if rewarded:
            new_username = (
                f"@{user.username}"
                if user.username
                else "ندارد"
            )
            try:
                await context.bot.send_message(
                    chat_id=referred_by,
                    text=f"""🎉 <b>دعوت جدید!</b>

━━━━━━━━━━━━━━━━━━

👤 کاربر جدید: <b>{escape(user.first_name or '—')}</b>
🔗 یوزرنیم: <b>{escape(new_username)}</b>

🎁 <b>پاداش شما: 3 GB</b>
📦 موجودی پاداش دعوت: <b>{get_user(referred_by)['referral_gb_balance'] or 0} GB</b>

یک کاربر جدید با لینک دعوتت وارد ربات شد.""",
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                pass

    # ادمین پنل مشتری نبیند
    if user.id == ADMIN_ID:
        context.user_data["awaiting_delivery"] = False

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
        return

    await update.message.reply_text(
        WELCOME,
        parse_mode=ParseMode.HTML,
        reply_markup=user_panel()
    )


# =========================================================
# ADMIN COMMAND
# =========================================================

async def admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )
        return

    context.user_data["awaiting_delivery"] = False
    context.user_data["awaiting_receipt_order_id"] = None
    context.user_data["awaiting_wallet_amount"] = False
    context.user_data["awaiting_wallet_receipt"] = False

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
        context.user_data["awaiting_delivery"] = False
        context.user_data["awaiting_receipt_order_id"] = None
        context.user_data["awaiting_wallet_amount"] = False
        context.user_data["awaiting_wallet_receipt"] = False

        # ادمین هیچ وقت پنل مشتری نبیند
        if user_id == ADMIN_ID:
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

        await q.edit_message_text(
            WELCOME,
            parse_mode=ParseMode.HTML
        )

        await q.message.reply_text(
            "🖥 پنل کاربری آماده است:",
            reply_markup=user_panel()
        )
        return

    # =====================================================
    # BUY
    # =====================================================

    if data == "buy":
        await q.edit_message_text(
            """
🛒 <b>فروشگاه اشتراک‌ها</b>

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

📦 حجم:
<b>{plan['gb']} GB</b>

⏱ اعتبار:
<b>{plan['days']} روز</b>

💰 مبلغ:
<b>{format_price(plan['price'])}</b>

━━━━━━━━━━━━━━━━━━

💰 اگر موجودی کیف پولت کافی باشد، می‌توانی مستقیم از کیف پول پرداخت کنی.

💳 یا می‌توانی با کارت پرداخت کنی و رسید بفرستی.
"""

        keyboard = order_payment_keyboard(order_id, include_wallet=True)

        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
        return

    # =====================================================
    # PAY ORDER WITH WALLET
    # =====================================================

    if data.startswith("walletpay:"):
        try:
            order_id = int(data.split(":", 1)[1])
        except ValueError:
            return

        order, new_balance, status = pay_order_with_wallet(
            order_id, user_id
        )

        if status == "not_found":
            await q.answer("❌ سفارش پیدا نشد.", show_alert=True)
            return

        if status == "already_paid":
            await q.answer("✅ این سفارش قبلاً پرداخت شده است.", show_alert=True)
            return

        if status == "receipt_pending":
            await q.answer("⏳ رسید این سفارش در انتظار بررسی است.", show_alert=True)
            return

        if status == "insufficient":
            current_balance = new_balance or 0
            await q.edit_message_text(
                f"""
⚠️ <b>موجودی کیف پول کافی نیست</b>

━━━━━━━━━━━━━━━━━━

💰 مبلغ سفارش: <b>{format_price(order['amount'])}</b>
💳 موجودی فعلی: <b>{format_price(current_balance)}</b>

🔸 برای پرداخت این سفارش، ابتدا کیف پولت را به اندازه کافی شارژ کن.

بعد از شارژ موفق، می‌توانی دوباره پرداخت را با کیف پول انجام دهی.
""",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 افزایش موجودی کیف پول", callback_data="wallet_topup")],
                    [InlineKeyboardButton("↩️ بازگشت به فروشگاه", callback_data="buy")]
                ])
            )
            return

        if status == "already_processed":
            await q.answer("⚠️ این سفارش قبلاً پردازش شده است.", show_alert=True)
            return

        plan = PLANS.get(order["plan_key"], {"name": order["plan_key"], "gb": 0, "days": 0})

        context.user_data["awaiting_config_name_order_id"] = None

        await q.edit_message_text(
            f"""
✅ <b>پرداخت با کیف پول با موفقیت انجام شد</b>

━━━━━━━━━━━━━━━━━━

🧾 سفارش: <code>#{order_id}</code>
💰 مبلغ پرداخت‌شده: <b>{format_price(order['amount'])}</b>
💳 موجودی جدید: <b>{format_price(new_balance)}</b>

⏳ پرداخت ثبت شد و سفارش برای تحویل کانفیگ در اختیار ادمین قرار گرفت.

📌 برای انتخاب نام کانفیگ، روی «ادامه» بزن.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ ادامه و انتخاب نام کانفیگ", callback_data=f"config_name_continue:{order_id}")],
                [back_button("home")]
            ])
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"""
💰 <b>پرداخت با کیف پول</b>

━━━━━━━━━━━━━━━━━━

🧾 سفارش: <code>#{order_id}</code>
👤 کاربر: <code>{user_id}</code>
⚡ پلن: <b>{escape(plan['name'])}</b>
💵 مبلغ: <b>{format_price(order['amount'])}</b>
💳 روش پرداخت: کیف پول

📌 سفارش پرداخت شده و منتظر تحویل دستی سرویس است.
""",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        return

    # =====================================================
    # OLD PAYMENT CALLBACK - KEEPING COMPATIBILITY
    # =====================================================

    if data.startswith("pay:"):
        order_id = data.split(":", 1)[1]

        con = db()
        order = con.execute(
            "SELECT * FROM orders WHERE id=?",
            (order_id,)
        ).fetchone()
        con.close()

        if not order or order["user_id"] != user_id:
            await q.answer(
                "❌ سفارش پیدا نشد.",
                show_alert=True
            )
            return

        await q.edit_message_text(
            card_payment_text(
                f"پرداخت سفارش #{order_id}",
                order["amount"]
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 ارسال رسید", callback_data=f"receipt:{order_id}")],
                [back_button("buy")]
            ])
        )
        return

    # =====================================================
    # ORDER RECEIPT
    # =====================================================

    if data.startswith("receipt:"):
        order_id = data.split(":", 1)[1]

        try:
            order_id_int = int(order_id)
        except ValueError:
            return

        con = db()
        order = con.execute(
            "SELECT * FROM orders WHERE id=?",
            (order_id_int,)
        ).fetchone()
        con.close()

        if not order or order["user_id"] != user_id:
            await q.answer(
                "❌ سفارش پیدا نشد.",
                show_alert=True
            )
            return

        if order["status"] == "paid":
            await q.answer(
                "✅ این سفارش قبلاً تأیید شده است.",
                show_alert=True
            )
            return

        if has_pending_order_receipt(order_id_int):
            await q.answer(
                "⏳ رسید این سفارش قبلاً ارسال شده و در انتظار بررسی است.",
                show_alert=True
            )
            return

        context.user_data["awaiting_delivery"] = False
        context.user_data["awaiting_wallet_amount"] = False
        context.user_data["awaiting_wallet_receipt"] = False
        context.user_data["awaiting_receipt_order_id"] = order_id_int

        await q.message.reply_text(
            f"""
📤 <b>ارسال رسید سفارش #{order_id_int}</b>

━━━━━━━━━━━━━━━━━━

💰 مبلغ سفارش:
<b>{format_price(order['amount'])}</b>

لطفاً <b>عکس رسید پرداخت</b> را همینجا ارسال کن.

بعد از ارسال، رسید برای ادمین فرستاده می‌شود و پس از تأیید،
مبلغ پرداختی به کیف پولت اضافه خواهد شد.
""",
            parse_mode=ParseMode.HTML
        )
        return

    # =====================================================
    # WALLET TOP-UP CALLBACK
    # =====================================================

    if data == "wallet_topup":
        context.user_data["awaiting_delivery"] = False
        context.user_data["awaiting_receipt_order_id"] = None
        context.user_data["awaiting_wallet_receipt"] = False
        context.user_data["awaiting_wallet_amount"] = True

        context.user_data["awaiting_wallet_amount"] = False

        await q.edit_message_text(
            """
<b>✦ Kaletek</b>

💳 <b>شارژ کیف پول</b>
━━━━━━━━━━━━━━━━━━

💰 مبلغ موردنظر برای شارژ کیف پول را به تومان وارد کن.

مثال:

<b>50,000 تومان</b>

━━━━━━━━━━━━━━━━━━

🔹 مبلغ را با عدد وارد کن.
🔹 حداقل مبلغ شارژ: <b>1,000 تومان</b>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ ادامه", callback_data="wallet_topup_continue")],
                [back_button("profile")]
            ])
        )
        return

    # =====================================================
    # WALLET TOP-UP CONTINUE
    # =====================================================

    if data == "wallet_topup_continue":
        context.user_data["awaiting_wallet_amount"] = True

        await q.edit_message_text(
            """
<b>✦ Kaletek</b>

💳 <b>مبلغ شارژ کیف پول</b>
━━━━━━━━━━━━━━━━━━

💰 مبلغ موردنظر را به تومان وارد کن.

مثال:
<b>50,000 تومان</b>

🔹 حداقل مبلغ شارژ: <b>1,000 تومان</b>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [back_button("profile")]
            ])
        )
        return

    # =====================================================
    # WALLET SEND RECEIPT
    # =====================================================

    if data == "wallet_send_receipt":
        amount = context.user_data.get("wallet_amount")

        if not amount:
            await q.answer(
                "❌ مبلغ شارژ پیدا نشد. دوباره اقدام کن.",
                show_alert=True
            )
            return

        if has_pending_wallet_deposit(user_id):
            context.user_data["wallet_amount"] = None

            await q.answer(
                "⏳ یک درخواست شارژ قبلی هنوز در انتظار بررسی است.",
                show_alert=True
            )
            return

        context.user_data["awaiting_receipt_order_id"] = None

        await q.message.reply_text(
            f"""
<b>✦ Kaletek</b>

📤 <b>ارسال رسید شارژ کیف پول</b>
━━━━━━━━━━━━━━━━━━

💰 <b>مبلغ شارژ</b>
{format_price(amount)}

📸 لطفاً تصویر واضح رسید پرداخت را همینجا ارسال کن.

🔎 بعد از دریافت، رسید برای بررسی ادمین ارسال می‌شود.
""",
            parse_mode=ParseMode.HTML
        )
        return

    # =====================================================
    # CONFIG NAME CONTINUE
    # =====================================================

    if data.startswith("config_name_continue:"):
        try:
            order_id = int(data.split(":", 1)[1])
        except ValueError:
            await q.answer("❌ سفارش نامعتبر است.", show_alert=True)
            return

        con = db()
        order = con.execute(
            "SELECT * FROM orders WHERE id=? AND user_id=?",
            (order_id, user_id)
        ).fetchone()
        con.close()

        if not order:
            await q.answer("❌ سفارش پیدا نشد.", show_alert=True)
            return

        context.user_data["awaiting_config_name_order_id"] = order_id

        await q.edit_message_text(
            """
🏷 <b>نام کانفیگت را انتخاب کن</b>

━━━━━━━━━━━━━━━━━━

یک نام کوتاه و دلخواه برای کانفیگت وارد کن.

مثال:
<b>ali1370</b>

📌 این نام در «📡 سرویس های من» و پیام‌های مربوط به کانفیگ نمایش داده می‌شود.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [back_button("home")]
            ])
        )
        return

    # =====================================================
    # RESEND CONFIG
    # =====================================================

    if data.startswith("resend_config:"):
        try:
            service_id = int(data.split(":", 1)[1])
        except ValueError:
            await q.answer("❌ سرویس نامعتبر است.", show_alert=True)
            return

        con = db()
        service = con.execute(
            "SELECT * FROM services WHERE id=? AND user_id=?",
            (service_id, user_id)
        ).fetchone()
        con.close()

        if not service:
            await q.answer("❌ سرویس پیدا نشد.", show_alert=True)
            return

        plan = PLANS.get(service["plan_key"], {"name": service["plan_key"]})
        await q.answer("📤 کانفیگ دوباره ارسال شد.")
        await q.message.reply_text(
            f"""
📤 <b>ارسال دوباره کانفیگ</b>
━━━━━━━━━━━━━━━━━━

🛰 <b>{escape(str(plan['name']))}</b>
🏷 نام کانفیگ: <b>{escape(str(service['config_name'] or plan['name']))}</b>
🔑 کد سرویس: <code>{escape(str(service['code']))}</code>

🔐 <b>کانفیگ</b>
<code>{escape(str(service['config']))}</code>
""",
            parse_mode=ParseMode.HTML
        )
        return

    # =====================================================
    # SERVICES
    # =====================================================

    if data == "services":
        services = get_services(user_id)
        rows = []
        if services:
            for service in services:
                rows.append([
                    InlineKeyboardButton(
                        f"📤 {service['config_name'] or service['code']}",
                        callback_data=f"resend_config:{service['id']}"
                    )
                ])
            rows.append([
                InlineKeyboardButton(
                    "🔄 تمدید سرویس",
                    callback_data="renew"
                )
            ])
        else:
            rows.append([
                InlineKeyboardButton(
                    "🛒 خرید سرویس",
                    callback_data="buy"
                )
            ])
        rows.append([back_button("home")])

        await q.edit_message_text(
            services_text(user_id),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows)
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

⚡ پلن:
{plan['name']}

📦 حجم:
{plan['gb']} GB

⏱ اعتبار:
{plan['days']} روز

💰 مبلغ:
<b>{format_price(plan['price'])}</b>

🧾 سفارش:
<code>#{order_id}</code>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💰 پرداخت با کیف پول",
                        callback_data=f"walletpay:{order_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💳 پرداخت با کارت و ارسال رسید",
                        callback_data=f"pay:{order_id}"
                    )
                ],
                [back_button("renew")]
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
                        "💰 شارژ کیف پول",
                        callback_data="wallet_topup"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📡 سرویس های من",
                        callback_data="services"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🎁 دعوت و دریافت رایگان",
                        callback_data="ref"
                    )
                ],
                [
                    back_button("home")
                ]
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
🎁 <b>دعوت و دریافت رایگان</b>

━━━━━━━━━━━━━━━━━━

لینک اختصاصی شما:

<code>{escape(link)}</code>

━━━━━━━━━━━━━━━━━━

این لینک را برای دوستانت ارسال کن.

هر کاربر جدیدی که با لینک تو وارد شود، ثبت می‌شود.

🎁 <b>پاداش دعوت</b>
به ازای هر دعوت موفق، <b>3 GB</b> حجم رایگان به پاداش دعوتت اضافه می‌شود.

📦 موجودی پاداش فعلی: <b>{get_user(user_id)['referral_gb_balance'] or 0} GB</b>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [back_button("home")]
            ])
        )
        return

    # =====================================================
    # GUIDE
    # =====================================================

    if data == "guide":
        await q.edit_message_text(
            """
📖 <b>آموزش و راهنما</b>

━━━━━━━━━━━━━━━━━━

🔹 بعد از خرید سرویس، کانفیگ برایت ارسال می‌شود.

🔹 کانفیگ را کپی کن.

🔹 آن را داخل برنامه سازگار با نوع کانفیگ وارد کن.

🔹 سپس اتصال را فعال کن.

━━━━━━━━━━━━━━━━━━

اگر مشکلی داشتی، از بخش
«🛟 تماس با پشتیبانی» استفاده کن.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🛟 تماس با پشتیبانی",
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
        if (
            SUPPORT_STICKER_ID
            and SUPPORT_STICKER_ID != "PASTE_STICKER_FILE_ID_HERE"
        ):
            try:
                await q.message.reply_sticker(
                    SUPPORT_STICKER_ID
                )
            except Exception:
                pass

        await q.edit_message_text(
            """
🛟 <b>تماس با پشتیبانی</b>

━━━━━━━━━━━━━━━━━━

اگر در خرید یا سرویس مشکلی داری،
از دکمه زیر با پشتیبانی تماس بگیر.

━━━━━━━━━━━━━━━━━━
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💬 تماس با پشتیبانی",
                        url=(
                            "https://t.me/"
                            + SUPPORT_USERNAME.lstrip("@")
                        )
                    )
                ],
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
        context.user_data["awaiting_delivery"] = False

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
            """
            SELECT COUNT(*) c
            FROM services
            WHERE active=1
            """
        ).fetchone()["c"]

        orders = con.execute(
            "SELECT COUNT(*) c FROM orders"
        ).fetchone()["c"]

        pending = con.execute(
            """
            SELECT COUNT(*) c
            FROM orders
            WHERE status IN ('pending', 'receipt_pending')
            """
        ).fetchone()["c"]

        paid = con.execute(
            "SELECT COUNT(*) c FROM orders WHERE status='paid'"
        ).fetchone()["c"]

        pending_wallet = con.execute(
            """
            SELECT COUNT(*) c
            FROM wallet_deposits
            WHERE status='pending'
            """
        ).fetchone()["c"]

        total_wallet = con.execute(
            """
            SELECT COALESCE(SUM(wallet_balance), 0) total
            FROM users
            """
        ).fetchone()["total"]

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

⏳ در انتظار رسید سفارش:
<b>{pending}</b>

💰 درخواست شارژ کیف پول:
<b>{pending_wallet}</b>

💵 مجموع موجودی کیف پول کاربران:
<b>{format_price(total_wallet)}</b>
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
                    f"📌 وضعیت: {escape(row['status'])}\n"
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
            SELECT
                user_id,
                username,
                first_name,
                wallet_balance,
                created_at
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
                f"👤 {escape(row['first_name'] or 'بدون نام')}\n"
                f"🆔 <code>{row['user_id']}</code>\n"
                f"🔗 {escape(username)}\n"
                f"💰 {format_price(row['wallet_balance'] or 0)}\n"
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
                f"🔑 <code>{escape(str(row['code']))}</code>\n"
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
    # ADMIN WALLET DEPOSITS
    # =====================================================

    if data == "admin_wallet":
        con = db()

        rows = con.execute("""
            SELECT
                id,
                user_id,
                amount,
                status,
                created_at
            FROM wallet_deposits
            ORDER BY id DESC
            LIMIT 15
        """).fetchall()

        con.close()

        if not rows:
            text = """
💰 <b>شارژهای کیف پول</b>

━━━━━━━━━━━━━━━━━━

📭 هنوز درخواست شارژی ثبت نشده.
"""
        else:
            lines = [
                "💰 <b>آخرین شارژهای کیف پول</b>",
                "━━━━━━━━━━━━━━━━━━"
            ]

            for row in rows:
                lines.append(
                    f"💳 <b>#{row['id']}</b>\n"
                    f"👤 <code>{row['user_id']}</code>\n"
                    f"💵 {format_price(row['amount'])}\n"
                    f"📌 {escape(row['status'])}\n"
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
    # ADMIN DELIVERY
    # =====================================================

    if data == "admin_deliver":
        context.user_data["awaiting_delivery"] = True
        context.user_data["awaiting_receipt_order_id"] = None
        context.user_data["awaiting_wallet_amount"] = False
        context.user_data["awaiting_wallet_receipt"] = False

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

    # =====================================================
    # ADMIN APPROVE ORDER RECEIPT
    # =====================================================

    if data.startswith("receipt_approve:"):
        try:
            receipt_id = int(
                data.split(":", 1)[1]
            )
        except ValueError:
            return

        receipt, new_balance, status = approve_payment_receipt(
            receipt_id,
            ADMIN_ID
        )

        if status == "not_found":
            await q.edit_message_caption(
                caption="❌ رسید پیدا نشد."
            )
            return

        if status == "already_processed":
            await q.edit_message_caption(
                caption=(
                    "⚠️ این رسید قبلاً بررسی شده است.\n"
                    "از شارژ دوباره کیف پول جلوگیری شد."
                )
            )
            return

        await q.edit_message_caption(
            caption=(
                "✅ <b>رسید تأیید شد</b>\n\n"
                f"🧾 سفارش: #{receipt['order_id']}\n"
                f"👤 کاربر: <code>{receipt['user_id']}</code>\n"
                f"💰 مبلغ: {format_price(receipt['amount'])}\n"
                f"💳 موجودی جدید: {format_price(new_balance)}"
            ),
            parse_mode=ParseMode.HTML
        )

        try:
            await context.bot.send_message(
                chat_id=receipt["user_id"],
                text=f"""
✦ <b>Kaletek</b>

✅ <b>رسید پرداخت تأیید شد</b>
━━━━━━━━━━━━━━━━━━

🧾 سفارش: <code>#{receipt['order_id']}</code>
💰 مبلغ تأییدشده: <b>{format_price(receipt['amount'])}</b>
💳 موجودی کیف پول: <b>{format_price(new_balance)}</b>

📌 حالا برای انتخاب نام کانفیگ، روی «ادامه» بزن.
""",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("▶️ ادامه و انتخاب نام کانفیگ", callback_data=f"config_name_continue:{receipt['order_id']}")]
                ])
            )
        except Exception:
            pass

        return

    # =====================================================
    # ADMIN REJECT ORDER RECEIPT
    # =====================================================

    if data.startswith("receipt_reject:"):
        try:
            receipt_id = int(
                data.split(":", 1)[1]
            )
        except ValueError:
            return

        receipt, status = reject_payment_receipt(
            receipt_id,
            ADMIN_ID
        )

        if status == "not_found":
            await q.edit_message_caption(
                caption="❌ رسید پیدا نشد."
            )
            return

        if status == "already_processed":
            await q.edit_message_caption(
                caption="⚠️ این رسید قبلاً بررسی شده است."
            )
            return

        await q.edit_message_caption(
            caption=(
                "❌ <b>رسید رد شد</b>\n\n"
                f"🧾 سفارش: #{receipt['order_id']}\n"
                f"👤 کاربر: <code>{receipt['user_id']}</code>\n"
                f"💰 مبلغ: {format_price(receipt['amount'])}"
            ),
            parse_mode=ParseMode.HTML
        )

        try:
            await context.bot.send_message(
                chat_id=receipt["user_id"],
                text=f"""
❌ <b>رسید پرداخت تأیید نشد</b>

━━━━━━━━━━━━━━━━━━

🧾 سفارش:
<code>#{receipt['order_id']}</code>

💰 مبلغ:
<b>{format_price(receipt['amount'])}</b>

رسید توسط ادمین تأیید نشد.
در صورت اشتباه، لطفاً رسید صحیح را دوباره ارسال کن.
""",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "📤 ارسال مجدد رسید",
                            callback_data=f"receipt:{receipt['order_id']}"
                        )
                    ]
                ])
            )
        except Exception:
            pass

        return

    # =====================================================
    # ADMIN APPROVE WALLET DEPOSIT
    # =====================================================

    if data.startswith("wallet_approve:"):
        try:
            deposit_id = int(
                data.split(":", 1)[1]
            )
        except ValueError:
            return

        deposit, new_balance, status = approve_wallet_deposit(
            deposit_id,
            ADMIN_ID
        )

        if status == "not_found":
            await q.edit_message_caption(
                caption="❌ درخواست شارژ پیدا نشد."
            )
            return

        if status == "already_processed":
            await q.edit_message_caption(
                caption=(
                    "⚠️ این درخواست قبلاً بررسی شده است.\n"
                    "از شارژ دوباره کیف پول جلوگیری شد."
                )
            )
            return

        await q.edit_message_caption(
            caption=(
                "✅ <b>شارژ کیف پول تأیید شد</b>\n\n"
                f"💳 درخواست: #{deposit['id']}\n"
                f"👤 کاربر: <code>{deposit['user_id']}</code>\n"
                f"💰 مبلغ: {format_price(deposit['amount'])}\n"
                f"💳 موجودی جدید: {format_price(new_balance)}"
            ),
            parse_mode=ParseMode.HTML
        )

        try:
            await context.bot.send_message(
                chat_id=deposit["user_id"],
                text=f"""
<b>✦ Kaletek</b>

✅ <b>شارژ کیف پول با موفقیت تأیید شد</b>
━━━━━━━━━━━━━━━━━━

💰 <b>مبلغ اضافه‌شده</b>
{format_price(deposit['amount'])}

💳 <b>موجودی جدید کیف پول</b>
{format_price(new_balance)}

🎉 مبلغ با موفقیت به کیف پولت اضافه شد و اکنون قابل استفاده است.
""",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

        return

    # =====================================================
    # ADMIN REJECT WALLET DEPOSIT
    # =====================================================

    if data.startswith("wallet_reject:"):
        try:
            deposit_id = int(
                data.split(":", 1)[1]
            )
        except ValueError:
            return

        deposit, status = reject_wallet_deposit(
            deposit_id,
            ADMIN_ID
        )

        if status == "not_found":
            await q.edit_message_caption(
                caption="❌ درخواست شارژ پیدا نشد."
            )
            return

        if status == "already_processed":
            await q.edit_message_caption(
                caption="⚠️ این درخواست قبلاً بررسی شده است."
            )
            return

        await q.edit_message_caption(
            caption=(
                "❌ <b>درخواست شارژ رد شد</b>\n\n"
                f"💳 درخواست: #{deposit['id']}\n"
                f"👤 کاربر: <code>{deposit['user_id']}</code>\n"
                f"💰 مبلغ: {format_price(deposit['amount'])}"
            ),
            parse_mode=ParseMode.HTML
        )

        try:
            await context.bot.send_message(
                chat_id=deposit["user_id"],
                text=f"""
❌ <b>شارژ کیف پول تأیید نشد</b>

━━━━━━━━━━━━━━━━━━

💰 مبلغ:
<b>{format_price(deposit['amount'])}</b>

رسید پرداخت توسط ادمین تأیید نشد.
اگر اشتباهی رخ داده، می‌توانی دوباره درخواست شارژ ثبت کنی.
""",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

        return


# =========================================================
# PHOTO / RECEIPT HANDLER
# =========================================================

async def photo_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    # =====================================================
    # ADMIN RECEIPT DOES NOT ENTER USER FLOW
    # =====================================================

    if user_id == ADMIN_ID:
        return

    ensure_user(update.effective_user)

    # =====================================================
    # ORDER RECEIPT
    # =====================================================

    order_id = context.user_data.get(
        "awaiting_receipt_order_id"
    )

    if order_id:
        con = db()

        order = con.execute(
            "SELECT * FROM orders WHERE id=?",
            (order_id,)
        ).fetchone()

        con.close()

        if not order or order["user_id"] != user_id:
            context.user_data["awaiting_receipt_order_id"] = None

            await update.message.reply_text(
                "❌ سفارش پیدا نشد."
            )
            return

        if order["status"] == "paid":
            context.user_data["awaiting_receipt_order_id"] = None

            await update.message.reply_text(
                "✅ این سفارش قبلاً پرداخت و تأیید شده است."
            )
            return

        if has_pending_order_receipt(order_id):
            context.user_data["awaiting_receipt_order_id"] = None

            await update.message.reply_text(
                "⏳ رسید این سفارش قبلاً ارسال شده و در انتظار بررسی ادمین است."
            )
            return

        photo = update.message.photo[-1]
        file_id = photo.file_id

        receipt_id = create_payment_receipt(
            order_id,
            user_id,
            order["amount"],
            file_id
        )

        context.user_data["awaiting_receipt_order_id"] = None
        context.user_data["awaiting_config_name_order_id"] = order_id

        await update.message.reply_text(
            f"""
✅ <b>رسید دریافت شد</b>

━━━━━━━━━━━━━━━━━━

🧾 سفارش:
<code>#{order_id}</code>

💰 مبلغ:
<b>{format_price(order['amount'])}</b>

⏳ رسید برای بررسی ادمین ارسال شد.

📌 بعد از تأیید رسید، نام کانفیگت را انتخاب کن.

برای ادامه روی دکمه زیر بزن.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("▶️ ادامه و انتخاب نام کانفیگ", callback_data=f"config_name_continue:{order_id}")]
            ])
        )

        plan = PLANS.get(
            order["plan_key"],
            {"name": order["plan_key"]}
        )

        username = (
            f"@{update.effective_user.username}"
            if update.effective_user.username
            else "ندارد"
        )

        admin_caption = f"""
🧾 <b>رسید پرداخت سفارش جدید</b>

━━━━━━━━━━━━━━━━━━

🔢 Receipt ID:
<code>{receipt_id}</code>

🧾 سفارش:
<code>#{order_id}</code>

👤 نام:
{escape(update.effective_user.first_name or '—')}

🔗 یوزرنیم:
{escape(username)}

🆔 User ID:
<code>{user_id}</code>

⚡ پلن:
<b>{escape(plan['name'])}</b>

💰 مبلغ:
<b>{format_price(order['amount'])}</b>

━━━━━━━━━━━━━━━━━━

برای تأیید یا رد رسید از دکمه‌های زیر استفاده کن.
"""

        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=admin_caption,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأیید و شارژ کیف پول",
                            callback_data=f"receipt_approve:{receipt_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ رد رسید",
                            callback_data=f"receipt_reject:{receipt_id}"
                        )
                    ],
                ])
            )
        except Exception as e:
            await update.message.reply_text(
                f"""
⚠️ رسید ثبت شد اما ارسال آن برای ادمین با مشکل مواجه شد.

خطا:
<code>{escape(str(e))}</code>
""",
                parse_mode=ParseMode.HTML
            )

        return

    # =====================================================
    # WALLET RECEIPT
    # =====================================================

    wallet_amount = context.user_data.get(
        "wallet_amount"
    )

    if wallet_amount:
        amount = int(wallet_amount)

        if amount <= 0:
            context.user_data["wallet_amount"] = None

            await update.message.reply_text(
                "❌ مبلغ نامعتبر است. دوباره از بخش شارژ کیف پول اقدام کن."
            )
            return

        if has_pending_wallet_deposit(user_id):
            context.user_data["wallet_amount"] = None

            await update.message.reply_text(
                "⏳ یک درخواست شارژ قبلی هنوز در انتظار بررسی ادمین است."
            )
            return

        photo = update.message.photo[-1]
        file_id = photo.file_id

        deposit_id = create_wallet_deposit(
            user_id,
            amount,
            file_id
        )

        context.user_data["wallet_amount"] = None

        await update.message.reply_text(
            f"""
✅ <b>رسید شارژ کیف پول دریافت شد</b>

━━━━━━━━━━━━━━━━━━

💰 مبلغ درخواست:
<b>{format_price(amount)}</b>

⏳ رسید برای بررسی ادمین ارسال شد.

بعد از تأیید، دقیقاً همین مبلغ به کیف پولت اضافه می‌شود.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=user_panel()
        )

        username = (
            f"@{update.effective_user.username}"
            if update.effective_user.username
            else "ندارد"
        )

        admin_caption = f"""
💰 <b>درخواست شارژ کیف پول</b>

━━━━━━━━━━━━━━━━━━

🔢 Deposit ID:
<code>{deposit_id}</code>

👤 نام:
{escape(update.effective_user.first_name or '—')}

🔗 یوزرنیم:
{escape(username)}

🆔 User ID:
<code>{user_id}</code>

💵 مبلغ درخواستی:
<b>{format_price(amount)}</b>

━━━━━━━━━━━━━━━━━━

با تأیید، دقیقاً همین مبلغ به کیف پول کاربر اضافه می‌شود.
"""

        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=admin_caption,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "✅ تأیید و شارژ کیف پول",
                            callback_data=f"wallet_approve:{deposit_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ رد رسید",
                            callback_data=f"wallet_reject:{deposit_id}"
                        )
                    ],
                ])
            )
        except Exception as e:
            await update.message.reply_text(
                f"""
⚠️ درخواست ثبت شد اما ارسال آن برای ادمین با مشکل مواجه شد.

خطا:
<code>{escape(str(e))}</code>
""",
                parse_mode=ParseMode.HTML
            )

        return


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # =====================================================
    # ADMIN DELIVERY MODE
    # =====================================================

    if (
        user_id == ADMIN_ID
        and context.user_data.get("awaiting_delivery")
    ):
        raw = text
        parts = raw.split("|", 2)

        if len(parts) != 3:
            await update.message.reply_text(
                """
❌ فرمت اشتباه است.

فرمت صحیح:

<code>USER_ID|PLAN_KEY|CONFIG</code>

مثال:

<code>123456789|p50|vless://...</code>
""",
                parse_mode=ParseMode.HTML
            )
            return

        try:
            target_user_id = int(
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

        config_name = get_order_config_name(target_user_id, plan_key) or PLANS[plan_key]["name"]

        service_id, code = create_service(
            target_user_id,
            plan_key,
            config,
            config_name=config_name
        )

        context.user_data["awaiting_delivery"] = False

        plan = PLANS[plan_key]

        await update.message.reply_text(
            f"""
✅ <b>سرویس ساخته شد</b>

━━━━━━━━━━━━━━━━━━

👤 کاربر:
<code>{target_user_id}</code>

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
                chat_id=target_user_id,
                text=f"""
🎉 <b>سرویس شما آماده است</b>
━━━━━━━━━━━━━━━━━━

🛰 <b>{plan['name']}</b>  •  📦 <b>{plan['gb']} GB</b>  •  ⏱ <b>{plan['days']} روز</b>
🏷 نام کانفیگ: <b>{escape(str(config_name))}</b>
🔑 کد سرویس: <code>{code}</code>

🔐 <b>کانفیگ</b>
<code>{escape(config)}</code>

━━━━━━━━━━━━━━━━━━
📡 برای مشاهده یا ارسال دوباره کانفیگ، وارد «سرویس های من» شو.
""",
                parse_mode=ParseMode.HTML
            )

        except Exception as e:
            await update.message.reply_text(
                f"""
⚠️ سرویس ساخته شد،
اما ارسال به کاربر ناموفق بود.

خطا:

<code>{escape(str(e))}</code>
""",
                parse_mode=ParseMode.HTML
            )

        return

    # =====================================================
    # ADMIN SHOULD NOT USE USER PANEL
    # =====================================================

    if user_id == ADMIN_ID:
        return

    ensure_user(update.effective_user)

    # =====================================================
    # CONFIG NAME INPUT
    # =====================================================

    if context.user_data.get("awaiting_config_name_order_id"):
        order_id = context.user_data.get("awaiting_config_name_order_id")
        config_name = text.strip()

        if len(config_name) < 2:
            await user_reply(update, context, "❌ نام کانفیگ باید حداقل ۲ کاراکتر باشد.")
            return

        if len(config_name) > 40:
            await user_reply(update, context, "❌ نام کانفیگ حداکثر ۴۰ کاراکتر باشد.")
            return

        if not set_order_config_name(order_id, user_id, config_name):
            context.user_data["awaiting_config_name_order_id"] = None
            await user_reply(update, context, "❌ سفارش پیدا نشد. لطفاً با پشتیبانی تماس بگیر.")
            return

        con = db()
        order_row = con.execute(
            "SELECT plan_key, created_at FROM orders WHERE id=? AND user_id=?",
            (order_id, user_id)
        ).fetchone()
        if order_row:
            con.execute(
                """UPDATE services SET config_name=?
                   WHERE id=(SELECT id FROM services
                             WHERE user_id=? AND plan_key=?
                               AND purchased_at >= ?
                             ORDER BY id DESC LIMIT 1)""",
                (config_name, user_id, order_row["plan_key"], order_row["created_at"])
            )
            con.commit()
        con.close()

        context.user_data["awaiting_config_name_order_id"] = None
        await user_reply(
            update,
            context,
            f"🏷 <b>نام کانفیگ ثبت شد</b>\n\nنام انتخابی: <b>{escape(config_name)}</b>\n\nپس از تحویل سرویس، همین نام کنار کانفیگت نمایش داده می‌شود.",
            parse_mode=ParseMode.HTML,
            reply_markup=user_panel()
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🏷 <b>نام کانفیگ کاربر ثبت شد</b>\n\n🧾 سفارش: <code>#{order_id}</code>\n👤 کاربر: <code>{user_id}</code>\n🔗 یوزرنیم: <b>{escape('@' + update.effective_user.username if update.effective_user.username else 'ندارد')}</b>\n🏷 نام کانفیگ: <b>{escape(config_name)}</b>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        return

    # =====================================================
    # WALLET AMOUNT INPUT
    # =====================================================

    if context.user_data.get("awaiting_wallet_amount"):
        normalized = (
            text
            .replace(",", "")
            .replace("تومان", "")
            .replace(" ", "")
        )

        if not normalized.isdigit():
            await user_reply(update, context, 
                """
❌ مبلغ نامعتبر است.

لطفاً فقط عدد وارد کن.

مثال:
<code>50,000 تومان</code>
""",
                parse_mode=ParseMode.HTML
            )
            return

        amount = int(normalized)

        if amount < 1000:
            await user_reply(update, context, 
                "❌ حداقل مبلغ شارژ 1,000 تومان است."
            )
            return

        if amount > 1_000_000_000:
            await user_reply(update, context, 
                "❌ مبلغ واردشده بیش از حد مجاز است."
            )
            return

        if has_pending_wallet_deposit(user_id):
            context.user_data["awaiting_wallet_amount"] = False

            await user_reply(update, context, 
                """
⏳ یک درخواست شارژ قبلی هنوز در انتظار بررسی ادمین است.

لطفاً تا تعیین تکلیف درخواست قبلی صبر کن.
""",
                reply_markup=user_panel()
            )
            return

        context.user_data["awaiting_wallet_amount"] = False
        context.user_data["wallet_amount"] = amount

        await user_reply(update, context, 
            card_payment_text(
                "شارژ کیف پول",
                amount,
                extra=(
                    "💰 مبلغی که وارد کردی ثبت شد."
                )
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📤 ارسال رسید",
                        callback_data="wallet_send_receipt"
                    )
                ],
                [
                    back_button("profile")
                ]
            ])
        )
        return

    # =====================================================
    # PROFILE
    # =====================================================

    if text == "👤 پروفایل و کیف پول":
        await user_reply(update, context, 
            profile_text(user_id),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💰 شارژ کیف پول",
                        callback_data="wallet_topup"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📡 سرویس های من",
                        callback_data="services"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🎁 دعوت و دریافت رایگان",
                        callback_data="ref"
                    )
                ],
                [
                    back_button("home")
                ]
            ])
        )
        return

    # =====================================================
    # DIRECT WALLET TOP-UP BUTTON
    # =====================================================

    if text == "💰 شارژ کیف پول":
        context.user_data["awaiting_wallet_amount"] = True
        context.user_data["wallet_amount"] = None
        context.user_data["awaiting_receipt_order_id"] = None

        await user_reply(update, context, 
            """
<b>✦ Kaletek</b>

💳 <b>شارژ کیف پول</b>
━━━━━━━━━━━━━━━━━━

💰 مبلغ موردنظر برای شارژ کیف پول را به تومان وارد کن.

مثال:

<b>50,000 تومان</b>

━━━━━━━━━━━━━━━━━━

🔹 مبلغ را با عدد وارد کن.
🔹 حداقل مبلغ شارژ: <b>1,000 تومان</b>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [back_button("profile")]
            ])
        )
        return

    # =====================================================
    # STORE
    # =====================================================

    if text == "🛒 فروشگاه اشتراک‌ها":
        await user_reply(update, context, 
            """
🛒 <b>فروشگاه اشتراک‌ها</b>

━━━━━━━━━━━━━━━━━━

پلن موردنظر خودت را انتخاب کن:
""",
            parse_mode=ParseMode.HTML,
            reply_markup=plans_menu("plan")
        )
        return

    # =====================================================
    # SERVICES
    # =====================================================

    if text == "📡 سرویس های من":
        services = get_services(user_id)
        rows = []
        if services:
            for service in services:
                rows.append([
                    InlineKeyboardButton(
                        f"📤 {service['config_name'] or service['code']}",
                        callback_data=f"resend_config:{service['id']}"
                    )
                ])
            rows.append([
                InlineKeyboardButton(
                    "🔄 تمدید سرویس",
                    callback_data="renew"
                )
            ])
        else:
            rows.append([
                InlineKeyboardButton(
                    "🛒 خرید سرویس",
                    callback_data="buy"
                )
            ])
        rows.append([back_button("home")])

        await user_reply(update, context, 
            services_text(user_id),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # =====================================================
    # REFERRAL
    # =====================================================

    if text == "🎁 دعوت و دریافت رایگان":
        bot_username = context.bot.username

        link = (
            f"https://t.me/"
            f"{bot_username}"
            f"?start={user_id}"
        )

        await user_reply(update, context, 
            f"""
🎁 <b>دعوت و دریافت رایگان</b>

━━━━━━━━━━━━━━━━━━

لینک اختصاصی شما:

<code>{escape(link)}</code>

━━━━━━━━━━━━━━━━━━

این لینک را برای دوستانت ارسال کن.

هر کاربر جدیدی که با لینک تو وارد شود، ثبت می‌شود.

🎁 <b>پاداش دعوت</b>
به ازای هر دعوت موفق، <b>3 GB</b> حجم رایگان به پاداش دعوتت اضافه می‌شود.

📦 موجودی پاداش فعلی: <b>{get_user(user_id)['referral_gb_balance'] or 0} GB</b>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=user_panel()
        )
        return

    # =====================================================
    # GUIDE
    # =====================================================

    if text == "📖 آموزش و راهنما":
        await user_reply(update, context, 
            """
📚 <b>راهنمای استفاده از سرویس</b>

┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄

🛒 <b>۱. خرید سرویس</b>
از بخش «فروشگاه اشتراک‌ها» پلن موردنظرت را انتخاب کن.
می‌توانی هزینه را از کیف پول پرداخت کنی یا با کارت و ارسال رسید پرداخت کنی.

💰 <b>۲. شارژ کیف پول</b>
از «پروفایل و کیف پول» مبلغ دلخواهت را وارد کن، واریز را انجام بده و تصویر رسید را ارسال کن. پس از تأیید ادمین، مبلغ به موجودی کیف پول اضافه می‌شود.

🎁 <b>۳. دعوت و دریافت رایگان</b>
لینک دعوت اختصاصی خودت را از بخش «🎁 دعوت و دریافت رایگان» بردار و برای دوستانت بفرست.
به ازای هر کاربر جدیدی که با لینک تو وارد ربات شود، <b>3 GB</b> پاداش رایگان برایت ثبت می‌شود.

📡 <b>۴. دریافت کانفیگ</b>
بعد از تأیید پرداخت و تحویل سرویس توسط ادمین، کانفیگ برایت ارسال می‌شود و در «سرویس های من» هم قابل مشاهده است.

🔄 <b>۵. تمدید</b>
اگر سرویس فعال داشته باشی، از بخش «سرویس های من» می‌توانی آن را تمدید کنی و هزینه را از کیف پول پرداخت کنی یا رسید ارسال کنی.

🔐 <b>۶. اتصال</b>
کانفیگ را کپی کن و داخل برنامه سازگار با نوع کانفیگ وارد کن، سپس اتصال را فعال کن.

🛟 <b>مشکل داشتی؟</b>
از بخش «تماس با پشتیبانی» با پشتیبانی در ارتباط باش.

┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
✨ <b>اگر در هر مرحله مشکلی داشتی، شماره سفارش یا کد سرویس را همراه پیامت ارسال کن.</b>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=user_panel()
        )
        return

    # =====================================================
    # SUPPORT
    # =====================================================

    if text == "🛟 تماس با پشتیبانی":
        if (
            SUPPORT_STICKER_ID
            and SUPPORT_STICKER_ID != "PASTE_STICKER_FILE_ID_HERE"
        ):
            try:
                await update.message.reply_sticker(
                    SUPPORT_STICKER_ID
                )
            except Exception:
                pass

        await user_reply(update, context, 
            """
🛟 <b>تماس با پشتیبانی</b>

━━━━━━━━━━━━━━━━━━

اگر در خرید یا سرویس مشکلی داری،
از دکمه زیر با پشتیبانی تماس بگیر.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💬 تماس با پشتیبانی",
                        url=(
                            "https://t.me/"
                            + SUPPORT_USERNAME.lstrip("@")
                        )
                    )
                ]
            ])
        )
        return


    # =====================================================
    # ADMIN SHOULD NOT USE USER PANEL
    # =====================================================

    if user_id == ADMIN_ID:
        return

    ensure_user(update.effective_user)

    # =====================================================
    # CONFIG NAME INPUT
    # =====================================================

    if context.user_data.get("awaiting_config_name_order_id"):
        order_id = context.user_data.get("awaiting_config_name_order_id")
        config_name = text.strip()

        if len(config_name) < 2:
            await user_reply(update, context, "❌ نام کانفیگ باید حداقل ۲ کاراکتر باشد.")
            return

        if len(config_name) > 40:
            await user_reply(update, context, "❌ نام کانفیگ حداکثر ۴۰ کاراکتر باشد.")
            return

        if not set_order_config_name(order_id, user_id, config_name):
            context.user_data["awaiting_config_name_order_id"] = None
            await user_reply(update, context, "❌ سفارش پیدا نشد. لطفاً با پشتیبانی تماس بگیر.")
            return

        con = db()
        order_row = con.execute(
            "SELECT plan_key, created_at FROM orders WHERE id=? AND user_id=?",
            (order_id, user_id)
        ).fetchone()
        if order_row:
            con.execute(
                """UPDATE services SET config_name=?
                   WHERE id=(SELECT id FROM services
                             WHERE user_id=? AND plan_key=?
                               AND purchased_at >= ?
                             ORDER BY id DESC LIMIT 1)""",
                (config_name, user_id, order_row["plan_key"], order_row["created_at"])
            )
            con.commit()
        con.close()

        context.user_data["awaiting_config_name_order_id"] = None
        await user_reply(
            update,
            context,
            f"🏷 <b>نام کانفیگ ثبت شد</b>\n\nنام انتخابی: <b>{escape(config_name)}</b>\n\nپس از تحویل سرویس، همین نام کنار کانفیگت نمایش داده می‌شود.",
            parse_mode=ParseMode.HTML,
            reply_markup=user_panel()
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🏷 <b>نام کانفیگ کاربر ثبت شد</b>\n\n🧾 سفارش: <code>#{order_id}</code>\n👤 کاربر: <code>{user_id}</code>\n🔗 یوزرنیم: <b>{escape('@' + update.effective_user.username if update.effective_user.username else 'ندارد')}</b>\n🏷 نام کانفیگ: <b>{escape(config_name)}</b>",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass
        return

    # =====================================================
    # WALLET AMOUNT INPUT
    # =====================================================

    if context.user_data.get("awaiting_wallet_amount"):
        normalized = (
            text
            .replace(",", "")
            .replace("تومان", "")
            .replace(" ", "")
        )

        if not normalized.isdigit():
            await user_reply(update, context, 
                """
❌ مبلغ نامعتبر است.

لطفاً فقط عدد وارد کن.

مثال:
<code>50,000 تومان</code>
""",
                parse_mode=ParseMode.HTML
            )
            return

        amount = int(normalized)

        if amount < 1000:
            await user_reply(update, context, 
                "❌ حداقل مبلغ شارژ 1,000 تومان است."
            )
            return

        if amount > 1_000_000_000:
            await user_reply(update, context, 
                "❌ مبلغ واردشده بیش از حد مجاز است."
            )
            return

        if has_pending_wallet_deposit(user_id):
            context.user_data["awaiting_wallet_amount"] = False

            await user_reply(update, context, 
                """
⏳ یک درخواست شارژ قبلی هنوز در انتظار بررسی ادمین است.

لطفاً تا تعیین تکلیف درخواست قبلی صبر کن.
""",
                reply_markup=user_panel()
            )
            return

        context.user_data["awaiting_wallet_amount"] = False
        context.user_data["wallet_amount"] = amount

        await user_reply(update, context, 
            card_payment_text(
                "شارژ کیف پول",
                amount,
                extra=(
                    "💰 مبلغی که وارد کردی ثبت شد."
                )
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📤 ارسال رسید",
                        callback_data="wallet_send_receipt"
                    )
                ],
                [
                    back_button("profile")
                ]
            ])
        )
        return

    # =====================================================
    # PROFILE
    # =====================================================

    if text == "👤 پروفایل و کیف پول":
        await user_reply(update, context, 
            profile_text(user_id),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💰 شارژ کیف پول",
                        callback_data="wallet_topup"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📡 سرویس های من",
                        callback_data="services"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🎁 دعوت و دریافت رایگان",
                        callback_data="ref"
                    )
                ],
                [
                    back_button("home")
                ]
            ])
        )
        return

    # =====================================================
    # DIRECT WALLET TOP-UP BUTTON
    # =====================================================

    if text == "💰 شارژ کیف پول":
        context.user_data["awaiting_wallet_amount"] = True
        context.user_data["wallet_amount"] = None
        context.user_data["awaiting_receipt_order_id"] = None

        await user_reply(update, context, 
            """
<b>✦ Kaletek</b>

💳 <b>شارژ کیف پول</b>
━━━━━━━━━━━━━━━━━━

💰 مبلغ موردنظر برای شارژ کیف پول را به تومان وارد کن.

مثال:

<b>50,000 تومان</b>

━━━━━━━━━━━━━━━━━━

🔹 مبلغ را با عدد وارد کن.
🔹 حداقل مبلغ شارژ: <b>1,000 تومان</b>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [back_button("profile")]
            ])
        )
        return

    # =====================================================
    # STORE
    # =====================================================

    if text == "🛒 فروشگاه اشتراک‌ها":
        await user_reply(update, context, 
            """
🛒 <b>فروشگاه اشتراک‌ها</b>

━━━━━━━━━━━━━━━━━━

پلن موردنظر خودت را انتخاب کن:
""",
            parse_mode=ParseMode.HTML,
            reply_markup=plans_menu("plan")
        )
        return

    # =====================================================
    # SERVICES
    # =====================================================

    if text == "📡 سرویس های من":
        services = get_services(user_id)
        rows = []
        if services:
            for service in services:
                rows.append([
                    InlineKeyboardButton(
                        f"📤 {service['config_name'] or service['code']}",
                        callback_data=f"resend_config:{service['id']}"
                    )
                ])
            rows.append([
                InlineKeyboardButton(
                    "🔄 تمدید سرویس",
                    callback_data="renew"
                )
            ])
        else:
            rows.append([
                InlineKeyboardButton(
                    "🛒 خرید سرویس",
                    callback_data="buy"
                )
            ])
        rows.append([back_button("home")])

        await user_reply(update, context, 
            services_text(user_id),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows)
        )
        return

    # =====================================================
    # REFERRAL
    # =====================================================

    if text == "🎁 دعوت و دریافت رایگان":
        bot_username = context.bot.username

        link = (
            f"https://t.me/"
            f"{bot_username}"
            f"?start={user_id}"
        )

        await user_reply(update, context, 
            f"""
🎁 <b>دعوت و دریافت رایگان</b>

━━━━━━━━━━━━━━━━━━

لینک اختصاصی شما:

<code>{escape(link)}</code>

━━━━━━━━━━━━━━━━━━

این لینک را برای دوستانت ارسال کن.

هر کاربر جدیدی که با لینک تو وارد شود، ثبت می‌شود.

🎁 <b>پاداش دعوت</b>
به ازای هر دعوت موفق، <b>3 GB</b> حجم رایگان به پاداش دعوتت اضافه می‌شود.

📦 موجودی پاداش فعلی: <b>{get_user(user_id)['referral_gb_balance'] or 0} GB</b>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=user_panel()
        )
        return

    # =====================================================
    # GUIDE
    # =====================================================

    if text == "📖 آموزش و راهنما":
        await user_reply(update, context, 
            """
📚 <b>راهنمای استفاده از سرویس</b>

┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄

🛒 <b>۱. خرید سرویس</b>
از بخش «فروشگاه اشتراک‌ها» پلن موردنظرت را انتخاب کن.
می‌توانی هزینه را از کیف پول پرداخت کنی یا با کارت و ارسال رسید پرداخت کنی.

💰 <b>۲. شارژ کیف پول</b>
از «پروفایل و کیف پول» مبلغ دلخواهت را وارد کن، واریز را انجام بده و تصویر رسید را ارسال کن. پس از تأیید ادمین، مبلغ به موجودی کیف پول اضافه می‌شود.

🎁 <b>۳. دعوت و دریافت رایگان</b>
لینک دعوت اختصاصی خودت را از بخش «🎁 دعوت و دریافت رایگان» بردار و برای دوستانت بفرست.
به ازای هر کاربر جدیدی که با لینک تو وارد ربات شود، <b>3 GB</b> پاداش رایگان برایت ثبت می‌شود.

📡 <b>۴. دریافت کانفیگ</b>
بعد از تأیید پرداخت و تحویل سرویس توسط ادمین، کانفیگ برایت ارسال می‌شود و در «سرویس های من» هم قابل مشاهده است.

🔄 <b>۵. تمدید</b>
اگر سرویس فعال داشته باشی، از بخش «سرویس های من» می‌توانی آن را تمدید کنی و هزینه را از کیف پول پرداخت کنی یا رسید ارسال کنی.

🔐 <b>۶. اتصال</b>
کانفیگ را کپی کن و داخل برنامه سازگار با نوع کانفیگ وارد کن، سپس اتصال را فعال کن.

🛟 <b>مشکل داشتی؟</b>
از بخش «تماس با پشتیبانی» با پشتیبانی در ارتباط باش.

┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
✨ <b>اگر در هر مرحله مشکلی داشتی، شماره سفارش یا کد سرویس را همراه پیامت ارسال کن.</b>
""",
            parse_mode=ParseMode.HTML,
            reply_markup=user_panel()
        )
        return

    # =====================================================
    # SUPPORT
    # =====================================================

    if text == "🛟 تماس با پشتیبانی":
        if (
            SUPPORT_STICKER_ID
            and SUPPORT_STICKER_ID != "PASTE_STICKER_FILE_ID_HERE"
        ):
            try:
                await update.message.reply_sticker(
                    SUPPORT_STICKER_ID
                )
            except Exception:
                pass

        await user_reply(update, context, 
            """
🛟 <b>تماس با پشتیبانی</b>

━━━━━━━━━━━━━━━━━━

اگر در خرید یا سرویس مشکلی داری،
از دکمه زیر با پشتیبانی تماس بگیر.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💬 تماس با پشتیبانی",
                        url=(
                            "https://t.me/"
                            + SUPPORT_USERNAME.lstrip("@")
                        )
                    )
                ]
            ])
        )
        return


# =========================================================
# RECEIPT BUTTON CALLBACK
# =========================================================

async def receipt_button_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    # این تابع دیگر استفاده نمی‌شود؛ منطق در callbacks است.
    pass


# =========================================================
# ERROR HANDLER
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

    # اول عکس، بعد متن
    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler
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
