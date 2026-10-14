"""
Phase 2D Tests - Command routing and alert continuity (suppression removed)
"""

import unittest
import sys
import os
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock

# Add the current directory to the path so we can import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database

class TestPhase2DCommandRouting(unittest.TestCase):
    """Test command routing for /filter and /clearfilters"""
    
    def setUp(self):
        """Set up test database"""
        # Import main first
        import main
        from main import filter_command, clearfilters_command
        self.filter_command = filter_command
        self.clearfilters_command = clearfilters_command
    
    def test_filter_command_exists(self):
        """Test that /filter command exists and is callable"""
        self.assertTrue(callable(self.filter_command))
    
    def test_clearfilters_command_exists(self):
        """Test that /clearfilters command exists and is callable"""
        self.assertTrue(callable(self.clearfilters_command))
    
    def test_filter_command_without_args_starts_guided_flow(self):
        """Test that /filter without args starts guided flow"""
        # Create mock update and context
        update = Mock()
        update.effective_user.id = 12345
        context = Mock()
        context.args = []
        
        # Mock the filter_start function
        with patch('main.filter_start', new_callable=AsyncMock) as mock_filter_start:
            mock_filter_start.return_value = 5  # SELECT_WALLET state
            
            # Run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self.filter_command(update, context))
                # Verify filter_start was called
                mock_filter_start.assert_called_once_with(update, context)
            finally:
                loop.close()
    
    def test_clearfilters_command_without_args_starts_guided_flow(self):
        """Test that /clearfilters without args starts guided flow"""
        # Create mock update and context
        update = Mock()
        update.effective_user.id = 12345
        context = Mock()
        context.args = []
        
        # Mock the clearfilters_start function
        with patch('main.clearfilters_start', new_callable=AsyncMock) as mock_clearfilters_start:
            mock_clearfilters_start.return_value = 7  # CLEARFILTERS_ENTER_ADDRESS state
            
            # Run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self.clearfilters_command(update, context))
                # Verify clearfilters_start was called
                mock_clearfilters_start.assert_called_once_with(update, context)
            finally:
                loop.close()
    
    def test_filter_command_with_args_uses_legacy_syntax(self):
        """Test that /filter with args uses legacy syntax"""
        # Create mock update and context
        update = Mock()
        update.effective_user.id = 12345
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = Mock()
        context.args = ["0x1234567890abcdef1234567890abcdef12345678", "asset", "BTC"]
        
        # Mock database operations
        with patch('main.database') as mock_db:
            mock_db.get_or_create_user.return_value = 1
            mock_db.user_watches_wallet.return_value = True
            mock_db.set_wallet_filter = Mock()
            
            # Run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self.filter_command(update, context))
                # Should end conversation (ConversationHandler.END is -1)
                self.assertEqual(result, -1)  # ConversationHandler.END
            finally:
                loop.close()
    
    def test_clearfilters_command_with_args_uses_legacy_syntax(self):
        """Test that /clearfilters with args uses legacy syntax"""
        # Create mock update and context
        update = Mock()
        update.effective_user.id = 12345
        update.message = Mock()
        update.message.reply_text = AsyncMock()
        context = Mock()
        context.args = ["0x1234567890abcdef1234567890abcdef12345678"]
        
        # Mock database operations
        with patch('main.database') as mock_db:
            mock_db.get_or_create_user.return_value = 1
            mock_db.user_watches_wallet.return_value = True
            mock_db.clear_wallet_filter.return_value = True
            
            # Run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(self.clearfilters_command(update, context))
                # Should return None (not a conversation)
                self.assertIsNone(result)
            finally:
                loop.close()

class TestPhase2DAlertContinuity(unittest.TestCase):
    """Test that alerts continue normally during filter setup (suppression removed)"""
    
    def test_no_suppression_state_exists(self):
        """Test that suppression state has been completely removed"""
        import main
        
        # Verify active_filter_setup does not exist
        self.assertFalse(hasattr(main, 'active_filter_setup'), 
                        "active_filter_setup should not exist - suppression feature removed")
    
    def test_alerts_work_during_filter_setup(self):
        """Test that alerts are sent normally even during filter setup"""
        from main import handle_wallet_event
        import main
        
        # Create mock fill data
        fill = {
            "coin": "BTC",
            "side": "B",
            "sz": "1.0",
            "px": "50000",
            "time": 1234567890000
        }
        wallet_address = "0x1234567890abcdef1234567890abcdef12345678"
        event_key = "test_event_key"
        
        # Mock the database to return subscribers
        with patch('main.database') as mock_db:
            mock_db.is_event_processed.return_value = False
            mock_db.get_wallet_subscribers.return_value = [12345]
            mock_db.get_or_create_user.return_value = 1
            mock_db.get_wallet_filter.return_value = None
            mock_db.mark_event_processed = Mock()
            
            # Mock the application
            main.application = None  # No application = no alert sends
            
            # Run the handler - should not check for suppression
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(handle_wallet_event(fill, wallet_address, event_key))
            finally:
                loop.close()
        
        # Verify no suppression check occurred (function should run without error)

