"""
Database module for Hyperliquid wallet monitor.
Handles SQLite database operations for users, watched wallets, and event deduplication.
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Optional, Tuple
import threading

logger = logging.getLogger(__name__)

class Database:
    """Database manager for wallet monitoring application"""
    
    def __init__(self, db_path: str = "hyperliquid_monitor.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._initialize_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _initialize_database(self):
        """Initialize database tables"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Create users table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER UNIQUE NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create watched_wallets table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS watched_wallets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        wallet_address TEXT NOT NULL,
                        wallet_alias TEXT,
                        enabled BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        UNIQUE(user_id, wallet_address)
                    )
                """)
                
                # Create processed_events table for deduplication
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_key TEXT NOT NULL,
                        wallet_address TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(event_key)
                    )
                """)
                
                # Create wallet_filters table for Phase 2A filtering
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS wallet_filters (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        wallet_address TEXT NOT NULL,
                        asset TEXT,
                        side TEXT,
                        min_value_usd REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        UNIQUE(user_id, wallet_address)
                    )
                """)

                # Create alert_history table for admin dashboard statistics
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS alert_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        wallet_address TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id)
                    )
                """)

                # Create indexes for performance
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_watched_wallets_address 
                    ON watched_wallets(wallet_address)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_processed_events_wallet
                    ON processed_events(wallet_address)
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_alert_history_created
                    ON alert_history(created_at)
                """)

                conn.commit()
                
                # Migration: Add wallet_alias column if it doesn't exist (Phase 3A)
                cursor.execute("PRAGMA table_info(watched_wallets)")
                columns = [row['name'] for row in cursor.fetchall()]
                if 'wallet_alias' not in columns:
                    cursor.execute("ALTER TABLE watched_wallets ADD COLUMN wallet_alias TEXT")
                    conn.commit()
                    logger.info("Migration: Added wallet_alias column to watched_wallets table")
                
                logger.info("Database initialized successfully")
                
            except Exception as e:
                logger.error(f"Failed to initialize database: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def get_or_create_user(self, telegram_id: int) -> int:
        """Get existing user or create new one, returns user ID"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Try to get existing user
                cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
                row = cursor.fetchone()
                
                if row:
                    return row['id']
                
                # Create new user
                cursor.execute(
                    "INSERT INTO users (telegram_id) VALUES (?)",
                    (telegram_id,)
                )
                conn.commit()
                return cursor.lastrowid
                
            except Exception as e:
                logger.error(f"Failed to get or create user: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def add_wallet_to_watchlist(self, user_id: int, wallet_address: str, wallet_alias: str = None) -> bool:
        """Add wallet to user's watchlist with optional alias"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address to lowercase
                wallet_address = wallet_address.lower()
                
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO watched_wallets (user_id, wallet_address, wallet_alias)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, wallet_address, wallet_alias)
                )
                
                conn.commit()
                added = cursor.rowcount > 0
                if added:
                    logger.info(f"Added wallet {wallet_address} (alias: {wallet_alias}) for user {user_id}")
                return added
                
            except Exception as e:
                logger.error(f"Failed to add wallet to watchlist: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def remove_wallet_from_watchlist(self, user_id: int, wallet_address: str) -> bool:
        """Remove wallet from user's watchlist"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address
                wallet_address = wallet_address.lower()
                
                cursor.execute(
                    """
                    DELETE FROM watched_wallets 
                    WHERE user_id = ? AND wallet_address = ?
                    """,
                    (user_id, wallet_address)
                )
                
                conn.commit()
                removed = cursor.rowcount > 0
                if removed:
                    logger.info(f"Removed wallet {wallet_address} for user {user_id}")
                return removed
                
            except Exception as e:
                logger.error(f"Failed to remove wallet from watchlist: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def get_user_wallets(self, user_id: int) -> List[str]:
        """Get all wallets watched by a user"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                cursor.execute(
                    """
                    SELECT wallet_address FROM watched_wallets 
                    WHERE user_id = ? AND enabled = 1
                    ORDER BY created_at
                    """,
                    (user_id,)
                )
                
                return [row['wallet_address'] for row in cursor.fetchall()]
                
            except Exception as e:
                logger.error(f"Failed to get user wallets: {e}")
                raise
            finally:
                conn.close()
    
    def get_user_wallets_with_aliases(self, user_id: int) -> List[tuple]:
        """Get all wallets with their aliases for a user"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                cursor.execute(
                    """
                    SELECT wallet_address, wallet_alias FROM watched_wallets 
                    WHERE user_id = ? AND enabled = 1
                    ORDER BY created_at
                    """,
                    (user_id,)
                )
                
                return [(row['wallet_address'], row['wallet_alias']) for row in cursor.fetchall()]
                
            except Exception as e:
                logger.error(f"Failed to get user wallets with aliases: {e}")
                raise
            finally:
                conn.close()
    
    def get_wallet_alias(self, user_id: int, wallet_address: str) -> Optional[str]:
        """Get alias for a specific wallet"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address
                wallet_address = wallet_address.lower()
                
                cursor.execute(
                    """
                    SELECT wallet_alias FROM watched_wallets 
                    WHERE user_id = ? AND wallet_address = ?
                    """,
                    (user_id, wallet_address)
                )
                
                row = cursor.fetchone()
                return row['wallet_alias'] if row else None
                
            except Exception as e:
                logger.error(f"Failed to get wallet alias: {e}")
                return None
            finally:
                conn.close()
    
    def set_wallet_alias(self, user_id: int, wallet_address: str, wallet_alias: str) -> bool:
        """Set or update alias for a wallet"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address
                wallet_address = wallet_address.lower()
                
                cursor.execute(
                    """
                    UPDATE watched_wallets 
                    SET wallet_alias = ?
                    WHERE user_id = ? AND wallet_address = ?
                    """,
                    (wallet_alias, user_id, wallet_address)
                )
                
                conn.commit()
                updated = cursor.rowcount > 0
                if updated:
                    logger.info(f"Updated alias for wallet {wallet_address} to '{wallet_alias}' for user {user_id}")
                return updated
                
            except Exception as e:
                logger.error(f"Failed to set wallet alias: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def format_wallet_display(self, wallet_address: str, wallet_alias: str = None) -> str:
        """Format wallet for display with alias and shortened address"""
        # Shorten address: 0x023a...2355
        shortened = f"{wallet_address[:6]}...{wallet_address[-4:]}"
        
        if wallet_alias:
            return f"{wallet_alias}\n{shortened}"
        else:
            return shortened
    
    def get_wallet_subscribers(self, wallet_address: str) -> List[int]:
        """Get all user IDs watching a specific wallet"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address
                wallet_address = wallet_address.lower()
                
                cursor.execute(
                    """
                    SELECT u.telegram_id 
                    FROM watched_wallets w
                    JOIN users u ON w.user_id = u.id
                    WHERE w.wallet_address = ? AND w.enabled = 1
                    """,
                    (wallet_address,)
                )
                
                return [row['telegram_id'] for row in cursor.fetchall()]
                
            except Exception as e:
                logger.error(f"Failed to get wallet subscribers: {e}")
                raise
            finally:
                conn.close()
    
    def get_all_active_wallets(self) -> List[str]:
        """Get all unique wallets being watched by any user"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                cursor.execute(
                    """
                    SELECT DISTINCT wallet_address FROM watched_wallets 
                    WHERE enabled = 1
                    """
                )
                
                return [row['wallet_address'] for row in cursor.fetchall()]
                
            except Exception as e:
                logger.error(f"Failed to get all active wallets: {e}")
                raise
            finally:
                conn.close()
    
    def is_event_processed(self, event_key: str) -> bool:
        """Check if an event has already been processed"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                cursor.execute(
                    "SELECT id FROM processed_events WHERE event_key = ?",
                    (event_key,)
                )
                
                return cursor.fetchone() is not None
                
            except Exception as e:
                logger.error(f"Failed to check if event is processed: {e}")
                raise
            finally:
                conn.close()
    
    def mark_event_processed(self, event_key: str, wallet_address: str):
        """Mark an event as processed"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address
                wallet_address = wallet_address.lower()
                
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO processed_events (event_key, wallet_address)
                    VALUES (?, ?)
                    """,
                    (event_key, wallet_address)
                )
                
                conn.commit()
                
            except Exception as e:
                logger.error(f"Failed to mark event as processed: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def cleanup_old_events(self, days: int = 7):
        """Clean up processed events older than specified days"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                cursor.execute(
                    """
                    DELETE FROM processed_events 
                    WHERE created_at < datetime('now', '-' || ? || ' days')
                    """,
                    (days,)
                )
                
                deleted = cursor.rowcount
                conn.commit()
                
                if deleted > 0:
                    logger.info(f"Cleaned up {deleted} old processed events")
                
                return deleted
                
            except Exception as e:
                logger.error(f"Failed to cleanup old events: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def get_user_count(self) -> int:
        """Get total number of users"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as count FROM users")
                return cursor.fetchone()['count']
            except Exception as e:
                logger.error(f"Failed to get user count: {e}")
                return 0
            finally:
                conn.close()
    
    def get_wallet_count(self) -> int:
        """Get total number of active watched wallets"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as count FROM watched_wallets WHERE enabled = 1")
                return cursor.fetchone()['count']
            except Exception as e:
                logger.error(f"Failed to get wallet count: {e}")
                return 0
            finally:
                conn.close()

    def get_users_with_wallets_count(self) -> int:
        """Get number of users who have at least one watched wallet"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(DISTINCT user_id) as count FROM watched_wallets WHERE enabled = 1")
                return cursor.fetchone()['count']
            except Exception as e:
                logger.error(f"Failed to get users with wallets count: {e}")
                return 0
            finally:
                conn.close()

    def get_unique_wallet_addresses_count(self) -> int:
        """Get number of unique wallet addresses being monitored"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(DISTINCT wallet_address) as count FROM watched_wallets WHERE enabled = 1")
                return cursor.fetchone()['count']
            except Exception as e:
                logger.error(f"Failed to get unique wallet addresses count: {e}")
                return 0
            finally:
                conn.close()

    def record_alert(self, user_id: int, wallet_address: str):
        """Record an alert sent to a user for a wallet"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO alert_history (user_id, wallet_address) VALUES (?, ?)",
                    (user_id, wallet_address.lower())
                )
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to record alert: {e}")
                conn.rollback()
            finally:
                conn.close()

    def get_total_alerts_count(self) -> int:
        """Get total number of alerts sent"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as count FROM alert_history")
                return cursor.fetchone()['count']
            except Exception as e:
                logger.error(f"Failed to get total alerts count: {e}")
                return 0
            finally:
                conn.close()

    def get_alerts_today_count(self) -> int:
        """Get number of alerts sent today"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) as count FROM alert_history WHERE DATE(created_at) = DATE('now')"
                )
                return cursor.fetchone()['count']
            except Exception as e:
                logger.error(f"Failed to get alerts today count: {e}")
                return 0
            finally:
                conn.close()

    def set_wallet_filter(self, user_id: int, wallet_address: str, asset: str = None,
                        side: str = None, min_value_usd: float = None) -> bool:
        """Set or update filter configuration for a user-wallet pair"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address
                wallet_address = wallet_address.lower()
                
                # Check if user watches this wallet
                cursor.execute(
                    "SELECT id FROM watched_wallets WHERE user_id = ? AND wallet_address = ?",
                    (user_id, wallet_address)
                )
                if not cursor.fetchone():
                    return False
                
                # Check if filter already exists
                cursor.execute(
                    "SELECT id FROM wallet_filters WHERE user_id = ? AND wallet_address = ?",
                    (user_id, wallet_address)
                )
                existing_row = cursor.fetchone()
                
                if existing_row:
                    # Update only the fields that are being set (non-None)
                    update_fields = []
                    update_values = []
                    
                    if asset is not None:
                        update_fields.append("asset = ?")
                        update_values.append(asset)
                    if side is not None:
                        update_fields.append("side = ?")
                        update_values.append(side)
                    if min_value_usd is not None:
                        update_fields.append("min_value_usd = ?")
                        update_values.append(min_value_usd)
                    
                    if update_fields:
                        update_fields.append("updated_at = CURRENT_TIMESTAMP")
                        update_values.extend([user_id, wallet_address])
                        
                        query = f"""
                            UPDATE wallet_filters 
                            SET {', '.join(update_fields)}
                            WHERE user_id = ? AND wallet_address = ?
                        """
                        cursor.execute(query, update_values)
                else:
                    # Insert new filter with provided values
                    cursor.execute(
                        """
                        INSERT INTO wallet_filters (user_id, wallet_address, asset, side, min_value_usd)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (user_id, wallet_address, asset, side, min_value_usd)
                    )
                
                conn.commit()
                logger.info(f"Set filter for user {user_id}, wallet {wallet_address}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to set wallet filter: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def get_wallet_filter(self, user_id: int, wallet_address: str) -> Optional[dict]:
        """Get filter configuration for a user-wallet pair"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address
                wallet_address = wallet_address.lower()
                
                cursor.execute(
                    """
                    SELECT asset, side, min_value_usd 
                    FROM wallet_filters 
                    WHERE user_id = ? AND wallet_address = ?
                    """,
                    (user_id, wallet_address)
                )
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                return {
                    'asset': row['asset'],
                    'side': row['side'],
                    'min_value_usd': row['min_value_usd']
                }
                
            except Exception as e:
                logger.error(f"Failed to get wallet filter: {e}")
                raise
            finally:
                conn.close()
    
    def clear_wallet_filter(self, user_id: int, wallet_address: str) -> bool:
        """Clear filter configuration for a user-wallet pair"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address
                wallet_address = wallet_address.lower()
                
                cursor.execute(
                    "DELETE FROM wallet_filters WHERE user_id = ? AND wallet_address = ?",
                    (user_id, wallet_address)
                )
                
                conn.commit()
                cleared = cursor.rowcount > 0
                if cleared:
                    logger.info(f"Cleared filter for user {user_id}, wallet {wallet_address}")
                return cleared
                
            except Exception as e:
                logger.error(f"Failed to clear wallet filter: {e}")
                conn.rollback()
                raise
            finally:
                conn.close()
    
    def get_user_wallets_with_filters(self, user_id: int) -> List[tuple]:
        """Get all wallets with their filter configurations for a user"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                cursor.execute(
                    """
                    SELECT w.wallet_address, w.wallet_alias, f.asset, f.side, f.min_value_usd
                    FROM watched_wallets w
                    LEFT JOIN wallet_filters f ON w.user_id = f.user_id AND w.wallet_address = f.wallet_address
                    WHERE w.user_id = ? AND w.enabled = 1
                    ORDER BY w.created_at
                    """,
                    (user_id,)
                )
                
                results = []
                for row in cursor.fetchall():
                    results.append((row['wallet_address'], row['wallet_alias'], row['asset'], row['side'], row['min_value_usd']))
                
                return results
                
            except Exception as e:
                logger.error(f"Failed to get user wallets with filters: {e}")
                raise
            finally:
                conn.close()
    
    def user_watches_wallet(self, user_id: int, wallet_address: str) -> bool:
        """Check if a user is watching a specific wallet"""
        with self.lock:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Normalize wallet address
                wallet_address = wallet_address.lower()
                
                cursor.execute(
                    "SELECT id FROM watched_wallets WHERE user_id = ? AND wallet_address = ? AND enabled = 1",
                    (user_id, wallet_address)
                )
                
                return cursor.fetchone() is not None
                
            except Exception as e:
                logger.error(f"Failed to check if user watches wallet: {e}")
                return False
            finally:
                conn.close()