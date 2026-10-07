"""Job-search assistant bot: daily digest of new matching jobs + follow-up reminders."""

from __future__ import annotations

import logging
from functools import wraps
from html import escape

import httpx
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import NetworkError, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from .config import Settings, load_settings
from .formatting import chunk_messages, format_application, format_job, parse_applied_args
from .matching import filter_jobs
from .sources import fetch_all
from .storage import Storage

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # would log the bot token in URLs
log = logging.getLogger("jobbot")

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
TELEGRAM_TIMEOUT = 30.0  # seconds

COMMANDS = [
    BotCommand("jobs", "Check for new jobs now"),
    BotCommand("all", "All matching open jobs"),
    BotCommand("applied", "Track an application: /applied Company - Role [url]"),
    BotCommand("followups", "Active applications"),
    BotCommand("companies", "Companies being watched"),
    BotCommand("stats", "Statistics"),
    BotCommand("help", "Help"),
]

HELP = (
    "<b>Job Bot</b> — new DevOps/Cloud jobs every morning + follow-up reminders.\n\n"
    "/jobs — check for new jobs now\n"
    "/all — every matching open position\n"
    "/applied Wiz - Senior DevOps Engineer https://… — track an application\n"
    "/followups — active applications\n"
    "/companies — companies being watched\n"
    "/stats — statistics\n\n"
    "Tap <b>✅ Applied</b> under a job and I'll remind you to follow up."
)


def settings_of(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]


def storage_of(context: ContextTypes.DEFAULT_TYPE) -> Storage:
    return context.bot_data["storage"]


def restricted(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if chat is None or chat.id not in settings_of(context).allowed_chat_ids:
            if update.callback_query:
                await update.callback_query.answer("Access denied", show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text("⛔ Access denied.")
            return None
        return await func(update, context)

    return wrapper


def job_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Applied", callback_data=f"apply:{job_id}"),
                InlineKeyboardButton("🙈 Not for me", callback_data=f"hide:{job_id}"),
            ]
        ]
    )


def followup_keyboard(app_id: int, days: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"📨 Followed up (+{days}d)", callback_data=f"snooze:{app_id}"
                ),
                InlineKeyboardButton("🗄 Close", callback_data=f"close:{app_id}"),
            ]
        ]
    )


async def find_matching_jobs(app: Application):
    search = app.bot_data["settings"].search
    jobs, errors = await fetch_all(app.bot_data["http"], search.companies)
    return filter_jobs(jobs, search), errors


def errors_note(errors: dict[str, str]) -> str:
    if not errors:
        return ""
    return "\n⚠️ Couldn't reach: " + ", ".join(escape(name) for name in sorted(errors))


async def send_new_jobs(app: Application, chat_ids, *, announce_empty: bool) -> int:
    settings: Settings = app.bot_data["settings"]
    matched, errors = await find_matching_jobs(app)
    new_jobs = app.bot_data["storage"].add_new_jobs(matched)
    limit = settings.search.max_jobs_per_digest

    for chat_id in chat_ids:
        try:
            if not new_jobs:
                if announce_empty:
                    await app.bot.send_message(
                        chat_id,
                        "No new jobs since the last check. /all shows every matching open position."
                        + errors_note(errors),
                        parse_mode=ParseMode.HTML,
                    )
                continue
            header = f"🆕 <b>{len(new_jobs)} new job(s)</b>{errors_note(errors)}"
            await app.bot.send_message(chat_id, header, parse_mode=ParseMode.HTML)
            for job in new_jobs[:limit]:
                await app.bot.send_message(
                    chat_id,
                    format_job(job),
                    parse_mode=ParseMode.HTML,
                    link_preview_options=NO_PREVIEW,
                    reply_markup=job_keyboard(job.id),
                )
            if len(new_jobs) > limit:
                await app.bot.send_message(
                    chat_id, f"…and {len(new_jobs) - limit} more. Use /all to see everything."
                )
        except TelegramError:
            log.exception("Failed to send jobs to chat %s", chat_id)
    return len(new_jobs)


async def send_due_followups(app: Application, chat_ids) -> None:
    settings: Settings = app.bot_data["settings"]
    tz = settings.search.digest_time.tzinfo
    for application in app.bot_data["storage"].due_followups():
        text = "⏰ <b>Time to follow up</b>\n" + format_application(application, tz)
        for chat_id in chat_ids:
            try:
                await app.bot.send_message(
                    chat_id,
                    text,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=NO_PREVIEW,
                    reply_markup=followup_keyboard(application.id, settings.search.followup_days),
                )
            except TelegramError:
                log.exception("Failed to send follow-up to chat %s", chat_id)


# --- Commands -----------------------------------------------------------------


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = f"Your chat id: <code>{chat_id}</code>\n\n"
    if chat_id in settings_of(context).allowed_chat_ids:
        text += HELP
    else:
        text += "Add it to ALLOWED_CHAT_IDS and restart the bot to get access."
    await update.message.reply_html(text)


@restricted
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP)


@restricted
async def jobs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Checking job boards…")
    await send_new_jobs(context.application, [update.effective_chat.id], announce_empty=True)


@restricted
async def all_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Collecting all matching jobs…")
    matched, errors = await find_matching_jobs(context.application)
    if not matched:
        await update.message.reply_html("Nothing matches right now." + errors_note(errors))
        return
    blocks = [f"<b>{len(matched)} matching open job(s)</b>{errors_note(errors)}"]
    blocks += [format_job(job) for job in matched]
    for message in chunk_messages(blocks):
        await update.message.reply_html(message, link_preview_options=NO_PREVIEW)


