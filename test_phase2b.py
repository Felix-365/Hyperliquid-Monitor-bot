"""
Tests for Phase 2B filter functionality.
Tests independent filter behavior, filter combinations, and backward compatibility.
"""

import unittest
import tempfile
import os
from database import Database
from filter_engine import FilterEngine


class TestFilterEngine(unittest.TestCase):
    """Test filter evaluation logic"""
    
    def test_no_filters(self):
        """Test that events match when no filters are configured"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '1.0',
            'px': '50000'
        }
        
        # No filters should match everything
        self.assertTrue(FilterEngine.matches_filters(event, None))
        self.assertTrue(FilterEngine.matches_filters(event, {}))
        self.assertTrue(FilterEngine.matches_filters(event, {'asset': None}))
    
    def test_asset_filter_match(self):
        """Test asset filter matching"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '1.0',
            'px': '50000'
        }
        
        filters = {'asset': 'BTC'}
        self.assertTrue(FilterEngine.matches_filters(event, filters))
    
    def test_asset_filter_no_match(self):
        """Test asset filter non-matching"""
        event = {
            'coin': 'ETH',
            'side': 'B',
            'sz': '1.0',
            'px': '3000'
        }
        
        filters = {'asset': 'BTC'}
        self.assertFalse(FilterEngine.matches_filters(event, filters))
    
    def test_asset_filter_with_perp_suffix(self):
        """Test asset filter with -PERP suffix"""
        event = {
            'coin': 'BTC-PERP',
            'side': 'B',
            'sz': '1.0',
            'px': '50000'
        }
        
        # Should match regardless of -PERP suffix
        filters = {'asset': 'BTC'}
        self.assertTrue(FilterEngine.matches_filters(event, filters))
        
        filters = {'asset': 'BTC-PERP'}
        self.assertTrue(FilterEngine.matches_filters(event, filters))
    
    def test_multi_asset_filter(self):
        """Test multi-asset filter with OR logic"""
        event_btc = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '1.0',
            'px': '50000'
        }
        
        event_eth = {
            'coin': 'ETH',
            'side': 'B',
            'sz': '1.0',
            'px': '3000'
        }
        
        event_doge = {
            'coin': 'DOGE',
            'side': 'B',
            'sz': '1.0',
            'px': '0.1'
        }
        
        # Multi-asset filter should match any of the assets
        filters = {'asset': 'BTC,ETH,DOGE'}
        self.assertTrue(FilterEngine.matches_filters(event_btc, filters))
        self.assertTrue(FilterEngine.matches_filters(event_eth, filters))
        self.assertTrue(FilterEngine.matches_filters(event_doge, filters))
        
        # Should not match other assets
        event_sol = {
            'coin': 'SOL',
            'side': 'B',
            'sz': '1.0',
            'px': '100'
        }
        self.assertFalse(FilterEngine.matches_filters(event_sol, filters))
    
    def test_multi_asset_filter_with_spaces(self):
        """Test multi-asset filter with spaces"""
        event_btc = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '1.0',
            'px': '50000'
        }
        
        event_eth = {
            'coin': 'ETH',
            'side': 'B',
            'sz': '1.0',
            'px': '3000'
        }
        
        # Multi-asset filter with spaces should work
        filters = {'asset': 'BTC, ETH, DOGE'}
        self.assertTrue(FilterEngine.matches_filters(event_btc, filters))
        self.assertTrue(FilterEngine.matches_filters(event_eth, filters))
    
    def test_side_filter_buy(self):
        """Test side filter for BUY"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '1.0',
            'px': '50000'
        }
        
        filters = {'side': 'BUY'}
        self.assertTrue(FilterEngine.matches_filters(event, filters))
    
    def test_side_filter_sell(self):
        """Test side filter for SELL"""
        event = {
            'coin': 'BTC',
            'side': 'A',
            'sz': '1.0',
            'px': '50000'
        }
        
        filters = {'side': 'SELL'}
        self.assertTrue(FilterEngine.matches_filters(event, filters))
    
    def test_side_filter_no_match(self):
        """Test side filter non-matching"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '1.0',
            'px': '50000'
        }
        
        filters = {'side': 'SELL'}
        self.assertFalse(FilterEngine.matches_filters(event, filters))
    
    def test_min_value_filter_match(self):
        """Test minimum value filter matching"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '2.0',
            'px': '60000'
        }
        
        # Trade value = 2.0 * 60000 = 120000
        filters = {'min_value_usd': 100000}
        self.assertTrue(FilterEngine.matches_filters(event, filters))
    
    def test_min_value_filter_no_match(self):
        """Test minimum value filter non-matching"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '1.0',
            'px': '50000'
        }
        
        # Trade value = 1.0 * 50000 = 50000
        filters = {'min_value_usd': 100000}
        self.assertFalse(FilterEngine.matches_filters(event, filters))
    
    def test_min_value_filter_exact_match(self):
        """Test minimum value filter exact match"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '2.0',
            'px': '50000'
        }
        
        # Trade value = 2.0 * 50000 = 100000
        filters = {'min_value_usd': 100000}
        self.assertTrue(FilterEngine.matches_filters(event, filters))
    
    def test_combined_filters_and_logic(self):
        """Test that multiple filters use AND logic"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '2.0',
            'px': '60000'
        }
        
        # All filters should match
        filters = {
            'asset': 'BTC',
            'side': 'BUY',
            'min_value_usd': 100000
        }
        self.assertTrue(FilterEngine.matches_filters(event, filters))
    
    def test_combined_filters_partial_match(self):
        """Test that partial filter matches fail with AND logic"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '2.0',
            'px': '60000'
        }
        
        # Asset matches but side doesn't
        filters = {
            'asset': 'BTC',
            'side': 'SELL',
            'min_value_usd': 100000
        }
        self.assertFalse(FilterEngine.matches_filters(event, filters))
    
    def test_validate_filter_type(self):
        """Test filter type validation"""
        self.assertTrue(FilterEngine.validate_filter_type('asset'))
        self.assertTrue(FilterEngine.validate_filter_type('side'))
        self.assertTrue(FilterEngine.validate_filter_type('min_value'))
        self.assertFalse(FilterEngine.validate_filter_type('invalid'))
        self.assertFalse(FilterEngine.validate_filter_type('banana'))
    
    def test_validate_side(self):
        """Test side validation"""
        self.assertTrue(FilterEngine.validate_side('BUY'))
        self.assertTrue(FilterEngine.validate_side('SELL'))
        self.assertTrue(FilterEngine.validate_side('buy'))
        self.assertTrue(FilterEngine.validate_side('sell'))
        self.assertFalse(FilterEngine.validate_side('invalid'))
        self.assertFalse(FilterEngine.validate_side('HELLO'))
    
    def test_validate_min_value(self):
        """Test minimum value validation"""
        self.assertEqual(FilterEngine.validate_min_value('100000'), 100000.0)
        self.assertEqual(FilterEngine.validate_min_value('100000.5'), 100000.5)
        self.assertEqual(FilterEngine.validate_min_value('0'), 0.0)
        self.assertIsNone(FilterEngine.validate_min_value('abc'))
        self.assertIsNone(FilterEngine.validate_min_value('-100'))


class TestDatabaseFilters(unittest.TestCase):
    """Test database filter operations"""
    
    def setUp(self):
        """Set up test database"""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.db = Database(self.temp_db.name)
    
    def tearDown(self):
        """Clean up test database"""
        os.unlink(self.temp_db.name)
    
    def test_set_wallet_filter(self):
        """Test setting wallet filter"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Add wallet to watchlist first
        self.db.add_wallet_to_watchlist(user_id, wallet)
        
        # Set filter
        result = self.db.set_wallet_filter(user_id, wallet, asset='BTC', side='BUY', min_value_usd=100000)
        self.assertTrue(result)
    
    def test_set_wallet_filter_not_watching(self):
        """Test setting filter for wallet not being watched"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Try to set filter without watching wallet
        result = self.db.set_wallet_filter(user_id, wallet, asset='BTC')
        self.assertFalse(result)
    
    def test_get_wallet_filter(self):
        """Test getting wallet filter"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Add wallet and set filter
        self.db.add_wallet_to_watchlist(user_id, wallet)
        self.db.set_wallet_filter(user_id, wallet, asset='BTC', side='BUY', min_value_usd=100000)
        
        # Get filter
        filters = self.db.get_wallet_filter(user_id, wallet)
        self.assertIsNotNone(filters)
        self.assertEqual(filters['asset'], 'BTC')
        self.assertEqual(filters['side'], 'BUY')
        self.assertEqual(filters['min_value_usd'], 100000)
    
    def test_get_wallet_filter_none(self):
        """Test getting filter when none exists"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Add wallet without filter
        self.db.add_wallet_to_watchlist(user_id, wallet)
        
        # Get filter
        filters = self.db.get_wallet_filter(user_id, wallet)
        self.assertIsNone(filters)
    
    def test_clear_wallet_filter(self):
        """Test clearing wallet filter"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Add wallet and set filter
        self.db.add_wallet_to_watchlist(user_id, wallet)
        self.db.set_wallet_filter(user_id, wallet, asset='BTC')
        
        # Clear filter
        result = self.db.clear_wallet_filter(user_id, wallet)
        self.assertTrue(result)
        
        # Verify filter is cleared
        filters = self.db.get_wallet_filter(user_id, wallet)
        self.assertIsNone(filters)
    
    def test_clear_wallet_filter_none(self):
        """Test clearing filter when none exists"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Add wallet without filter
        self.db.add_wallet_to_watchlist(user_id, wallet)
        
        # Try to clear non-existent filter
        result = self.db.clear_wallet_filter(user_id, wallet)
        self.assertFalse(result)
    
    def test_update_wallet_filter(self):
        """Test updating existing wallet filter"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Add wallet and set initial filter
        self.db.add_wallet_to_watchlist(user_id, wallet)
        self.db.set_wallet_filter(user_id, wallet, asset='BTC')
        
        # Update filter
        self.db.set_wallet_filter(user_id, wallet, asset='ETH', side='SELL')
        
        # Verify update
        filters = self.db.get_wallet_filter(user_id, wallet)
        self.assertEqual(filters['asset'], 'ETH')
        self.assertEqual(filters['side'], 'SELL')
        self.assertIsNone(filters['min_value_usd'])
    
    def test_get_user_wallets_with_filters(self):
        """Test getting user wallets with filter configurations"""
        user_id = self.db.get_or_create_user(12345)
        wallet1 = '0x' + 'a' * 40
        wallet2 = '0x' + 'b' * 40
        
        # Add wallets
        self.db.add_wallet_to_watchlist(user_id, wallet1)
        self.db.add_wallet_to_watchlist(user_id, wallet2)
        
        # Set filter for wallet1 only
        self.db.set_wallet_filter(user_id, wallet1, asset='BTC', side='BUY')
        
        # Get wallets with filters
        wallets = self.db.get_user_wallets_with_filters(user_id)
        self.assertEqual(len(wallets), 2)
        
        # Find wallet1 in results
        wallet1_result = next((w for w in wallets if w[0] == wallet1), None)
        self.assertIsNotNone(wallet1_result)
        self.assertEqual(wallet1_result[2], 'BTC')  # asset is at index 2 now (after wallet_alias)
        self.assertEqual(wallet1_result[3], 'BUY')   # side is at index 3 now
        
        # Find wallet2 in results (no filters)
        wallet2_result = next((w for w in wallets if w[0] == wallet2), None)
        self.assertIsNotNone(wallet2_result)
        self.assertIsNone(wallet2_result[2])  # asset is at index 2 now
        self.assertIsNone(wallet2_result[3])  # side is at index 3 now
    
    def test_user_watches_wallet(self):
        """Test checking if user watches wallet"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Initially not watching
        self.assertFalse(self.db.user_watches_wallet(user_id, wallet))
        
        # Add wallet
        self.db.add_wallet_to_watchlist(user_id, wallet)
        
        # Now watching
        self.assertTrue(self.db.user_watches_wallet(user_id, wallet))
    
    def test_multiple_users_same_wallet_different_filters(self):
        """Test that multiple users can have different filters for same wallet"""
        user1_id = self.db.get_or_create_user(11111)
        user2_id = self.db.get_or_create_user(22222)
        wallet = '0x' + 'a' * 40
        
        # Both users watch same wallet
        self.db.add_wallet_to_watchlist(user1_id, wallet)
        self.db.add_wallet_to_watchlist(user2_id, wallet)
        
        # Set different filters
        self.db.set_wallet_filter(user1_id, wallet, asset='BTC', side='BUY')
        self.db.set_wallet_filter(user2_id, wallet, side='SELL', min_value_usd=50000)
        
        # Verify filters are independent
        filters1 = self.db.get_wallet_filter(user1_id, wallet)
        filters2 = self.db.get_wallet_filter(user2_id, wallet)
        
        self.assertEqual(filters1['asset'], 'BTC')
        self.assertEqual(filters1['side'], 'BUY')
        self.assertIsNone(filters1['min_value_usd'])
        
        self.assertIsNone(filters2['asset'])
        self.assertEqual(filters2['side'], 'SELL')
        self.assertEqual(filters2['min_value_usd'], 50000)
    
    def test_independent_filter_updates(self):
        """Test that updating one filter preserves others"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Add wallet and set initial filters
        self.db.add_wallet_to_watchlist(user_id, wallet)
        self.db.set_wallet_filter(user_id, wallet, asset='BTC', side='BUY', min_value_usd=100000)
        
        # Update only asset
        self.db.set_wallet_filter(user_id, wallet, asset='ETH')
        
        # Verify side and min_value are preserved
        filters = self.db.get_wallet_filter(user_id, wallet)
        self.assertEqual(filters['asset'], 'ETH')
        self.assertEqual(filters['side'], 'BUY')
        self.assertEqual(filters['min_value_usd'], 100000)
        
        # Update only side
        self.db.set_wallet_filter(user_id, wallet, side='SELL')
        
        # Verify asset and min_value are preserved
        filters = self.db.get_wallet_filter(user_id, wallet)
        self.assertEqual(filters['asset'], 'ETH')
        self.assertEqual(filters['side'], 'SELL')
        self.assertEqual(filters['min_value_usd'], 100000)
        
        # Update only min_value
        self.db.set_wallet_filter(user_id, wallet, min_value_usd=50000)
        
        # Verify asset and side are preserved
        filters = self.db.get_wallet_filter(user_id, wallet)
        self.assertEqual(filters['asset'], 'ETH')
        self.assertEqual(filters['side'], 'SELL')
        self.assertEqual(filters['min_value_usd'], 50000)
    
    def test_add_filter_preserves_existing(self):
        """Test that adding a filter preserves existing ones"""
        user_id = self.db.get_or_create_user(12345)
        wallet = '0x' + 'a' * 40
        
        # Add wallet and set initial filter
        self.db.add_wallet_to_watchlist(user_id, wallet)
        self.db.set_wallet_filter(user_id, wallet, asset='BTC')
        
        # Add second filter
        self.db.set_wallet_filter(user_id, wallet, side='BUY')
        
        # Verify both filters exist
        filters = self.db.get_wallet_filter(user_id, wallet)
        self.assertEqual(filters['asset'], 'BTC')
        self.assertEqual(filters['side'], 'BUY')
        self.assertIsNone(filters['min_value_usd'])
        
        # Add third filter
        self.db.set_wallet_filter(user_id, wallet, min_value_usd=100000)
        
        # Verify all three filters exist
        filters = self.db.get_wallet_filter(user_id, wallet)
        self.assertEqual(filters['asset'], 'BTC')
        self.assertEqual(filters['side'], 'BUY')
        self.assertEqual(filters['min_value_usd'], 100000)


