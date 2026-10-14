import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler

# Conversation states for filter flow
SELECT_WALLET, SELECT_FILTER_TYPE, ENTER_ASSET, SELECT_SIDE, ENTER_MIN_VALUE = range(5)

# Conversation states for watch flow
WATCH_ENTER_ADDRESS = 5
WATCH_ENTER_ALIAS = 6

# Conversation states for clearfilters flow
CLEARFILTERS_ENTER_ADDRESS = 7
CLEARFILTERS_CONFIRM = 8

# Conversation states for unwatch flow
UNWATCH_SELECT_WALLET = 9
UNWATCH_CONFIRM = 10

# Conversation states for alias editing flow
ALIAS_SELECT_WALLET = 11
ALIAS_ENTER_ALIAS = 12

# Import our custom modules
from database import Database
from subscription_manager import WalletSubscriptionManager
from filter_engine import FilterEngine

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress verbose HTTP logging from python-telegram-bot
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

# Suppress PTBUserWarning for ConversationHandler per_message settings
import warnings
warnings.filterwarnings("ignore", message=".*per_message.*ConversationHandler.*")

# Get Telegram bot token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not found in environment variables")
    exit(1)

# Get admin user ID (optional, for admin dashboard)
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
if ADMIN_USER_ID:
    try:
        ADMIN_USER_ID = int(ADMIN_USER_ID)
        logger.info("Admin user ID configured")
    except ValueError:
        logger.warning("ADMIN_USER_ID must be an integer, admin dashboard disabled")
        ADMIN_USER_ID = None
else:
    logger.info("ADMIN_USER_ID not configured, admin dashboard disabled")

# Redact Telegram bot token from logs
class TokenRedactor(logging.Filter):
    """Filter to redact Telegram bot tokens from logs"""
    def filter(self, record):
        if hasattr(record, 'msg'):
            # Redact token pattern in URLs
            if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN in str(record.msg):
                record.msg = str(record.msg).replace(TELEGRAM_BOT_TOKEN, '<REDACTED>')
        if hasattr(record, 'args'):
            # Also check args for token
            new_args = []
            for arg in record.args:
                if isinstance(arg, str) and TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN in arg:
                    new_args.append(arg.replace(TELEGRAM_BOT_TOKEN, '<REDACTED>'))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
        return True

# Add token redactor to all loggers
for handler in logging.root.handlers:
    handler.addFilter(TokenRedactor())

# Hyperliquid WebSocket endpoint
HYPERLIQUID_WS_URL = "wss://api.hyperliquid.xyz/ws"

# Global instances
database = Database()
subscription_manager = None
application = None

# Shutdown flag to prevent alert sends after application shutdown
is_shutting_down = False

# Event for monitoring thread shutdown coordination
monitoring_shutdown_event = None

# Reference to main event loop for cross-thread Telegram calls
main_event_loop = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command with button menu"""
    keyboard = [
        [
            InlineKeyboardButton("➕ Add Wallet", callback_data="menu_watch"),
            InlineKeyboardButton("👀 My Wallets", callback_data="menu_wallets")
        ],
        [
            InlineKeyboardButton("🔔 Alerts", callback_data="menu_filters"),
            InlineKeyboardButton("❓ Help", callback_data="menu_help")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = """👋 Hyperliquid Wallet Monitor

Monitor wallets and receive real-time trade alerts."""
    
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)
    logger.info(f"Start command received from user {update.effective_user.id}")

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu button interactions"""
    query = update.callback_query
    await query.answer()

    if query.data == "menu_wallets":
        # Show wallet management UI
        await query.edit_message_text("👀 My Wallets\n\n")
        await wallets(update, context)
    elif query.data == "menu_help":
        # Trigger help command
        await help_command(update, context)
    elif query.data == "menu_start":
        # Return to main dashboard
        await start(update, context)

async def wallet_management_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle wallet management button interactions"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("wallet_manage_"):
        await wallet_manage_selected(update, context)
    elif query.data.startswith("wallet_filter_"):
        await wallet_filter_selected(update, context)
    elif query.data.startswith("wallet_unwatch_"):
        await wallet_unwatch_selected(update, context)
    elif query.data.startswith("unwatch_confirm_"):
        await unwatch_confirm_selected(update, context)
    elif query.data.startswith("unwatch_wallet_"):
        await unwatch_wallet_selected(update, context)
    elif query.data == "menu_start":
        # Return to main dashboard
        await start(update, context)
    elif query.data == "menu_wallets":
        # Return to wallet list
        await wallets(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    message = """🤖 HYPERLIQUID WALLET MONITOR

Commands:
/start - Start the bot
/watch <wallet> - Monitor a wallet
/unwatch <wallet> - Stop monitoring a wallet
/wallets - List your watched wallets
/filters - View your filters
/clearfilters <wallet> - Clear filters for a wallet
/help - Show this help message

Filter types:
  asset - Filter by token (e.g., BTC, or BTC,ETH,DOGE)
  side - Filter by side (BUY or SELL)
  min_value - Minimum USD trade value (e.g., 100000)

Set filters via /start → 🔔 Alerts

Legacy command:
/filter <wallet> <type> <value> - Set alert filter directly

Example:
/filter 0xABC... asset BTC
/filter 0xABC... asset BTC,ETH,DOGE
/filter 0xABC... side SELL
/filter 0xABC... min_value 100000"""

    if update.callback_query:
        keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="menu_start")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message)
    logger.info(f"Help command received from user {update.effective_user.id}")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /admin command - admin dashboard"""
    global ADMIN_USER_ID, subscription_manager

    # Check if admin is configured
    if not ADMIN_USER_ID:
        message = "❌ Admin dashboard is not configured."
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        return

    # Check if user is admin
    if update.effective_user.id != ADMIN_USER_ID:
        message = "❌ You are not authorized to access the admin dashboard."
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        logger.warning(f"Unauthorized admin access attempt by user {update.effective_user.id}")
        return

    # Get statistics
    total_users = database.get_user_count()
    users_with_wallets = database.get_users_with_wallets_count()
    total_wallets = database.get_wallet_count()
    unique_wallets = database.get_unique_wallet_addresses_count()
    total_alerts = database.get_total_alerts_count()
    alerts_today = database.get_alerts_today_count()

    # Get monitoring status
    if subscription_manager:
        status_info = subscription_manager.get_status()
        monitoring_active = status_info["monitoring_active"]
        active_subscriptions = status_info["subscribed_wallets"]
        monitoring_status = "🟢 Running" if monitoring_active else "🔴 Stopped"
    else:
        monitoring_status = "🔴 Stopped"
        active_subscriptions = 0

    # Build dashboard message
    message = f"""🛠 ADMIN DASHBOARD

👥 USERS
Total Users: {total_users}
Users with Wallets: {users_with_wallets}

👛 WALLETS
Watched Wallets: {total_wallets}
Unique Wallets: {unique_wallets}

🔔 ALERTS
Alerts Sent: {total_alerts:,}
Today: {alerts_today}

🟢 SYSTEM
Monitoring: {monitoring_status}
Active Wallets: {active_subscriptions}"""

    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_refresh")],
        [InlineKeyboardButton("◀️ Back", callback_data="menu_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        except Exception as e:
            # Handle "Message is not modified" error gracefully
            if "Message is not modified" in str(e):
                # No changes needed, just answer the query
                await update.callback_query.answer()
            else:
                # Re-raise other errors
                raise
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

    logger.info(f"Admin dashboard accessed by user {update.effective_user.id}")

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin dashboard callback buttons"""
    global ADMIN_USER_ID

    query = update.callback_query
    await query.answer()

    # Verify admin on every callback
    if update.effective_user.id != ADMIN_USER_ID:
        await query.edit_message_text("❌ You are not authorized.")
        logger.warning(f"Unauthorized admin callback by user {update.effective_user.id}")
        return

    if query.data == "admin_refresh":
        # Refresh dashboard
        await admin_command(update, context)
    elif query.data == "menu_start":
        # Return to main menu
        await start(update, context)