@restricted
async def applied_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    parsed = parse_applied_args(" ".join(context.args))
    if not parsed:
        await update.message.reply_text(
            "Usage: /applied Company - Role https://link (role and link optional)"
        )
        return
    company, role, url = parsed
    settings = settings_of(context)
    application = storage_of(context).add_application(
        company, role, url, settings.search.followup_days
    )
    tz = settings.search.digest_time.tzinfo
    await update.message.reply_html(
        "✅ Tracking:\n" + format_application(application, tz), link_preview_options=NO_PREVIEW
    )


@restricted
async def followups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = settings_of(context)
    applications = storage_of(context).active_applications()
    if not applications:
        await update.message.reply_text(
            "No active applications. Tap ✅ Applied under a job or use /applied."
        )
        return
    tz = settings.search.digest_time.tzinfo
    for application in applications:
        await update.message.reply_html(
            format_application(application, tz),
            link_preview_options=NO_PREVIEW,
            reply_markup=followup_keyboard(application.id, settings.search.followup_days),
        )


@restricted
async def companies_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    search = settings_of(context).search
    lines = [f"• {escape(c.name)} <i>({c.source})</i>" for c in search.companies]
    text = f"<b>Watching {len(lines)} companies</b>\n" + "\n".join(lines)
    text += "\n\nKeywords: " + escape(", ".join(search.keywords))
    await update.message.reply_html(text)


@restricted
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = storage_of(context).stats()
    await update.message.reply_text(
        f"Jobs found: {s['jobs_seen']}\nActive applications: {s['active']}\nClosed: {s['closed']}"
    )


@restricted
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    action, _, raw_id = (query.data or "").partition(":")
    if not raw_id.isdigit():
        await query.answer()
        return
    item_id = int(raw_id)
    storage = storage_of(context)
    settings = settings_of(context)
    days = settings.search.followup_days
    original = query.message.text_html if query.message else ""

    if action == "apply":
        job = storage.get_job(item_id)
        if job is None:
            await query.answer("Job not found", show_alert=True)
            return
        if storage.has_application_for_url(job.url):
            await query.answer("Already tracked")
        else:
            storage.add_application(job.company, job.title, job.url, days)
            await query.answer("Saved")
        await query.edit_message_text(
            f"{original}\n\n✅ <b>Applied</b> — I'll remind you in {days} days.",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    elif action == "hide":
        await query.answer("Hidden")
        await query.edit_message_reply_markup(reply_markup=None)
    elif action == "snooze":
        storage.snooze(item_id, days)
        await query.answer(f"Next reminder in {days} days")
        await query.edit_message_text(
            f"{original}\n\n📨 Followed up — next reminder in {days} days.",
            parse_mode=ParseMode.HTML,
            link_preview_options=NO_PREVIEW,
        )
    elif action == "close":
        storage.close_application(item_id)
        await query.answer("Closed")
        await query.edit_message_text(
            f"{original}\n\n🗄 Closed.", parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW
        )
    else:
        await query.answer()


# --- Scheduled digest & lifecycle ----------------------------------------------


async def daily_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    app = context.application
    chats = app.bot_data["settings"].allowed_chat_ids
    count = await send_new_jobs(app, chats, announce_empty=False)
    await send_due_followups(app, chats)
    log.info("Daily digest done: %d new job(s)", count)


async def on_startup(app: Application) -> None:
    app.bot_data["http"] = httpx.AsyncClient(
        timeout=20, headers={"User-Agent": "job-bot/1.0 (personal job search)"}
    )
    try:
        await app.bot.set_my_commands(COMMANDS)
    except TelegramError as exc:
        # The command menu is cosmetic: a slow Telegram API must not stop the bot.
        log.warning("Could not set the command menu (%s); continuing", exc)
    if not app.bot_data["settings"].allowed_chat_ids:
        log.warning("ALLOWED_CHAT_IDS is empty: send /start to the bot to get your chat id.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log handler errors in one line; network blips are expected and not worth a traceback."""
    if isinstance(context.error, NetworkError):
        log.warning("Telegram network error: %s", context.error)
    else:
        log.error("Unhandled error", exc_info=context.error)


async def on_shutdown(app: Application) -> None:
    if client := app.bot_data.get("http"):
        await client.aclose()
    app.bot_data["storage"].close()


def build_application(settings: Settings) -> Application:
    app = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        # Generous timeouts: home Wi-Fi or a busy Telegram API shouldn't crash the bot.
        .connect_timeout(TELEGRAM_TIMEOUT)
        .read_timeout(TELEGRAM_TIMEOUT)
        .write_timeout(TELEGRAM_TIMEOUT)
        .pool_timeout(TELEGRAM_TIMEOUT)
        .get_updates_connect_timeout(TELEGRAM_TIMEOUT)
        .get_updates_read_timeout(TELEGRAM_TIMEOUT)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings
    app.bot_data["storage"] = Storage(settings.db_path)

    for name, handler in [
        ("start", start_cmd),
        ("help", help_cmd),
        ("jobs", jobs_cmd),
        ("all", all_cmd),
        ("applied", applied_cmd),
        ("followups", followups_cmd),
        ("companies", companies_cmd),
        ("stats", stats_cmd),
    ]:
        app.add_handler(CommandHandler(name, handler))
    app.add_handler(CallbackQueryHandler(button))
    app.add_error_handler(on_error)

    app.job_queue.run_daily(
        daily_digest, time=settings.search.digest_time, days=settings.search.digest_days
    )
    return app


def main() -> None:
    settings = load_settings()
    log.info(
        "Starting job-bot: %d companies, digest at %s",
        len(settings.search.companies),
        settings.search.digest_time.strftime("%H:%M"),
    )
    build_application(settings).run_polling(drop_pending_updates=True, bootstrap_retries=5)


if __name__ == "__main__":
    main()
