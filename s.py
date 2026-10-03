import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

TOKEN = "8952875701:AAFZacIec2YPSIkA2K9vSFxnnbRdNiZb59g"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy")],
        [
            InlineKeyboardButton("📦 سرویس من", callback_data="my_service"),
            InlineKeyboardButton("🔄 تمدید", callback_data="renew"),
        ],
        [
            InlineKeyboardButton("🎁 دعوت دوستان", callback_data="referral"),
            InlineKeyboardButton("💬 پشتیبانی", callback_data="support"),
        ],
    ]

    await update.message.reply_text(
        "✨ به ربات فروش خوش آمدید!\n\n"
        "یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "buy":
        keyboard = [
            [InlineKeyboardButton("📅 یک ماهه - 30GB", callback_data="plan_30")],
            [InlineKeyboardButton("📅 یک ماهه - 70GB", callback_data="plan_70")],
            [InlineKeyboardButton("📅 یک ماهه - 150GB", callback_data="plan_150")],
            [InlineKeyboardButton("🔙 برگشت", callback_data="back")],
        ]

        await query.edit_message_text(
            "🛒 پلن موردنظر را انتخاب کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data.startswith("plan_"):
        plan = query.data.replace("plan_", "")

        await query.edit_message_text(
            f"✅ پلن {plan}GB انتخاب شد.\n\n"
            "💳 مرحله بعد: پرداخت\n"
            "⚠️ سیستم پرداخت هنوز به ربات متصل نشده است."
        )

    elif query.data == "my_service":
        await query.edit_message_text(
            "📦 سرویس شما\n\n"
            "فعلاً سرویس فعالی برای حساب شما ثبت نشده است."
        )

    elif query.data == "renew":
        await query.edit_message_text(
            "🔄 برای تمدید، ابتدا یک سرویس فعال داشته باشید."
        )

    elif query.data == "referral":
        user_id = query.from_user.id
        await query.edit_message_text(
            "🎁 دعوت دوستان\n\n"
            f"لینک دعوت شما:\n"
            f"https://t.me/YOUR_BOT_USERNAME?start=ref_{user_id}"
        )

    elif query.data == "support":
        await query.edit_message_text(
            "💬 پشتیبانی\n\n"
            "برای ارتباط با پشتیبانی به @YOUR_USERNAME پیام دهید."
        )

    elif query.data == "back":
        await start_from_callback(query)


async def start_from_callback(query):
    keyboard = [
        [InlineKeyboardButton("🛒 خرید سرویس", callback_data="buy")],
        [
            InlineKeyboardButton("📦 سرویس من", callback_data="my_service"),
            InlineKeyboardButton("🔄 تمدید", callback_data="renew"),
        ],
        [
            InlineKeyboardButton("🎁 دعوت دوستان", callback_data="referral"),
            InlineKeyboardButton("💬 پشتیبانی", callback_data="support"),
        ],
    ]

    await query.edit_message_text(
        "✨ منوی اصلی:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده است.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
