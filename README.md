# Hyperliquid Telegram Wallet Monitor - V1

A reliable multi-wallet Telegram bot that monitors Hyperliquid wallets and sends alerts when new trading activity is detected, with user-configurable alert filters.

## Requirements

- Python 3.8 or higher

## Installation

1. Clone the repository:
```bash
cd Hyperliquid_monitor_bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
cp .env.example .env
```

Edit `.env` and add your configuration:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
ADMIN_USER_ID=your_telegram_user_id
```

**Important:**
- `TELEGRAM_BOT_TOKEN`: Get this from [@BotFather](https://t.me/BotFather) on Telegram
- `ADMIN_USER_ID`: Your numeric Telegram user ID (required for admin commands like `/admin` and `/status`)

To find your Telegram user ID, message [@userinfobot](https://t.me/userinfobot) on Telegram.

## Usage

### Start the Bot

```bash
python main.py
```

### Telegram Commands

#### `/start`
Displays the main menu with buttons for adding wallets, viewing your wallets, configuring alerts, and help.

#### `/help`
Shows available commands and usage instructions.

#### `/watch <wallet_address>` or **➕ Add Wallet** button
Starts monitoring a Hyperliquid wallet for trading activity.

Example:
```
/watch 0x1234567890abcdef1234567890abcdef12345678
```

The bot will:
1. Validate the wallet address (must be 42 characters starting with 0x)
2. Optionally ask for a wallet alias
3. Add the wallet to your watchlist (persisted in database)
4. Connect to the Hyperliquid WebSocket API if not already connected
5. Subscribe to the wallet's fill events
6. Send Telegram alerts when new trading activity is detected

#### `/unwatch <wallet_address>` or **My Wallets → Unwatch**
Stop monitoring a specific wallet.

#### `/wallets` or **👀 My Wallets** button
Display your current watchlist with options to edit aliases, configure filters, or unwatch.

#### `/admin` (admin only)
Display the admin dashboard with system statistics (users, wallets, alerts, monitoring status).

Only accessible to the configured admin user.

#### `/status` (admin only)
Display detailed monitoring status (connection, subscriptions, activity).

Only accessible to the configured admin user.

#### `/filter <wallet> <filter_type> <value>` or **🔔 Alerts** button
Set alert filters for a watched wallet.

Available filter types:
- `asset` - Filter by token (e.g., BTC, ETH, or BTC,ETH,DOGE for multiple)
- `side` - Filter by side (BUY or SELL)
- `min_value` - Minimum USD trade value (e.g., 100000)

Examples:
```
/filter 0x1234... asset BTC
/filter 0x1234... asset BTC,ETH,DOGE
/filter 0x1234... side SELL
/filter 0x1234... min_value 100000
```

Multiple filters can be combined using AND logic. For example:
```
/filter 0x1234... asset BTC
/filter 0x1234... side SELL
/filter 0x1234... min_value 100000
```
This will only alert for BTC SELL trades worth $100,000 or more.

#### `/filters` or **🔔 Alerts → View Filters**
Display your configured filters for all watched wallets.

#### `/clearfilters <wallet>` or **🔔 Alerts → Clear Filters**
Clear all filters for a watched wallet.

Removes all filters and returns to alerting on all supported trade activity for that wallet.

## How It Works

1. **Multi-User Support**: Multiple Telegram users can use the bot simultaneously, each with their own watchlists
2. **Multi-Wallet Monitoring**: Each user can monitor multiple wallets
3. **Shared Subscriptions**: If multiple users watch the same wallet, only one Hyperliquid subscription is maintained
4. **Event Routing**: Wallet events are routed only to users who are watching that specific wallet
5. **Database Persistence**: Watchlists and filters are stored in SQLite and survive application restarts
6. **Event Deduplication**: Prevents duplicate alerts for the same event using event fingerprinting
7. **Automatic Reconnection**: WebSocket connections automatically reconnect with exponential backoff
8. **Subscription Restoration**: After restart or reconnection, all wallet subscriptions are automatically restored
9. **Snapshot Handling**: Initial snapshots from Hyperliquid are ignored to prevent historical activity alerts
10. **Real-time Monitoring**: Only new fills trigger Telegram alerts
11. **User-Configurable Filters**: Users can set per-wallet filters for asset, side, and minimum trade value
12. **Independent Filter Evaluation**: Each user's filters are evaluated independently, allowing different users to receive different alerts for the same wallet

## Features

- ✅ Multi-user support with individual watchlists
- ✅ Multi-wallet monitoring per user
- ✅ Shared Hyperliquid subscriptions for efficiency
- ✅ SQLite database for persistent storage
- ✅ Event deduplication to prevent duplicate alerts
- ✅ Automatic WebSocket reconnection with exponential backoff
- ✅ Automatic subscription restoration after restart
- ✅ `/start`, `/help`, `/watch`, `/unwatch`, `/wallets`, `/status` commands
- ✅ `/filter`, `/filters`, `/clearfilters` commands for alert filtering
- ✅ Asset filter (filter by token such as BTC, ETH)
- ✅ Side filter (filter by BUY or SELL)
- ✅ Minimum trade value filter (filter by USD value)
- ✅ AND logic for combined filters
- ✅ Per-user, per-wallet filter configuration
- ✅ Real-time Hyperliquid WebSocket connection
- ✅ User fills subscription
- ✅ Initial snapshot filtering (no historical alerts)
- ✅ Formatted Telegram alerts for new activity
- ✅ Comprehensive error handling and logging
- ✅ Wallet address normalization (case-insensitive)

## Database Schema

The application uses SQLite with the following tables:

### users
- `id` (INTEGER PRIMARY KEY)
- `telegram_id` (INTEGER UNIQUE) - Telegram user ID
- `created_at` (TIMESTAMP)

### watched_wallets
- `id` (INTEGER PRIMARY KEY)
- `user_id` (INTEGER) - Foreign key to users
- `wallet_address` (TEXT) - Lowercase wallet address
- `enabled` (BOOLEAN) - Whether wallet is actively monitored
- `created_at` (TIMESTAMP)
- UNIQUE constraint on (user_id, wallet_address)

### processed_events
- `id` (INTEGER PRIMARY KEY)
- `event_key` (TEXT UNIQUE) - SHA256 hash for deduplication
- `wallet_address` (TEXT) - Associated wallet
- `created_at` (TIMESTAMP)

### wallet_filters
- `id` (INTEGER PRIMARY KEY)
- `user_id` (INTEGER) - Foreign key to users
- `wallet_address` (TEXT) - Associated wallet
- `asset` (TEXT) - Optional asset filter (e.g., BTC)
- `side` (TEXT) - Optional side filter (BUY or SELL)
- `min_value_usd` (REAL) - Optional minimum USD trade value
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)
- UNIQUE constraint on (user_id, wallet_address)

## Alert Format

When new wallet activity is detected, the bot sends:

```
🔔 NEW HYPERLIQUID ACTIVITY

