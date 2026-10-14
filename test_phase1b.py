"""
Test file for Phase 1B functionality.
Tests the multi-wallet, multi-user, database, and subscription management features.
"""

import asyncio
import sys
import os
import time
import tempfile
import shutil
from datetime import datetime

# Set environment variable before importing main to avoid exit
os.environ['TELEGRAM_BOT_TOKEN'] = 'test_token_for_testing'

# Import the modules we need to test
from database import Database
from subscription_manager import WalletSubscriptionManager

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

class MockApplication:
    """Mock Telegram application for testing"""
    def __init__(self):
        self.bot = MockBot()

def test_database_initialization():
    """Test database initialization and schema creation"""
    print("\n=== Testing Database Initialization ===")
    
    # Create a temporary database for testing
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test.db")
    
    try:
        db = Database(test_db_path)
        
        # Verify tables were created by checking basic operations
        user_id = db.get_or_create_user(123456)
        assert user_id > 0, "User creation failed"
        
        print("[PASS] Database initialized with correct schema")
        return True
        
    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_user_wallet_operations():
    """Test adding and removing wallets from user watchlist"""
    print("\n=== Testing User Wallet Operations ===")
    
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test.db")
    
    try:
        db = Database(test_db_path)
        
        # Create test user
        user_id = db.get_or_create_user(123456)
        
        # Test adding wallet
        wallet1 = "0x1234567890abcdef1234567890abcdef12345678"
        added = db.add_wallet_to_watchlist(user_id, wallet1)
        assert added, "Failed to add wallet to watchlist"
        
        # Test duplicate add (should not add again)
        added_again = db.add_wallet_to_watchlist(user_id, wallet1)
        assert not added_again, "Duplicate wallet should not be added again"
        
        # Test getting user wallets
        user_wallets = db.get_user_wallets(user_id)
        assert len(user_wallets) == 1, "Should have exactly 1 wallet"
        assert wallet1.lower() in user_wallets, "Wallet not found in user wallets"
        
        # Test adding second wallet
        wallet2 = "0xabcdef1234567890abcdef1234567890abcdef12"
        db.add_wallet_to_watchlist(user_id, wallet2)
        user_wallets = db.get_user_wallets(user_id)
        assert len(user_wallets) == 2, "Should have 2 wallets"
        
        # Test removing wallet
        removed = db.remove_wallet_from_watchlist(user_id, wallet1)
        assert removed, "Failed to remove wallet"
        
        user_wallets = db.get_user_wallets(user_id)
        assert len(user_wallets) == 1, "Should have 1 wallet after removal"
        assert wallet1.lower() not in user_wallets, "Removed wallet still in list"
        
        print("[PASS] User wallet operations work correctly")
        return True
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_multiple_users_same_wallet():
    """Test multiple users watching the same wallet"""
    print("\n=== Testing Multiple Users Same Wallet ===")
    
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test.db")
    
    try:
        db = Database(test_db_path)
        
        # Create two users
        user1_id = db.get_or_create_user(111111)
        user2_id = db.get_or_create_user(222222)
        
        # Both users watch the same wallet
        shared_wallet = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"
        
        db.add_wallet_to_watchlist(user1_id, shared_wallet)
        db.add_wallet_to_watchlist(user2_id, shared_wallet)
        
        # Check that both users have the wallet
        user1_wallets = db.get_user_wallets(user1_id)
        user2_wallets = db.get_user_wallets(user2_id)
        
        assert shared_wallet.lower() in user1_wallets, "User 1 missing shared wallet"
        assert shared_wallet.lower() in user2_wallets, "User 2 missing shared wallet"
        
        # Check wallet subscribers
        subscribers = db.get_wallet_subscribers(shared_wallet)
        assert len(subscribers) == 2, "Should have 2 subscribers"
        assert 111111 in subscribers, "User 1 not in subscribers"
        assert 222222 in subscribers, "User 2 not in subscribers"
        
        # One user stops watching
        db.remove_wallet_from_watchlist(user1_id, shared_wallet)
        
        # Check that wallet still has one subscriber
        subscribers = db.get_wallet_subscribers(shared_wallet)
        assert len(subscribers) == 1, "Should have 1 subscriber after removal"
        assert 222222 in subscribers, "User 2 should still be subscriber"
        
        print("[PASS] Multiple users can watch same wallet correctly")
        return True
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_event_deduplication():
    """Test event deduplication functionality"""
    print("\n=== Testing Event Deduplication ===")
    
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test.db")
    
    try:
        db = Database(test_db_path)
        
        # Test event key processing
        event_key = "test_event_key_123"
        wallet = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"
        
        # First check - should not be processed
        assert not db.is_event_processed(event_key), "Event should not be marked as processed initially"
        
        # Mark as processed
        db.mark_event_processed(event_key, wallet)
        
        # Second check - should be processed
        assert db.is_event_processed(event_key), "Event should be marked as processed"
        
        # Try to mark again (should not fail due to INSERT OR IGNORE)
        db.mark_event_processed(event_key, wallet)
        
        # Still should be processed
        assert db.is_event_processed(event_key), "Event should still be marked as processed"
        
        print("[PASS] Event deduplication works correctly")
        return True
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def test_wallet_normalization():
    """Test wallet address normalization"""
    print("\n=== Testing Wallet Address Normalization ===")
    
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test.db")
    
    try:
        db = Database(test_db_path)
        
        user_id = db.get_or_create_user(123456)
        
        # Add wallet with mixed case
        wallet_mixed = "0xAbCdEf1234567890AbCdEf1234567890AbCdEf12"
        db.add_wallet_to_watchlist(user_id, wallet_mixed)
        
        # Try to add same wallet with different case
        wallet_lower = "0xabcdef1234567890abcdef1234567890abcdef12"
        added = db.add_wallet_to_watchlist(user_id, wallet_lower)
        
        # Should not add again (normalization prevents duplicates)
        assert not added, "Duplicate wallet with different case should not be added"
        
        # Check that wallet is stored in lowercase
        user_wallets = db.get_user_wallets(user_id)
        assert wallet_lower in user_wallets, "Wallet should be normalized to lowercase"
        
        print("[PASS] Wallet address normalization works correctly")
        return True
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)



