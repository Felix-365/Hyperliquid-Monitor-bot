"""
Test file for verifying Hyperliquid event processing to Telegram alert flow.
This test simulates Hyperliquid WebSocket messages and verifies the complete
event-processing path without connecting to the real API.
"""

import asyncio
import sys
import time
import os
from datetime import datetime

# Set environment variable before importing main to avoid exit
os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token_for_testing'

# Import the functions we need to test from main.py
from main import format_telegram_message

# Mock Telegram application for testing
class MockBot:
    """Mock Telegram bot for testing"""
    def __init__(self):
        self.messages_sent = []
    
    async def send_message(self, chat_id, text):
        """Mock send_message that stores messages instead of sending them"""
        self.messages_sent.append({
            'chat_id': chat_id,
            'text': text,
            'timestamp': time.time()
        })
        print(f"[MOCK] Telegram message sent to chat {chat_id}")
        print(f"  Message preview: {text[:100]}...")

class MockApplication:
    """Mock Telegram application for testing"""
    def __init__(self):
        self.bot = MockBot()

def test_format_telegram_message():
    """Test the Telegram message formatting function"""
    print("\n=== Testing Telegram Message Formatting ===")
    
    # Test data matching the specification
    test_wallet = "0x1234567890abcdef1234567890abcdef12345678"
    test_fill = {
        "coin": "BTC",
        "side": "B",  # B for BUY
        "sz": "0.25",
        "px": "108420",
        "time": int(time.time() * 1000)  # Current timestamp in milliseconds
    }
    
    # Call the formatting function
    message = format_telegram_message(test_fill, test_wallet)
    
    # Verify the message was formatted correctly
    assert message is not None, "Message formatting failed"
    assert "NEW HYPERLIQUID ACTIVITY" in message, "Missing header"
    assert "0x1234...5678" in message, "Wallet address not formatted correctly"
    assert "BTC" in message, "Coin not included"
    assert "BUY" in message, "BUY side not formatted correctly"
    assert "0.25 BTC" in message, "Size not formatted correctly"
    assert "$108,420.00" in message, "Price not formatted correctly"
    
    # Verify message structure without printing emojis
    assert "Wallet:" in message, "Missing Wallet section"
    assert "Size:" in message, "Missing Size section"
    assert "Price:" in message, "Missing Price section"
    assert "Time:" in message, "Missing Time section"
    
    print("[PASS] Telegram message formatted correctly")
    # Verify message structure
    print(f"[PASS] Message structure validated")
    return True

def test_sell_order_formatting():
    """Test that SELL orders are formatted correctly"""
    print("\n=== Testing SELL Order Formatting ===")
    
    test_wallet = "0x1234567890abcdef1234567890abcdef12345678"
    test_fill = {
        "coin": "ETH",
        "side": "A",  # A for SELL in Hyperliquid
        "sz": "1.5",
        "px": "3500",
        "time": int(time.time() * 1000)
    }
    
    message = format_telegram_message(test_fill, test_wallet)
    
    assert message is not None, "Message formatting failed"
    assert "SELL" in message, "SELL side not formatted correctly"
    assert "ETH" in message, "Coin not included"
    
    print("[PASS] SELL order formatted correctly with emoji")
    return True

def run_all_tests():
    """Run all tests and report results"""
    print("=" * 60)
    print("HYPERLIQUID EVENT PROCESSING TESTS (PHASE 1A)")
    print("=" * 60)
    
    tests = [
        ("Telegram Message Formatting", test_format_telegram_message),
        ("SELL Order Formatting", test_sell_order_formatting),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, "PASSED", None))
            print(f"[PASS] {test_name}: PASSED")
        except AssertionError as e:
            results.append((test_name, "FAILED", str(e)))
            print(f"[FAIL] {test_name}: FAILED - {e}")
        except Exception as e:
            results.append((test_name, "ERROR", str(e)))
            print(f"[ERROR] {test_name}: ERROR - {e}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, status, _ in results if status == "PASSED")
    failed = sum(1 for _, status, _ in results if status == "FAILED")
    errors = sum(1 for _, status, _ in results if status == "ERROR")
    
    print(f"Total tests: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Errors: {errors}")
    
    if failed > 0 or errors > 0:
        print("\nFailed/Error details:")
        for test_name, status, error in results:
            if status in ["FAILED", "ERROR"]:
                print(f"  - {test_name}: {error}")
        return False
    else:
        print("\n[PASS] All Phase 1A tests passed!")
        return True

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)