Wallet:
0x1234...abcd

BTC

🟢 BUY

Size: 0.25 BTC
Price: $108,420

Time: 10:42:18 UTC
```

## Architecture

```
                 Hyperliquid WebSocket
                      │
                      ▼
               Wallet Subscription Manager
                      │
             ┌────────┼────────┐
             ▼        ▼        ▼
          Wallet A Wallet B Wallet C
             │        │        │
             └────────┼────────┘
                      ▼
                Event Handler + Deduplication
                      │
              ┌───────┴───────┐
              ▼               ▼
          Telegram A       Telegram B
```

## Logging

The bot logs important events:
- Bot started
- Database operations
- WebSocket connection status
- Subscription management
- Event processing and deduplication
- Telegram message delivery
- Error conditions

**Note**: The Telegram bot token is never logged for security.

## Testing

Run the automated test suite:

```bash
python test_event_processing.py
python test_phase1b.py
python test_phase2b.py
python test_phase2c.py
python test_phase2c_simple.py
python test_phase2d.py
```

## Database Backup

To backup your SQLite database:

```bash
cp hyperliquid_monitor.db hyperliquid_monitor.db.backup
```

To restore from backup:

```bash
cp hyperliquid_monitor.db.backup hyperliquid_monitor.db
```

## Token Rotation

If you need to rotate your Telegram bot token:

1. Open [@BotFather](https://t.me/BotFather) on Telegram
2. Use `/revoke` command
3. Select your bot
4. Generate a new token
5. Update `TELEGRAM_BOT_TOKEN` in your `.env` file
6. Restart the bot

**Important:** Always rotate tokens through BotFather. Never share or reuse tokens.

## Known Limitations

- Manual Telegram testing required for full validation of button flows
- Some conversation flow tests are skipped due to in-memory database initialization issues
- WebSocket reconnection may take up to 60 seconds with exponential backoff
- Alert suppression during filter configuration was removed (alerts continue normally during setup)

## Security Notes

- Never commit the `.env` file to version control
- The `.env` file and database files are included in `.gitignore`
- The bot token is never logged or printed (TokenRedactor class)
- No private keys or trading credentials are requested or stored
- This is a monitoring-only application with no trading capabilities
- Admin commands (`/admin`, `/status`) are protected by ADMIN_USER_ID

## Troubleshooting

- Ensure your `.env` file contains a valid Telegram bot token
- Make sure wallet addresses are valid 42-character hex strings starting with 0x
- Check that the bot has internet connectivity for WebSocket connections
- Verify the bot token has appropriate permissions
- Database file will be created automatically on first run
- Check logs for detailed error information

## Security

- Never commit the `.env` file to version control
- The `.env` file and database files are included in `.gitignore`
- The bot token is never logged or printed
- No private keys or trading credentials are requested or stored
- This is a monitoring-only application with no trading capabilities

## Phase 1B Improvements over Phase 1A

- **Multi-User Support**: Multiple Telegram users can use the bot independently
- **Multi-Wallet Support**: Each user can monitor multiple wallets simultaneously
- **Persistent Storage**: Watchlists survive application restarts via SQLite database
- **Shared Subscriptions**: Efficient WebSocket subscription management when multiple users watch the same wallet
- **Event Deduplication**: Prevents duplicate alerts using event fingerprinting
- **Automatic Reconnection**: Robust WebSocket handling with exponential backoff
- **Subscription Restoration**: Automatic recovery of all subscriptions after restart or reconnection
- **Enhanced Commands**: Added `/unwatch`, `/wallets`, `/status`, and `/help` commands
- **Better Architecture**: Separated concerns with dedicated database and subscription manager modules

## Phase 2A Improvements over Phase 1B

- **Alert Filtering**: Users can configure per-wallet filters to control which events generate alerts
- **Asset Filter**: Filter alerts by specific tokens (e.g., only BTC trades)
- **Side Filter**: Filter alerts by trade direction (BUY or SELL)
- **Minimum Value Filter**: Filter alerts by minimum USD trade value
- **Combined Filters**: Multiple filters can be combined using AND logic
- **Per-User Configuration**: Each user can have different filters for the same wallet
- **Filter Persistence**: Filter configurations survive application restarts
- **Filter Management Commands**: Added `/filter`, `/filters`, and `/clearfilters` commands
- **Filter Engine**: Dedicated module for deterministic filter evaluation
- **WebSocket Unaffected**: Filters only affect alert generation, not WebSocket monitoring