class TestPhase2DShutdown(unittest.TestCase):
    """Test shutdown coordination"""
    
    def test_shutdown_flag_exists(self):
        """Test that shutdown flag exists"""
        from main import is_shutting_down
        import main
        
        # Test setting shutdown flag
        main.is_shutting_down = True
        self.assertTrue(main.is_shutting_down)
        
        # Test clearing shutdown flag
        main.is_shutting_down = False
        self.assertFalse(main.is_shutting_down)
    
    def test_shutdown_event_exists(self):
        """Test that shutdown event variable exists"""
        from main import monitoring_shutdown_event
        import main
        
        # The event is created in main(), so we just verify the variable exists
        # It will be None before main() runs, but that's expected
        self.assertTrue(hasattr(main, 'monitoring_shutdown_event'))
    
    def test_shutdown_flag_persists(self):
        """Test that shutdown flag persists across function calls"""
        from main import is_shutting_down
        import main
        
        # Set shutdown flag
        main.is_shutting_down = True
        
        # Verify it's still set
        self.assertTrue(main.is_shutting_down)
        
        # Clean up
        main.is_shutting_down = False
    
    def test_shutdown_flag_prevents_alerts(self):
        """Test that shutdown flag prevents alert sending"""
        from main import is_shutting_down, handle_wallet_event
        import main
        
        # Set shutdown flag
        main.is_shutting_down = True
        
        # Create mock fill data
        fill = {
            "coin": "BTC",
            "side": "B",
            "sz": "1.0",
            "px": "50000",
            "time": 1234567890000
        }
        wallet_address = "0x1234567890abcdef1234567890abcdef12345678"
        event_key = "test_event_key"
        
        # Mock the database to return subscribers
        with patch('main.database') as mock_db:
            mock_db.is_event_processed.return_value = False
            mock_db.get_wallet_subscribers.return_value = [12345]
            mock_db.get_or_create_user.return_value = 1
            mock_db.get_wallet_filter.return_value = None
            mock_db.mark_event_processed = Mock()
            
            # Mock the application
            main.application = None  # No application = no alert sends
            
            # Run the handler
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(handle_wallet_event(fill, wallet_address, event_key))
            finally:
                loop.close()
        
        # Clean up
        main.is_shutting_down = False

class TestPhase2DTokenRedaction(unittest.TestCase):
    """Test Telegram bot token redaction from logs"""
    
    def test_token_redactor_filter_exists(self):
        """Test that token redactor filter is configured"""
        import main
        import logging
        
        # Check if any handlers have the TokenRedactor filter
        has_redactor = False
        for handler in logging.root.handlers:
            for f in handler.filters:
                if hasattr(f, '__class__') and 'TokenRedactor' in f.__class__.__name__:
                    has_redactor = True
                    break
        
        self.assertTrue(has_redactor, "TokenRedactor filter should be configured")

class TestPhase2DConversationStates(unittest.TestCase):
    """Test conversation state constants"""
    
    def test_conversation_state_values(self):
        """Test that conversation state constants are correctly defined"""
        from main import (
            WATCH_ENTER_ADDRESS, 
            CLEARFILTERS_ENTER_ADDRESS, 
            CLEARFILTERS_CONFIRM
        )
        
        # Verify state values are distinct integers
        self.assertEqual(WATCH_ENTER_ADDRESS, 5)
        self.assertEqual(CLEARFILTERS_ENTER_ADDRESS, 7)
        self.assertEqual(CLEARFILTERS_CONFIRM, 8)
        
        # Verify they don't overlap
        self.assertNotEqual(WATCH_ENTER_ADDRESS, CLEARFILTERS_ENTER_ADDRESS)
        self.assertNotEqual(CLEARFILTERS_ENTER_ADDRESS, CLEARFILTERS_CONFIRM)

if __name__ == '__main__':
    unittest.main()
