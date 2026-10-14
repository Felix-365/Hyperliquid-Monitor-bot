# Phase 2D Manual Testing Guide

This guide provides step-by-step instructions for manually testing the Phase 2D fixes.

## Prerequisites
- Ensure the bot is running with valid Telegram bot token
- Have a test Telegram account ready
- Have at least one Hyperliquid wallet address ready for testing

## Test 1 — Direct /filter Command

**Objective:** Verify that `/filter` command works when typed directly

**Steps:**
1. Open your Telegram bot chat
2. Type `/filter` (without any arguments)
3. Press Enter

**Expected Result:**
- Bot should respond with the wallet selection screen:
  ```
  🔔 Set Alert Filter

  Which wallet do you want to configure?

  [Wallet 1 — 0xABC...123]
  [Wallet 2 — 0xDEF...456]

  [❌ Cancel]
  ```

**If No Wallets Watched:**
- Bot should respond with:
  ```
  🔔 Set Alert Filter

  You are not monitoring any wallets yet.

  [➕ Watch Wallet]
  [❌ Cancel]
  ```

**Test Criteria:** ✅ PASS if wallet selection screen appears immediately

---

## Test 2 — Telegram Command Menu /filter

**Objective:** Verify that `/filter` works from Telegram's command menu

**Steps:**
1. Open your Telegram bot chat
2. Type `/` to open the command menu
3. Select `filter` from the menu
4. Tap it

**Expected Result:**
- Same as Test 1 — wallet selection screen should appear

**Test Criteria:** ✅ PASS if wallet selection screen appears immediately

---

## Test 3 — Direct /clearfilters Command

**Objective:** Verify that `/clearfilters` command works when typed directly

**Steps:**
1. Open your Telegram bot chat
2. Type `/clearfilters` (without any arguments)
3. Press Enter

**Expected Result:**
- Bot should respond with:
  ```
  🗑 Clear Filters

  Please paste the wallet address whose filters
  you want to clear.

  [❌ Cancel]
  ```

**Test Criteria:** ✅ PASS if address input prompt appears immediately

---

## Test 4 — Filter Suppression

**Objective:** Verify that alerts are suppressed during filter setup

**Preparation:**
- Have a highly active wallet address ready (e.g., `0x023a3d058020fb76cca98f01b3c48c8938a22355`)
- Ensure you're already watching this wallet
- Allow the bot to receive some normal alerts first

**Steps:**
1. Send `/filter`
2. Select the highly active wallet
3. **Do not complete the filter setup** — leave it in the configuration state
4. Observe the terminal logs for incoming events
5. Wait for 30-60 seconds while the wallet is actively trading

**Expected Behavior:**
- WebSocket continues receiving events
- Terminal logs show "New wallet event detected"
- Terminal logs show "Alert suppressed for user X during filter setup"
- **No Telegram alerts are sent** for that user/wallet pair

**Completion:**
6. Complete the filter setup (press "✅ Done" or configure a filter)
7. Wait for new events
8. Verify that alerts resume normally

**Test Criteria:** ✅ PASS if alerts are suppressed during setup and resume after completion

---

## Test 5 — Shutdown Coordination

**Objective:** Verify clean shutdown without HTTPXRequest errors

**Preparation:**
- Start the bot with at least one watched wallet
- Allow the bot to receive some live events
- Keep the bot running for at least 30 seconds

**Steps:**
1. Start the bot: `py main.py`
2. Wait for it to connect and receive some events
3. Press `Ctrl+C` to shutdown

**Expected Behavior:**
- Terminal shows:
  ```
  Starting shutdown sequence
  Shutdown flag set - preventing new alert sends
  Stopping subscription manager
  Waiting for monitoring thread to exit...
  Monitoring thread exited cleanly
  Shutdown complete
  ```

**Critical Check:**
- **No** `HTTPXRequest is not initialized` error
- **No** `RuntimeError` related to HTTP client
- Clean exit

**Test Criteria:** ✅ PASS if shutdown completes without HTTPXRequest errors

---

## Test 6 — Token Redaction

**Objective:** Verify that Telegram bot token is redacted from logs

**Preparation:**
- Start the bot
- Perform some bot operations (watch a wallet, send commands)

**Steps:**
1. Start the bot: `py main.py`
2. Watch a wallet: `/watch 0x1234567890abcdef1234567890abcdef12345678`
3. Check the terminal output

**Expected Behavior:**
- Terminal logs should **never** show the actual bot token
- URLs should appear as:
  - `https://api.telegram.org/bot<REDACTED>/sendMessage`
  - NOT: `https://api.telegram.org/bot1234567890:ABCDEF.../sendMessage`

**Critical Check:**
- Search terminal output for your actual bot token
- Should find **zero** occurrences

**Test Criteria:** ✅ PASS if no actual token appears in logs

---

## Test 7 — Legacy Command Syntax

**Objective:** Verify backward compatibility with command arguments

**Steps:**
1. Test legacy filter syntax:
   ```
   /filter 0x1234567890abcdef1234567890abcdef12345678 asset BTC
   ```
2. Test legacy clearfilters syntax:
   ```
   /clearfilters 0x1234567890abcdef1234567890abcdef12345678
   ```

**Expected Result:**
- Commands execute immediately without entering guided flow
- Appropriate success/error messages appear

**Test Criteria:** ✅ PASS if legacy syntax still works

---

## Test 8 — Start Menu Integration

**Objective:** Verify `/start` menu buttons still work

**Steps:**
1. Send `/start`
2. Tap "🔔 Alert Filters"
3. Verify guided filter flow starts
4. Send `/start` again
5. Tap "📊 Status"
6. Verify status appears

**Expected Result:**
- All menu buttons work correctly
- Guided flows start as expected

**Test Criteria:** ✅ PASS if all menu buttons work

---

## Summary Checklist

- [ ] Test 1: Direct `/filter` works
- [ ] Test 2: Menu `/filter` works
- [ ] Test 3: Direct `/clearfilters` works
- [ ] Test 4: Filter suppression active during setup
- [ ] Test 5: Clean shutdown without errors
- [ ] Test 6: Token redacted from logs
- [ ] Test 7: Legacy syntax works
- [ ] Test 8: Start menu buttons work

## Troubleshooting

**If `/filter` doesn't work:**
- Check handler registration order in `main.py`
- Verify ConversationHandler is registered before simple CommandHandlers
- Check terminal logs for "Filter command received" message

**If alerts not suppressed:**
- Check `active_filter_setup` set in terminal logs
- Verify suppression key matches (user_id, wallet_address)
- Check that suppression is removed on Done/Cancel

**If shutdown errors occur:**
- Verify shutdown flag is set BEFORE stopping subscription manager
- Check that monitoring thread joins successfully
- Verify `is_shutting_down` flag is checked in `handle_wallet_event`

**If token appears in logs:**
- Verify TokenRedactor is loaded after TELEGRAM_BOT_TOKEN is set
- Check that TokenRedactor is added to all logging handlers
- Restart bot after code changes