class TestFilterIntegration(unittest.TestCase):
    """Test filter integration with event pipeline"""
    
    def test_event_routing_with_filters(self):
        """Test that events are routed correctly with different user filters"""
        event = {
            'coin': 'BTC',
            'side': 'B',
            'sz': '2.0',
            'px': '60000'
        }
        
        # User 1: BTC filter
        filters1 = {'asset': 'BTC'}
        self.assertTrue(FilterEngine.matches_filters(event, filters1))
        
        # User 2: ETH filter
        filters2 = {'asset': 'ETH'}
        self.assertFalse(FilterEngine.matches_filters(event, filters2))
        
        # User 3: No filters
        filters3 = None
        self.assertTrue(FilterEngine.matches_filters(event, filters3))
    
    def test_combined_filter_scenario(self):
        """Test realistic combined filter scenario"""
        # Event: BTC SELL $150,000
        event = {
            'coin': 'BTC',
            'side': 'A',
            'sz': '1.5',
            'px': '100000'
        }
        
        # User A: BTC + SELL + min $100k
        filters_a = {
            'asset': 'BTC',
            'side': 'SELL',
            'min_value_usd': 100000
        }
        self.assertTrue(FilterEngine.matches_filters(event, filters_a))
        
        # User B: SELL + min $50k
        filters_b = {
            'side': 'SELL',
            'min_value_usd': 50000
        }
        self.assertTrue(FilterEngine.matches_filters(event, filters_b))
        
        # User C: No filters
        filters_c = None
        self.assertTrue(FilterEngine.matches_filters(event, filters_c))
        
        # User D: ETH filter
        filters_d = {'asset': 'ETH'}
        self.assertFalse(FilterEngine.matches_filters(event, filters_d))


if __name__ == '__main__':
    unittest.main()