# Placeholder functions for V2 features (not currently used in menu)
# Kept for future use when V2 features are implemented

async def wallet_stats_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for V2 wallet stats"""
    keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="menu_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = """📊 Wallet Stats

Advanced wallet analytics coming in V2.

Future features will include:
- PnL tracking
- Trading history
- Volume analysis
- Wallet behavior patterns"""

    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

async def summary_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for V2 summary"""
    keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="menu_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = """📋 Summary

Activity summary coming in V2.

Future features will include:
- Recent activity overview
- Trading volume summary
- Asset activity breakdown"""

    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

async def settings_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Placeholder for V2 settings"""
    keyboard = [[InlineKeyboardButton("◀️ Back", callback_data="menu_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = """⚙️ Settings

Settings configuration coming in V2.

Future features will include:
- Notification preferences
- Alert preferences
- Account settings"""

    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /watch command - starts guided flow if no args, otherwise uses legacy syntax"""
    # If no arguments, start guided flow
    if not context.args:
        return await watch_start(update, context)
    
    # Legacy syntax: /watch <wallet_address>
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /watch <wallet_address>")
        return
    
    wallet_address = context.args[0]
    
    # Basic wallet address validation (starts with 0x and is 42 characters)
    if not wallet_address.startswith("0x") or len(wallet_address) != 42:
        await update.message.reply_text("Invalid wallet address. Must be a 42-character hex string starting with 0x")
        return
    
    # Get or create user
    user_id = database.get_or_create_user(update.effective_user.id)
    
    # Add wallet to watchlist (no alias for legacy command)
    already_watching = not database.add_wallet_to_watchlist(user_id, wallet_address)
    
    # Format wallet address for display
    display = database.format_wallet_display(wallet_address)
    
    if already_watching:
        await update.message.reply_text(
            f"👀 You're already monitoring:\n\n{display}"
        )
    else:
        await update.message.reply_text(
            f"✅ Wallet added\n\nNow monitoring:\n\n{display}"
        )
        
        # Add wallet to subscription manager
        if subscription_manager:
            await subscription_manager.add_wallet(wallet_address)
            # Ensure monitoring is running
            ensure_monitoring_running()
        
        logger.info(f"User {update.effective_user.id} started watching wallet {wallet_address}")

async def watch_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start guided wallet addition - show address input prompt"""
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="watch_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = (
        "➕ Add Wallet\n\n"
        "Please paste the Hyperliquid wallet address\n"
        "you want to monitor.\n\n"
        "Example:\n"
        "0x1234...abcd"
    )

    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass  # Already answered by menu_handler
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

    return WATCH_ENTER_ADDRESS

async def watch_address_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle wallet address input in guided flow"""
    wallet_address = update.message.text.strip()

    # Basic wallet address validation
    if not wallet_address.startswith("0x") or len(wallet_address) != 42:
        await update.message.reply_text(
            "❌ Invalid wallet address.\n\n"
            "Must be a 42-character hex string starting with 0x.\n\n"
            "Please try again or press Cancel to exit."
        )
        return WATCH_ENTER_ADDRESS

    # Store wallet address in context
    context.user_data['wallet_address'] = wallet_address

    # Ask for alias (optional)
    keyboard = [
        [InlineKeyboardButton("⏭️ Skip (No Alias)", callback_data="watch_skip_alias")],
        [InlineKeyboardButton("❌ Cancel", callback_data="watch_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "➕ Wallet Address Accepted\n\n"
        f"Address: {wallet_address[:6]}...{wallet_address[-4:]}\n\n"
        "Optional: Enter a friendly name/alias for this wallet\n"
        "(e.g., Binance Whale, My Trading Wallet)\n\n"
        "Or tap Skip to continue without an alias.",
        reply_markup=reply_markup
    )

    return WATCH_ENTER_ALIAS

async def watch_alias_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle wallet alias input in guided flow"""
    alias = update.message.text.strip()
    wallet_address = context.user_data.get('wallet_address')

    if not wallet_address:
        await update.message.reply_text("❌ Error: Wallet address not found. Please start over.")
        return ConversationHandler.END

    # Get or create user
    user_id = database.get_or_create_user(update.effective_user.id)

    # Add wallet to watchlist with alias
    already_watching = not database.add_wallet_to_watchlist(user_id, wallet_address, alias)

    display = database.format_wallet_display(wallet_address, alias)

    if already_watching:
        await update.message.reply_text(
            f"👀 You're already monitoring:\n\n{display}"
        )
    else:
        await update.message.reply_text(
            f"✅ Wallet added\n\nNow monitoring:\n\n{display}"
        )
        
        # Add wallet to subscription manager
        if subscription_manager:
            await subscription_manager.add_wallet(wallet_address)
            # Ensure monitoring is running
            ensure_monitoring_running()

        logger.info(f"User {update.effective_user.id} started watching wallet {wallet_address} with alias '{alias}'")

    return ConversationHandler.END

async def watch_skip_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle skipping alias entry"""
    query = update.callback_query
    await query.answer()

    wallet_address = context.user_data.get('wallet_address')

    if not wallet_address:
        await query.edit_message_text("❌ Error: Wallet address not found. Please start over.")
        return ConversationHandler.END

    # Get or create user
    user_id = database.get_or_create_user(update.effective_user.id)

    # Add wallet to watchlist without alias
    already_watching = not database.add_wallet_to_watchlist(user_id, wallet_address)

    display = database.format_wallet_display(wallet_address)

    if already_watching:
        await query.edit_message_text(
            f"👀 You're already monitoring:\n\n{display}"
        )
    else:
        await query.edit_message_text(
            f"✅ Wallet added\n\nNow monitoring:\n\n{display}"
        )
        
        # Add wallet to subscription manager
        if subscription_manager:
            await subscription_manager.add_wallet(wallet_address)
            # Ensure monitoring is running
            ensure_monitoring_running()

        logger.info(f"User {update.effective_user.id} started watching wallet {wallet_address} without alias")

    return ConversationHandler.END

async def alias_select_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle wallet selection for alias editing"""
    query = update.callback_query
    await query.answer()

    wallet_address = query.data.replace("alias_wallet_", "")
    context.user_data['wallet_address'] = wallet_address

    current_alias = database.get_wallet_alias(update.effective_user.id, wallet_address)
    display = database.format_wallet_display(wallet_address, current_alias)

    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="alias_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"✏️ Edit Alias\n\n{display}\n\n"
        f"Current alias: {current_alias if current_alias else '(none)'}\n\n"
        "Enter a new alias (or leave blank to remove alias):",
        reply_markup=reply_markup
    )

    return ALIAS_ENTER_ALIAS

async def alias_enter_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle alias input"""
    new_alias = update.message.text.strip()
    wallet_address = context.user_data.get('wallet_address')

    if not wallet_address:
        await update.message.reply_text("❌ Error: Wallet address not found. Please start over.")
        return ConversationHandler.END

    # Get or create user
    user_id = database.get_or_create_user(update.effective_user.id)

    # Update alias (or clear if empty)
    if new_alias:
        database.set_wallet_alias(user_id, wallet_address, new_alias)
        display = database.format_wallet_display(wallet_address, new_alias)
        await update.message.reply_text(
            f"✅ Alias updated\n\n{display}"
        )
    else:
        database.set_wallet_alias(user_id, wallet_address, None)
        display = database.format_wallet_display(wallet_address)
        await update.message.reply_text(
            f"✅ Alias removed\n\n{display}"
        )

    return ConversationHandler.END

async def alias_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle alias editing cancellation"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Alias editing cancelled.")
    return ConversationHandler.END

async def watch_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle watch setup cancellation"""
    query = update.callback_query
    await query.answer()
    
    # Return to main dashboard
    await start(update, context)
    return ConversationHandler.END

async def unwatch_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unwatch cancellation"""
    query = update.callback_query
    await query.answer()
    
    # Return to main menu
    keyboard = [
        [InlineKeyboardButton("➕ Watch Wallet", callback_data="menu_watch")],
        [InlineKeyboardButton("👀 My Wallets", callback_data="menu_wallets")],
        [InlineKeyboardButton("❌ Unwatch Wallet", callback_data="menu_unwatch")],
        [InlineKeyboardButton("🔔 Alert Filters", callback_data="menu_filters")],
        [InlineKeyboardButton("❓ Help", callback_data="menu_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = """👋 Welcome to Hyperliquid Monitor

Monitor Hyperliquid wallets and receive Telegram
alerts when they trade.

What would you like to do?"""
    
    await query.edit_message_text(message, reply_markup=reply_markup)
    return ConversationHandler.END

async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unwatch command - starts guided flow if no args, otherwise uses legacy syntax"""
    # If no arguments, start guided flow
    if not context.args:
        return await unwatch_start(update, context)
    
    # Legacy syntax: /unwatch <wallet_address>
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /unwatch <wallet_address>")
        return
    
    wallet_address = context.args[0]
    
    # Basic wallet address validation
    if not wallet_address.startswith("0x") or len(wallet_address) != 42:
        await update.message.reply_text("Invalid wallet address. Must be a 42-character hex string starting with 0x")
        return
    
    # Get user
    user_id = database.get_or_create_user(update.effective_user.id)
    
    # Remove wallet from watchlist
    removed = database.remove_wallet_from_watchlist(user_id, wallet_address)
    
    # Format wallet address for display
    short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
    
    if removed:
        await update.message.reply_text(
            f"🛑 Wallet removed\n\nNo longer monitoring:\n\n{short_wallet}"
        )
        
        # Check if any other users are still watching this wallet
        subscribers = database.get_wallet_subscribers(wallet_address)
        if not subscribers and subscription_manager:
            # No one else watching, remove from subscription manager
            await subscription_manager.remove_wallet(wallet_address)
        
        logger.info(f"User {update.effective_user.id} stopped watching wallet {wallet_address}")
    else:
        await update.message.reply_text(
            f"You're not monitoring:\n\n{short_wallet}"
        )

async def unwatch_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start guided unwatch - show wallet selection with aliases"""
    user_id = database.get_or_create_user(update.effective_user.id)
    wallets = database.get_user_wallets_with_aliases(user_id)
    
    if not wallets:
        keyboard = [
            [InlineKeyboardButton("➕ Watch Wallet", callback_data="menu_watch")],
            [InlineKeyboardButton("❌ Cancel", callback_data="menu_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "❌ Unwatch Wallet\n\nYou're not monitoring any wallets yet.\n\nUse /watch to start monitoring a wallet first."
        if update.callback_query:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
        return ConversationHandler.END
    
    # Create inline keyboard with wallet buttons showing aliases
    keyboard = []
    for wallet_address, wallet_alias in wallets:
        display = database.format_wallet_display(wallet_address, wallet_alias)
        keyboard.append([InlineKeyboardButton(display, callback_data=f"unwatch_wallet_{wallet_address}")])
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="menu_start")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = "❌ Select wallet to unwatch\n\n"
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)
    
    return UNWATCH_SELECT_WALLET

async def wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /wallets command - show wallet management UI"""
    # Get user
    user_id = database.get_or_create_user(update.effective_user.id)
    
    # Get user's wallets with aliases
    user_wallets = database.get_user_wallets_with_aliases(user_id)
    
    if not user_wallets:
        message = (
            "👀 My Wallets\n\n"
            "You aren't monitoring any wallets yet.\n\n"
            "Use:\n\n/watch <wallet>\n\nto start monitoring."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        return
    
    # Build keyboard with wallet buttons
    keyboard = []
    for wallet_address, wallet_alias in user_wallets:
        display = database.format_wallet_display(wallet_address, wallet_alias)
        keyboard.append([InlineKeyboardButton(display, callback_data=f"wallet_manage_{wallet_address}")])
    
    keyboard.append([InlineKeyboardButton("➕ Add Wallet", callback_data="menu_watch")])
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="menu_start")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"👀 My Wallets\n\nTotal: {len(user_wallets)} wallet(s)"
    if update.callback_query:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)
    logger.info(f"User {update.effective_user.id} requested their watchlist")

async def wallet_manage_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle wallet selection for management"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = query.data.replace("wallet_manage_", "")
    user_id = database.get_or_create_user(update.effective_user.id)
    
    wallet_alias = database.get_wallet_alias(user_id, wallet_address)
    display = database.format_wallet_display(wallet_address, wallet_alias)
    
    keyboard = [
        [InlineKeyboardButton("🔔 Filters", callback_data=f"wallet_filter_{wallet_address}")],
        [InlineKeyboardButton("✏️ Edit Alias", callback_data=f"alias_wallet_{wallet_address}")],
        [InlineKeyboardButton("❌ Unwatch", callback_data=f"wallet_unwatch_{wallet_address}")],
        [InlineKeyboardButton("◀️ Back", callback_data="menu_wallets")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"👀 {display}\n\n"
        "Select an action:",
        reply_markup=reply_markup
    )

async def wallet_filter_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle filter selection from wallet management"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = query.data.replace("wallet_filter_", "")
    context.user_data['wallet_address'] = wallet_address
    
    # Start filter flow for this wallet
    return await filter_start(update, context)

async def wallet_unwatch_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unwatch selection from wallet management"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = query.data.replace("wallet_unwatch_", "")
    user_id = database.get_or_create_user(update.effective_user.id)
    
    wallet_alias = database.get_wallet_alias(user_id, wallet_address)
    display = database.format_wallet_display(wallet_address, wallet_alias)
    
    # Show confirmation
    keyboard = [
        [InlineKeyboardButton("✅ Confirm Unwatch", callback_data=f"unwatch_confirm_{wallet_address}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"wallet_manage_{wallet_address}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"❌ Unwatch Wallet?\n\n{display}\n\n"
        "This wallet will be removed from your watchlist.\n"
        "Monitoring will stop for this wallet.",
        reply_markup=reply_markup
    )

async def unwatch_wallet_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle wallet selection from guided unwatch flow"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = query.data.replace("unwatch_wallet_", "")
    user_id = database.get_or_create_user(update.effective_user.id)
    
    wallet_alias = database.get_wallet_alias(user_id, wallet_address)
    display = database.format_wallet_display(wallet_address, wallet_alias)
    
    # Show confirmation
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data=f"unwatch_confirm_{wallet_address}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Are you sure you want to unwatch:\n\n{display}\n\n"
        "This wallet will be removed from your watchlist.\n"
        "Monitoring will stop for this wallet.",
        reply_markup=reply_markup
    )
    
    return UNWATCH_CONFIRM

async def unwatch_confirm_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unwatch confirmation"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = query.data.replace("unwatch_confirm_", "")
    user_id = database.get_or_create_user(update.effective_user.id)
    
    wallet_alias = database.get_wallet_alias(user_id, wallet_address)
    display = database.format_wallet_display(wallet_address, wallet_alias)
    
    # Remove wallet from watchlist
    if database.remove_wallet_from_watchlist(user_id, wallet_address):
        # Check if any other users are still watching this wallet
        subscribers = database.get_wallet_subscribers(wallet_address)
        if not subscribers and subscription_manager:
            # No one else watching, remove from subscription manager
            await subscription_manager.remove_wallet(wallet_address)

        await query.edit_message_text(
            f"🛑 Wallet removed\n\nNo longer monitoring:\n\n{display}"
        )
        logger.info(f"User {update.effective_user.id} stopped watching wallet {wallet_address}")
    else:
        await query.edit_message_text(
            f"You're not monitoring:\n\n{display}"
        )
    
    # Return to wallet list
    return await wallets(update, context)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - admin only"""
    global subscription_manager, ADMIN_USER_ID

    # Check if admin is configured
    if not ADMIN_USER_ID:
        await update.message.reply_text("❌ Status command is not configured.")
        return

    # Check if user is admin
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("❌ You are not authorized to access this command.")
        logger.warning(f"Unauthorized status access attempt by user {update.effective_user.id}")
        return

    # Get database stats
    total_users = database.get_user_count()
    total_wallets = database.get_wallet_count()

    # Get subscription manager status
    if subscription_manager:
        status_info = subscription_manager.get_status()
        connected = status_info["connected"]
        active_subscriptions = status_info["subscribed_wallets"]
        monitoring_active = status_info["monitoring_active"]
        last_activity = subscription_manager.get_time_since_last_activity()
    else:
        connected = False
        active_subscriptions = 0
        monitoring_active = False
        last_activity = None

    # Build response
    if connected and monitoring_active:
        status_emoji = "🟢"
        connection_status = "Connected"

        if last_activity is not None:
            if last_activity < 60:
                activity_text = f"{int(last_activity)} seconds ago"
            else:
                activity_text = f"{int(last_activity // 60)} minutes ago"
        else:
            activity_text = "Just connected"
    else:
        status_emoji = "🔴"
        connection_status = "Disconnected"
        activity_text = "N/A"
        if subscription_manager and subscription_manager.monitoring_active:
            connection_status = "Reconnecting..."
        elif subscription_manager and subscription_manager.subscribed_wallets:
            connection_status = "Connecting..."

    response = f"""{status_emoji} MONITOR STATUS

Hyperliquid: {connection_status}
Watched wallets: {total_wallets}
Active subscriptions: {active_subscriptions}
Last activity: {activity_text}
Total users: {total_users}"""

    await update.message.reply_text(response)
    logger.info(f"Admin user {update.effective_user.id} requested status")

async def filter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /filter command - starts guided flow if no args, otherwise uses legacy syntax"""
    logger.info(f"Filter command received from user {update.effective_user.id}, args: {context.args}")
    
    # If no arguments, start guided flow (return state to start conversation)
    if not context.args:
        logger.info("Starting guided filter flow")
        return await filter_start(update, context)
    
    # Legacy syntax: /filter <wallet> <filter_type> <value>
    # Return ConversationHandler.END to exit conversation immediately
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: /filter <wallet> <filter_type> <value>\n\n"
            "Available filters:\n"
            "  asset - Filter by asset/token (e.g., BTC)\n"
            "  side - Filter by side (BUY or SELL)\n"
            "  min_value - Minimum USD trade value (e.g., 100000)\n\n"
            "Or use /filter without arguments for guided setup."
        )
        return ConversationHandler.END
    
    wallet_address = context.args[0]
    filter_type = context.args[1]
    filter_value = context.args[2] if len(context.args) > 2 else None
    
    # Validate wallet address
    if not wallet_address.startswith("0x") or len(wallet_address) != 42:
        await update.message.reply_text("Invalid wallet address. Must be a 42-character hex string starting with 0x")
        return ConversationHandler.END
    
    # Check if user watches this wallet
    user_id = database.get_or_create_user(update.effective_user.id)
    if not database.user_watches_wallet(user_id, wallet_address):
        await update.message.reply_text(
            f"❌ You're not monitoring this wallet.\n\nUse:\n\n/watch {wallet_address}\n\nto start monitoring."
        )
        return ConversationHandler.END
    
    # Validate filter type
    if not FilterEngine.validate_filter_type(filter_type):
        await update.message.reply_text(
            f"❌ Unknown filter.\n\nAvailable filters:\n"
            "  asset (e.g., BTC or BTC,ETH,DOGE)\n"
            "  side (BUY or SELL)\n"
            "  min_value (e.g., 100000)"
        )
        return ConversationHandler.END
    
    # Process based on filter type
    asset = None
    side = None
    min_value_usd = None
    
    if filter_type == "asset":
        asset = filter_value
    elif filter_type == "side":
        if not FilterEngine.validate_side(filter_value):
            await update.message.reply_text(
                "❌ Invalid side.\n\nUse:\n\nBUY\nor\nSELL"
            )
            return ConversationHandler.END
        side = filter_value
    elif filter_type == "min_value":
        min_value = FilterEngine.validate_min_value(filter_value)
        if min_value is None:
            await update.message.reply_text(
                f"❌ Invalid minimum value.\n\nExample:\n\n/filter {wallet_address} min_value 100000"
            )
            return ConversationHandler.END
        min_value_usd = min_value
    
    # Set the filter (only the specified filter)
    database.set_wallet_filter(user_id, wallet_address, asset=asset, side=side, min_value_usd=min_value_usd)
    
    # Get short wallet for display
    short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
    
    await update.message.reply_text(
        f"✅ Filter set\n\n{short_wallet}\n\n{filter_type.upper()}: {filter_value}"
    )
    
    logger.info(f"User {update.effective_user.id} set {filter_type} filter for wallet {wallet_address}")
    return ConversationHandler.END

async def filter_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start guided filter setup - show wallet selection with aliases"""
    user_id = database.get_or_create_user(update.effective_user.id)
    wallets = database.get_user_wallets_with_aliases(user_id)

    if not wallets:
        keyboard = [
            [InlineKeyboardButton("➕ Watch Wallet", callback_data="menu_watch")],
            [InlineKeyboardButton("❌ Cancel", callback_data="filter_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message = (
            "🔔 Set Alert Filter\n\n"
            "You're not monitoring any wallets yet.\n\n"
            "Use /watch to start monitoring a wallet first."
        )

        if update.callback_query:
            try:
                await update.callback_query.answer()
            except:
                pass  # Already answered by menu_handler
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, reply_markup=reply_markup)
        return ConversationHandler.END

    # Create inline keyboard with wallet buttons showing aliases
    keyboard = []
    for wallet_address, wallet_alias in wallets:
        display = database.format_wallet_display(wallet_address, wallet_alias)
        keyboard.append([InlineKeyboardButton(display, callback_data=f"filter_wallet_{wallet_address}")])

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="filter_cancel")])
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="menu_start")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    message = (
        "🔔 Set Alert Filter\n\n"
        "Which wallet do you want to configure?"
    )

    if update.callback_query:
        try:
            await update.callback_query.answer()
        except:
            pass  # Already answered by menu_handler
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup)

    return SELECT_WALLET

async def filter_wallet_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle wallet selection - show filter type options with alias"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = query.data.replace("filter_wallet_", "")
    context.user_data['filter_wallet'] = wallet_address
    
    user_id = database.get_or_create_user(update.effective_user.id)
    wallet_alias = database.get_wallet_alias(user_id, wallet_address)
    display = database.format_wallet_display(wallet_address, wallet_alias)
    
    keyboard = [
        [InlineKeyboardButton("🪙 Asset", callback_data="filter_type_asset")],
        [InlineKeyboardButton("↕️ Side", callback_data="filter_type_side")],
        [InlineKeyboardButton("💵 Minimum Value", callback_data="filter_type_min_value")],
        [InlineKeyboardButton("🧹 Clear Filters", callback_data="filter_clear")],
        [InlineKeyboardButton("✅ Done", callback_data="filter_done")],
        [InlineKeyboardButton("❌ Cancel", callback_data="filter_cancel")],
        [InlineKeyboardButton("◀️ Back", callback_data="menu_start")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🔔 Filters for\n\n{display}\n\n"
        "Select a filter to configure:",
        reply_markup=reply_markup
    )
    
    return SELECT_FILTER_TYPE

async def filter_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle filter type selection"""
    query = update.callback_query
    await query.answer()
    
    filter_type = query.data.replace("filter_type_", "")
    context.user_data['filter_type'] = filter_type
    
    if filter_type == "asset":
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="filter_cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🪙 Asset Filter\n\n"
            "Enter one or multiple assets.\n\n"
            "Examples:\n"
            "BTC\n"
            "BTC, ETH\n"
            "BTC, ETH, DOGE, PUMP\n\n"
            "Enter the assets you want to receive alerts for:",
            reply_markup=reply_markup
        )
        return ENTER_ASSET
    
    elif filter_type == "side":
        keyboard = [
            [InlineKeyboardButton("🟢 BUY", callback_data="filter_side_BUY")],
            [InlineKeyboardButton("🔴 SELL", callback_data="filter_side_SELL")],
            [InlineKeyboardButton("❌ Cancel", callback_data="filter_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "↕️ Trade Side\n\n"
            "Which trades do you want?",
            reply_markup=reply_markup
        )
        return SELECT_SIDE
    
    elif filter_type == "min_value":
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="filter_cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💵 Minimum Trade Value\n\n"
            "Enter the minimum trade value in USD.\n\n"
            "Example:\n10000\n\n"
            "This means you'll receive alerts for trades\n"
            "worth $10,000 or more.",
            reply_markup=reply_markup
        )
        return ENTER_MIN_VALUE
    
    return ConversationHandler.END

async def filter_asset_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle asset input"""
    asset = update.message.text.strip().upper()
    
    if not asset:
        await update.message.reply_text("❌ Asset cannot be empty.")
        return ENTER_ASSET
    
    wallet_address = context.user_data.get('filter_wallet')
    user_id = database.get_or_create_user(update.effective_user.id)
    
    # Set only the asset filter
    database.set_wallet_filter(user_id, wallet_address, asset=asset)
    
    short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Another Filter", callback_data=f"filter_type_add_{wallet_address}")],
        [InlineKeyboardButton("✅ Done", callback_data="filter_done")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Asset filter saved\n\n"
        f"Wallet: {short_wallet}\n"
        f"Asset: {asset}\n\n"
        f"Your other filters were kept unchanged.",
        reply_markup=reply_markup
    )
    
    logger.info(f"User {update.effective_user.id} set asset filter {asset} for wallet {wallet_address}")
    return SELECT_FILTER_TYPE

async def filter_side_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle side selection"""
    query = update.callback_query
    await query.answer()
    
    side = query.data.replace("filter_side_", "")
    wallet_address = context.user_data.get('filter_wallet')
    user_id = database.get_or_create_user(update.effective_user.id)
    
    # Set only the side filter
    database.set_wallet_filter(user_id, wallet_address, side=side)
    
    short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Another Filter", callback_data=f"filter_type_add_{wallet_address}")],
        [InlineKeyboardButton("✅ Done", callback_data="filter_done")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"✅ Side filter saved\n\n"
        f"Wallet: {short_wallet}\n"
        f"Side: {side}\n\n"
        f"Your other filters were kept unchanged.",
        reply_markup=reply_markup
    )
    
    logger.info(f"User {update.effective_user.id} set side filter {side} for wallet {wallet_address}")
    return SELECT_FILTER_TYPE

async def filter_min_value_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle minimum value input"""
    value_str = update.message.text.strip()
    min_value = FilterEngine.validate_min_value(value_str)
    
    if min_value is None:
        await update.message.reply_text(
            "❌ Invalid minimum value.\n\n"
            "Please enter a valid number, e.g., 10000"
        )
        return ENTER_MIN_VALUE
    
    wallet_address = context.user_data.get('filter_wallet')
    user_id = database.get_or_create_user(update.effective_user.id)
    
    # Set only the minimum value filter
    database.set_wallet_filter(user_id, wallet_address, min_value_usd=min_value)
    
    short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Another Filter", callback_data=f"filter_type_add_{wallet_address}")],
        [InlineKeyboardButton("✅ Done", callback_data="filter_done")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Minimum value filter saved\n\n"
        f"Wallet: {short_wallet}\n"
        f"Minimum Value: ${min_value:,.0f}\n\n"
        f"Your other filters were kept unchanged.",
        reply_markup=reply_markup
    )
    
    logger.info(f"User {update.effective_user.id} set min_value filter {min_value} for wallet {wallet_address}")
    return SELECT_FILTER_TYPE

async def filter_add_another(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle adding another filter after setting one"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = query.data.replace("filter_type_add_", "")
    context.user_data['filter_wallet'] = wallet_address
    
    short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
    
    keyboard = [
        [InlineKeyboardButton("🪙 Asset", callback_data="filter_type_asset")],
        [InlineKeyboardButton("↕️ Side", callback_data="filter_type_side")],
        [InlineKeyboardButton("💵 Minimum Value", callback_data="filter_type_min_value")],
        [InlineKeyboardButton("🧹 Clear Filters", callback_data="filter_clear")],
        [InlineKeyboardButton("✅ Done", callback_data="filter_done")],
        [InlineKeyboardButton("❌ Cancel", callback_data="filter_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🔧 Choose a filter\n\n"
        f"Wallet:\n{short_wallet}",
        reply_markup=reply_markup
    )
    
    return SELECT_FILTER_TYPE

async def filter_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle filter setup completion"""
    query = update.callback_query
    await query.answer()
    
    # Return to main dashboard
    await start(update, context)
    return ConversationHandler.END

async def filter_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle filter setup cancellation"""
    query = update.callback_query
    await query.answer()
    
    # Return to main dashboard
    await start(update, context)
    return ConversationHandler.END

async def filter_clear_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle clear filters selection - show confirmation"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = context.user_data.get('filter_wallet')
    if not wallet_address:
        await query.edit_message_text("❌ Error: Wallet not found.")
        return ConversationHandler.END
    
    user_id = database.get_or_create_user(update.effective_user.id)
    wallet_alias = database.get_wallet_alias(user_id, wallet_address)
    display = database.format_wallet_display(wallet_address, wallet_alias)
    
    keyboard = [
        [InlineKeyboardButton("✅ Clear Filters", callback_data="filter_confirm_clear")],
        [InlineKeyboardButton("❌ Cancel", callback_data="filter_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🧹 Clear filters for\n\n{display}\n\n"
        "This will remove all filters for this wallet.",
        reply_markup=reply_markup
    )
    
    return SELECT_FILTER_TYPE

async def filter_confirm_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle clear filters confirmation"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = context.user_data.get('filter_wallet')
    if not wallet_address:
        await query.edit_message_text("❌ Error: Wallet not found.")
        return ConversationHandler.END
    
    user_id = database.get_or_create_user(update.effective_user.id)
    
    if database.clear_wallet_filter(user_id, wallet_address):
        wallet_alias = database.get_wallet_alias(user_id, wallet_address)
        display = database.format_wallet_display(wallet_address, wallet_alias)
        
        await query.edit_message_text(
            f"✅ Filters cleared for\n\n{display}"
        )
    else:
        await query.edit_message_text("❌ No filters to clear for this wallet.")
    
    return ConversationHandler.END

async def filters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /filters command - show with button UX"""
    user_id = database.get_or_create_user(update.effective_user.id)
    
    # Get user's wallets with filters
    wallet_filters = database.get_user_wallets_with_filters(user_id)
    
    if not wallet_filters:
        await update.message.reply_text(
            "⚙️ FILTERS\n\n"
            "You aren't monitoring any wallets yet.\n\n"
            "Use:\n\n/watch <wallet>\n\nto start monitoring."
        )
        return
    
    # If only one wallet, show its filters with buttons
    if len(wallet_filters) == 1:
        wallet_address, wallet_alias, asset, side, min_value = wallet_filters[0]
        display = database.format_wallet_display(wallet_address, wallet_alias)
        
        response_lines = [f"🔔 Alert Filters\n\nWallet:\n{display}\n\nActive filters:\n"]
        
        has_filters = False
        
        if asset:
            response_lines.append(f"🪙 Asset: {asset}")
            has_filters = True
        
        if side:
            response_lines.append(f"↕️ Side: {side}")
            has_filters = True
        
        if min_value:
            response_lines.append(f"💵 Minimum Value: ${min_value:,.0f}")
            has_filters = True
        
        if not has_filters:
            response_lines.append("No filters are configured.\n\nYou'll receive alerts for all supported trades.")
            keyboard = [
                [InlineKeyboardButton("➕ Add Filter", callback_data=f"filter_type_add_{wallet_address}")],
                [InlineKeyboardButton("⬅️ Back", callback_data="filters_back")]
            ]
        else:
            response_lines.append("\nAll active filters must match.")
            
            # Add explanation of what's not filtered
            if not asset:
                response_lines.append("\nNo Asset filter - all assets included")
            if not side:
                response_lines.append("No Side filter - both BUY and SELL included")
            if not min_value:
                response_lines.append("No Minimum Value filter - all trade values included")
            
            keyboard = [
                [InlineKeyboardButton("✏️ Change Filters", callback_data=f"filter_type_add_{wallet_address}")],
                [InlineKeyboardButton("🗑 Clear Filters", callback_data=f"filter_clear_{wallet_address}")],
                [InlineKeyboardButton("⬅️ Back", callback_data="filters_back")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("\n".join(response_lines), reply_markup=reply_markup)
        logger.info(f"User {update.effective_user.id} requested their filters")
    else:
        # Multiple wallets - show list
        response_lines = ["⚙️ YOUR FILTERS\n"]
        
        for wallet_address, wallet_alias, asset, side, min_value in wallet_filters:
            display = database.format_wallet_display(wallet_address, wallet_alias)
            response_lines.append(f"Wallet:\n{display}")
            
            has_filters = False
            
            if asset:
                response_lines.append(f"🪙 Asset: {asset}")
                has_filters = True
            
            if side:
                response_lines.append(f"↕️ Side: {side}")
                has_filters = True
            
            if min_value:
                response_lines.append(f"💵 Minimum Value: ${min_value:,.0f}")
                has_filters = True
            
            if not has_filters:
                response_lines.append("No filters configured")
                response_lines.append("All supported trade activity will generate alerts.")
            
            response_lines.append("")
        
        await update.message.reply_text("\n".join(response_lines))
        logger.info(f"User {update.effective_user.id} requested their filters")

async def filters_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button interactions from /filters"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "filters_back":
        await start(update, context)
        return
    
    if query.data.startswith("filter_clear_"):
        wallet_address = query.data.replace("filter_clear_", "")
        short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
        
        keyboard = [
            [InlineKeyboardButton("✅ Clear Filters", callback_data=f"filter_confirm_clear_{wallet_address}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="filters_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚠️ Clear Filters?\n\n"
            f"This will remove all alert filters for:\n\n{short_wallet}\n\n"
            f"After clearing, alerts for this wallet will include\n"
            f"all supported trades.",
            reply_markup=reply_markup
        )
        return
    
    if query.data.startswith("filter_confirm_clear_"):
        wallet_address = query.data.replace("filter_confirm_clear_", "")
        user_id = database.get_or_create_user(update.effective_user.id)
        
        database.clear_wallet_filter(user_id, wallet_address)
        
        short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
        
        await query.edit_message_text(
            f"✅ Filters cleared\n\n{short_wallet}\n\n"
            f"All supported trade activity will now generate alerts."
        )
        logger.info(f"User {update.effective_user.id} cleared filters for wallet {wallet_address}")
        return
    
    if query.data.startswith("filter_type_add_"):
        wallet_address = query.data.replace("filter_type_add_", "")
        context.user_data['filter_wallet'] = wallet_address
        
        short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
        
        keyboard = [
            [InlineKeyboardButton("🪙 Asset", callback_data="filter_type_asset")],
            [InlineKeyboardButton("↕️ Side", callback_data="filter_type_side")],
            [InlineKeyboardButton("💵 Minimum Value", callback_data="filter_type_min_value")],
            [InlineKeyboardButton("❌ Cancel", callback_data="filters_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🔧 Choose a filter\n\n"
            f"Wallet:\n{short_wallet}",
            reply_markup=reply_markup
        )
        return

async def clearfilters_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clearfilters command - starts guided flow if no args, otherwise uses legacy syntax"""
    logger.info(f"Clearfilters command received from user {update.effective_user.id}, args: {context.args}")
    
    # If no arguments, start guided flow (return state to start conversation)
    if not context.args:
        logger.info("Starting guided clearfilters flow")
        return await clearfilters_start(update, context)
    
    # Legacy syntax: /clearfilters <wallet>
    # Return ConversationHandler.END to exit conversation immediately
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /clearfilters <wallet>")
        return ConversationHandler.END
    
    wallet_address = context.args[0]
    
    # Validate wallet address
    if not wallet_address.startswith("0x") or len(wallet_address) != 42:
        await update.message.reply_text("Invalid wallet address. Must be a 42-character hex string starting with 0x")
        return ConversationHandler.END
    
    # Check if user watches this wallet
    user_id = database.get_or_create_user(update.effective_user.id)
    if not database.user_watches_wallet(user_id, wallet_address):
        await update.message.reply_text(
            f"❌ You're not monitoring this wallet.\n\nUse:\n\n/watch {wallet_address}\n\nto start monitoring."
        )
        return ConversationHandler.END
    
    # Clear the filter
    cleared = database.clear_wallet_filter(user_id, wallet_address)
    
    if cleared:
        wallet_alias = database.get_wallet_alias(user_id, wallet_address)
        display = database.format_wallet_display(wallet_address, wallet_alias)
        await update.message.reply_text(
            f"✅ Filters cleared\n\n{display}\n\nAll supported trade activity will now generate alerts."
        )
        logger.info(f"User {update.effective_user.id} cleared filters for wallet {wallet_address}")
    else:
        await update.message.reply_text("No filters were configured for this wallet.")

async def clearfilters_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start guided clear filters - show wallet selection with aliases"""
    user_id = database.get_or_create_user(update.effective_user.id)
    wallets = database.get_user_wallets_with_aliases(user_id)
    
    if not wallets:
        keyboard = [
            [InlineKeyboardButton("➕ Watch Wallet", callback_data="menu_watch")],
            [InlineKeyboardButton("❌ Cancel", callback_data="clearfilters_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🧹 Clear Filters\n\n"
            "You're not monitoring any wallets yet.\n\n"
            "Use /watch to start monitoring a wallet first.",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    
    # Create inline keyboard with wallet buttons showing aliases
    keyboard = []
    for wallet_address, wallet_alias in wallets:
        display = database.format_wallet_display(wallet_address, wallet_alias)
        keyboard.append([InlineKeyboardButton(display, callback_data=f"clearfilters_wallet_{wallet_address}")])
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="clearfilters_cancel")])
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="menu_start")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🧹 Select wallet to clear filters\n\n",
        reply_markup=reply_markup
    )
    
    return CLEARFILTERS_ENTER_ADDRESS

async def clearfilters_wallet_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle wallet selection - show confirmation"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = query.data.replace("clearfilters_wallet_", "")
    context.user_data['clearfilters_wallet'] = wallet_address
    
    user_id = database.get_or_create_user(update.effective_user.id)
    wallet_alias = database.get_wallet_alias(user_id, wallet_address)
    display = database.format_wallet_display(wallet_address, wallet_alias)
    
    keyboard = [
        [InlineKeyboardButton("✅ Clear Filters", callback_data="clearfilters_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="clearfilters_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🧹 Clear filters for\n\n{display}\n\n"
        "This will remove all filters for this wallet.",
        reply_markup=reply_markup
    )
    
    return CLEARFILTERS_CONFIRM

async def clearfilters_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle clear filters confirmation"""
    query = update.callback_query
    await query.answer()
    
    wallet_address = context.user_data.get('clearfilters_wallet')
    if not wallet_address:
        await query.edit_message_text("❌ Error: wallet address not found.")
        return ConversationHandler.END
    
    user_id = database.get_or_create_user(update.effective_user.id)
    
    # Clear the filter
    cleared = database.clear_wallet_filter(user_id, wallet_address)
    
    short_wallet = wallet_address[:6] + "..." + wallet_address[-4:]
    
    if cleared:
        await query.edit_message_text(
            f"✅ Filters cleared\n\n{short_wallet}\n\n"
            f"All supported trade activity will now generate alerts."
        )
        logger.info(f"User {update.effective_user.id} cleared filters for wallet {wallet_address}")
    else:
        await query.edit_message_text("No filters were configured for this wallet.")
    
    return ConversationHandler.END

async def clearfilters_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle clear filters cancellation"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text("❌ Clear filters cancelled.")
    return ConversationHandler.END

async def handle_wallet_event(fill: dict, wallet_address: str, event_key: str):
    """Handle wallet events from subscription manager"""
    global application, is_shutting_down
    
    try:
        # Check if event was already processed (deduplication)
        if database.is_event_processed(event_key):
            logger.info(f"Event {event_key} already processed, skipping")
            return
        
        # Mark event as processed
        database.mark_event_processed(event_key, wallet_address)
        
        # Get all subscribers for this wallet
        subscribers = database.get_wallet_subscribers(wallet_address)
        
        if not subscribers:
            logger.info(f"No subscribers for wallet {wallet_address}")
            return
        
        logger.info(f"Sending alert to {len(subscribers)} subscribers for wallet {wallet_address}")
        
        # Send alert to each subscriber, respecting their filters
        for chat_id in subscribers:
            try:
                # Check if application is shutting down - prevent alert sends
                if is_shutting_down:
                    logger.info(f"Application shutting down, skipping alert to user {chat_id}")
                    continue
                
                # Get user's filter for this wallet
                user_id_db = database.get_or_create_user(chat_id)
                filters = database.get_wallet_filter(user_id_db, wallet_address)
                
                # Check if event matches user's filters
                if FilterEngine.matches_filters(fill, filters):
                    message = format_telegram_message(fill, wallet_address)
                    if message and application and main_event_loop:
                        # Schedule the bot call on the main event loop to avoid event loop mismatch
                        import concurrent.futures
                        try:
                            future = asyncio.run_coroutine_threadsafe(
                                application.bot.send_message(chat_id=chat_id, text=message),
                                main_event_loop
                            )
                            # Wait for the result with a timeout
                            future.result(timeout=5.0)
                            logger.info(f"Alert sent to user {chat_id}")
                            # Record alert in database for admin dashboard
                            database.record_alert(user_id_db, wallet_address)
                        except concurrent.futures.TimeoutError:
                            logger.warning(f"Timeout sending alert to user {chat_id}")
                        except (RuntimeError, AttributeError) as e:
                            if "HTTPXRequest" in str(e) or "event loop" in str(e) or "not initialized" in str(e) or "closed" in str(e):
                                logger.warning(f"Cannot send alert - application likely shutting down: {type(e).__name__}")
                            else:
                                raise
                    elif message and application and not main_event_loop:
                        logger.info(f"Skipping alert to user {chat_id} - main event loop closed (shutdown in progress)")
                else:
                    logger.info(f"Event filtered for user {chat_id} (wallet {wallet_address})")
            except Exception as e:
                logger.error(f"Failed to send alert to user {chat_id}: {e}")
                
    except Exception as e:
        logger.error(f"Error handling wallet event: {e}")

def format_telegram_message(fill: dict, wallet_address: str):
    """Format Telegram message from fill data"""
    try:
        coin = fill.get("coin", "Unknown")
        side = fill.get("side", "Unknown")
        size = fill.get("sz", "Unknown")
        price = fill.get("px", "Unknown")
        time_ms = fill.get("time", 0)
        
        # Format timestamp
        if time_ms:
            time_str = datetime.fromtimestamp(time_ms / 1000).strftime("%H:%M:%S UTC")
        else:
            time_str = "Unknown"
        
        # Format price
        try:
            price_float = float(price)
            price_formatted = f"${price_float:,.2f}"
        except (ValueError, TypeError):
            price_formatted = str(price)
        
        # Format side with emoji
        side_emoji = "🟢 BUY" if side.upper() == "B" else "🔴 SELL"
        
        # Build message
        message = f"""🔔 NEW HYPERLIQUID ACTIVITY

Wallet:
{wallet_address[:6]}...{wallet_address[-4:]}

{coin}

{side_emoji}

Size: {size} {coin}
Price: {price_formatted}

Time: {time_str}"""
        
        return message
        
    except Exception as e:
        logger.error(f"Error formatting Telegram message: {e}")
        return None

def restore_subscriptions():
    """Restore wallet subscriptions from database on startup"""
    global subscription_manager
    
    # Get all active wallets from database
    active_wallets = database.get_all_active_wallets()
    
    logger.info(f"Restoring subscriptions for {len(active_wallets)} wallets")
    
    # Add each wallet to subscription manager (synchronously for startup)
    for wallet_address in active_wallets:
        subscription_manager.subscribed_wallets.add(wallet_address.lower())
    
    logger.info("Subscription restoration complete")

def run_subscription_manager():
    """Run subscription manager in a separate event loop"""
    global subscription_manager, monitoring_shutdown_event
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(subscription_manager.start_monitoring())
    except Exception as e:
        logger.error(f"Subscription manager error: {e}")
    finally:
        loop.close()
        # Signal that monitoring thread has exited
        if monitoring_shutdown_event:
            monitoring_shutdown_event.set()

def ensure_monitoring_running():
    """Ensure the subscription manager is running"""
    global subscription_manager
    
    if not subscription_manager.monitoring_active and subscription_manager.subscribed_wallets:
        logger.info("Starting subscription manager monitoring thread")
        import threading
        monitoring_thread = threading.Thread(
            target=run_subscription_manager,
            daemon=True
        )
        monitoring_thread.start()

async def post_init(application: Application) -> None:
    """Register bot commands with Telegram after application initialization"""
    global main_event_loop
    # Capture the main event loop reference here
    main_event_loop = asyncio.get_running_loop()
    logger.info("Main event loop captured for cross-thread Telegram calls")
    
    await application.bot.set_my_commands([
        ("start", "Start the bot"),
        ("help", "Show help message"),
        ("watch", "Monitor a wallet"),
        ("unwatch", "Stop monitoring a wallet"),
        ("wallets", "List your watched wallets"),
        ("status", "Check monitoring status"),
        ("filters", "View your filters"),
        ("clearfilters", "Clear filters for a wallet")
    ])

def main():
    """Main function to run the bot"""
    global subscription_manager, application, is_shutting_down, monitoring_shutdown_event, main_event_loop
    import threading
    
    logger.info("Bot started")
    
    # Create shutdown event for monitoring thread coordination
    monitoring_shutdown_event = threading.Event()
    
    # Create subscription manager
    subscription_manager = WalletSubscriptionManager(
        HYPERLIQUID_WS_URL,
        handle_wallet_event
    )
    
    # Restore subscriptions from database
    restore_subscriptions()
    
    monitoring_thread = None
    # Start monitoring if there are wallets to watch
    if subscription_manager.subscribed_wallets:
        # Start monitoring in background thread
        monitoring_thread = threading.Thread(
            target=run_subscription_manager,
            daemon=True
        )
        monitoring_thread.start()
        logger.info("Subscription manager thread started")
    else:
        logger.info("No wallets to monitor at startup, will start when wallets are added")
    
    # Create Telegram application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    # Create watch conversation handler
    watch_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("watch", watch),
            CallbackQueryHandler(watch_start, pattern="^menu_watch$")
        ],
        states={
            WATCH_ENTER_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, watch_address_entered),
                CallbackQueryHandler(watch_cancel, pattern="^watch_cancel$")
            ],
            WATCH_ENTER_ALIAS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, watch_alias_entered),
                CallbackQueryHandler(watch_skip_alias, pattern="^watch_skip_alias$"),
                CallbackQueryHandler(watch_cancel, pattern="^watch_cancel$")
            ],
        },
        fallbacks=[CallbackQueryHandler(watch_cancel, pattern="^watch_cancel$")],
        per_message=False,
        block=False
    )

    # Create alias editing conversation handler
    alias_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(alias_select_wallet, pattern="^alias_wallet_")],
        states={
            ALIAS_ENTER_ALIAS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, alias_enter_alias),
                CallbackQueryHandler(alias_cancel, pattern="^alias_cancel$")
            ],
        },
        fallbacks=[CallbackQueryHandler(alias_cancel, pattern="^alias_cancel$")],
        per_message=False,
        block=False
    )
    
    # Create clearfilters conversation handler
    clearfilters_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("clearfilters", clearfilters_command)],
        states={
            CLEARFILTERS_ENTER_ADDRESS: [
                CallbackQueryHandler(clearfilters_wallet_selected, pattern="^clearfilters_wallet_"),
                CallbackQueryHandler(clearfilters_cancel, pattern="^clearfilters_cancel$")
            ],
            CLEARFILTERS_CONFIRM: [
                CallbackQueryHandler(clearfilters_confirm, pattern="^clearfilters_confirm"),
                CallbackQueryHandler(clearfilters_cancel, pattern="^clearfilters_cancel$")
            ],
        },
        fallbacks=[CallbackQueryHandler(clearfilters_cancel, pattern="^clearfilters_cancel$")],
        per_message=False,
        block=False
    )

    # Create unwatch conversation handler
    unwatch_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("unwatch", unwatch)],
        states={
            UNWATCH_SELECT_WALLET: [
                CallbackQueryHandler(unwatch_wallet_selected, pattern="^unwatch_wallet_"),
                CallbackQueryHandler(unwatch_cancel, pattern="^menu_start$")
            ],
            UNWATCH_CONFIRM: [
                CallbackQueryHandler(unwatch_confirm_selected, pattern="^unwatch_confirm_"),
                CallbackQueryHandler(unwatch_cancel, pattern="^menu_start$")
            ],
        },
        fallbacks=[CallbackQueryHandler(unwatch_cancel, pattern="^menu_start$")],
        per_message=False,
        block=False
    )
    
    # Create filter conversation handler - ONLY for guided mode (no arguments)
    # Legacy mode with arguments is handled directly by filter_command function
    filter_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(filter_start, pattern="^menu_filters$"),
            CallbackQueryHandler(filter_add_another, pattern="^filter_type_add_")
        ],
        states={
            SELECT_WALLET: [CallbackQueryHandler(filter_wallet_selected, pattern="^filter_wallet_")],
            SELECT_FILTER_TYPE: [
                CallbackQueryHandler(filter_type_selected, pattern="^filter_type_"),
                CallbackQueryHandler(filter_clear_selected, pattern="^filter_clear$"),
                CallbackQueryHandler(filter_confirm_clear, pattern="^filter_confirm_clear"),
                CallbackQueryHandler(filter_cancel, pattern="^filter_cancel$")
            ],
            ENTER_ASSET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, filter_asset_entered),
                CallbackQueryHandler(filter_cancel, pattern="^filter_cancel$")
            ],
            SELECT_SIDE: [
                CallbackQueryHandler(filter_side_selected, pattern="^filter_side_"),
                CallbackQueryHandler(filter_cancel, pattern="^filter_cancel$")
            ],
            ENTER_MIN_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, filter_min_value_entered),
                CallbackQueryHandler(filter_cancel, pattern="^filter_cancel$")
            ],
        },
        fallbacks=[
            CallbackQueryHandler(filter_cancel, pattern="^filter_cancel$"),
            CallbackQueryHandler(filter_done, pattern="^filter_done$")
        ],
        per_message=False,
        block=False,
        name="filter_conversation"
    )
    
    # Add command handlers - ConversationHandlers must be added before simple CommandHandlers
    # Register conversation handlers first to ensure they capture their commands
    application.add_handler(watch_conv_handler)
    application.add_handler(alias_conv_handler)
    application.add_handler(filter_conv_handler)
    application.add_handler(clearfilters_conv_handler)
    application.add_handler(unwatch_conv_handler)
    
    # Then register simple command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("unwatch", unwatch))
    application.add_handler(CommandHandler("wallets", wallets))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("filters", filters_command))

    # Add button handlers
    # menu_handler excludes menu_filters and menu_watch since those are handled by conversation handlers
    application.add_handler(CallbackQueryHandler(menu_handler, pattern="^(menu_wallets|menu_help|menu_start)$"))
    application.add_handler(CallbackQueryHandler(wallet_management_handler, pattern="^(wallet_manage_|wallet_filter_|wallet_unwatch_|unwatch_confirm_|unwatch_wallet_)"))
    application.add_handler(CallbackQueryHandler(filters_button_handler, pattern="^(filters_back|filter_clear_|filter_confirm_clear_)"))
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^(admin_refresh|menu_start)$"))
    
    # Start the bot
    try:
        application.run_polling()
    finally:
        # Cleanup on shutdown
        logger.info("Starting shutdown sequence")
        
        # Step 1: Set shutdown flag FIRST to prevent new alert sends
        is_shutting_down = True
        logger.info("Shutdown flag set - preventing new alert sends")
        
        # Step 2: Clear main event loop reference to prevent cross-thread calls during shutdown
        main_event_loop = None
        logger.info("Main event loop reference cleared")
        
        # Step 3: Stop subscription manager to prevent new events
        if subscription_manager:
            logger.info("Stopping subscription manager")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(subscription_manager.stop_monitoring())
            except Exception as e:
                logger.error(f"Error stopping subscription manager: {e}")
            finally:
                loop.close()
        
        # Step 4: Wait for monitoring thread to exit
        if monitoring_thread and monitoring_thread.is_alive():
            logger.info("Waiting for monitoring thread to exit...")
            monitoring_thread.join(timeout=5.0)
            if monitoring_thread.is_alive():
                logger.warning("Monitoring thread did not exit cleanly")
            else:
                logger.info("Monitoring thread exited cleanly")
        
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")