def test_get_all_active_wallets():
    """Test getting all active wallets across all users"""
    print("\n=== Testing Get All Active Wallets ===")
    
    temp_dir = tempfile.mkdtemp()
    test_db_path = os.path.join(temp_dir, "test.db")
    
    try:
        db = Database(test_db_path)
        
        # Create multiple users with different wallets
        user1 = db.get_or_create_user(111111)
        user2 = db.get_or_create_user(222222)
        
        wallet1 = "0xABCDEF1234567890ABCDEF1234567890ABCDEF12"
        wallet2 = "0x1234567890ABCDEF1234567890ABCDEF12345678"
        wallet3 = "0xFEDCBA0987654321FEDCBA0987654321FEDCBA09"
        
        # User 1 watches wallet1 and wallet2
        db.add_wallet_to_watchlist(user1, wallet1)
        db.add_wallet_to_watchlist(user1, wallet2)
        
        # User 2 watches wallet2 and wallet3
        db.add_wallet_to_watchlist(user2, wallet2)
        db.add_wallet_to_watchlist(user2, wallet3)
        
        # Get all active wallets
        all_wallets = db.get_all_active_wallets()
        
        # Should have 3 unique wallets
        assert len(all_wallets) == 3, f"Expected 3 unique wallets, got {len(all_wallets)}"
        assert wallet1.lower() in all_wallets, "Wallet 1 missing"
        assert wallet2.lower() in all_wallets, "Wallet 2 missing"
        assert wallet3.lower() in all_wallets, "Wallet 3 missing"
        
        print("[PASS] Get all active wallets works correctly")
        return True
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def run_all_tests():
    """Run all Phase 1B tests and report results"""
    print("=" * 60)
    print("PHASE 1B FUNCTIONALITY TESTS")
    print("=" * 60)
    
    tests = [
        ("Database Initialization", test_database_initialization),
        ("User Wallet Operations", test_user_wallet_operations),
        ("Multiple Users Same Wallet", test_multiple_users_same_wallet),
        ("Event Deduplication", test_event_deduplication),
        ("Wallet Normalization", test_wallet_normalization),
        ("Get All Active Wallets", test_get_all_active_wallets),
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
        print("\n[PASS] All Phase 1B tests passed!")
        return True

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)