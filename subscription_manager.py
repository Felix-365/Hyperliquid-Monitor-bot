"""
Wallet subscription manager for Hyperliquid WebSocket connections.
Handles multiple wallet subscriptions, reconnection logic, and event routing.
"""

import asyncio
import json
import logging
import time
import hashlib
from typing import Dict, Set, Optional, Callable
import websockets

logger = logging.getLogger(__name__)

class WalletSubscriptionManager:
    """Manages Hyperliquid WebSocket subscriptions for multiple wallets"""
    
    def __init__(self, ws_url: str, event_callback: Callable):
        """
        Initialize subscription manager
        
        Args:
            ws_url: WebSocket URL for Hyperliquid
            event_callback: Function to call when wallet events are received
        """
        self.ws_url = ws_url
        self.event_callback = event_callback
        
        # State management
        self.subscribed_wallets = set()
        self.websocket = None
        self.monitoring_active = False
        self.reconnect_task = None
        self.last_activity_time = None
        
        # Reconnection settings
        self.reconnect_delay = 1  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        
    async def add_wallet(self, wallet_address: str):
        """Add a wallet to monitoring"""
        wallet_address = wallet_address.lower()
        
        if wallet_address in self.subscribed_wallets:
            logger.info(f"Wallet {wallet_address} already subscribed")
            return
        
        self.subscribed_wallets.add(wallet_address)
        logger.info(f"Added wallet {wallet_address} to monitoring")
        
        # If already connected, subscribe to the new wallet
        if self.websocket and self.monitoring_active:
            await self._subscribe_wallet(wallet_address)
    
    async def remove_wallet(self, wallet_address: str):
        """Remove a wallet from monitoring"""
        wallet_address = wallet_address.lower()
        
        if wallet_address not in self.subscribed_wallets:
            logger.info(f"Wallet {wallet_address} not in subscriptions")
            return
        
        self.subscribed_wallets.remove(wallet_address)
        logger.info(f"Removed wallet {wallet_address} from monitoring")
        
        # If no wallets left, we could disconnect, but let's keep connection alive
        # for potential quick re-subscriptions
    
    async def start_monitoring(self):
        """Start the WebSocket monitoring loop"""
        if self.monitoring_active:
            logger.info("Monitoring already active")
            return
        
        self.monitoring_active = True
        logger.info("Monitoring loop started")
        await self._monitoring_loop()
        logger.info("Monitoring loop ended")
    
    async def stop_monitoring(self):
        """Stop the WebSocket monitoring loop"""
        logger.info("Stopping monitoring")
        self.monitoring_active = False
        
        if self.reconnect_task:
            self.reconnect_task.cancel()
            self.reconnect_task = None
        
        if self.websocket:
            try:
                await self.websocket.close()
            except:
                pass
            self.websocket = None
        
        logger.info("Monitoring stopped")
        
        # Give the monitoring loop a moment to exit cleanly
        await asyncio.sleep(0.1)
    
    async def _monitoring_loop(self):
        """Main monitoring loop with reconnection logic"""
        logger.info("Starting monitoring loop")
        while self.monitoring_active:
            try:
                await self._connect_and_subscribe()
                # Reset reconnect delay on successful connection
                self.reconnect_delay = 1
                self.reconnect_attempts = 0
                
                logger.info("Connection successful, entering message processing loop")
                
                # Process messages until disconnected
                await self._process_messages()
                
            except websockets.exceptions.WebSocketException as e:
                logger.error(f"WebSocket error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error in monitoring loop: {e}")
            finally:
                logger.info("Monitoring loop iteration completed, cleaning up connection")
                if self.websocket:
                    try:
                        await self.websocket.close()
                    except:
                        pass
                    self.websocket = None
                
                # Reconnection logic with exponential backoff
                if self.monitoring_active and self.subscribed_wallets:
                    logger.info("Scheduling reconnection")
                    await self._schedule_reconnect()
                else:
                    logger.info("No wallets to monitor or monitoring stopped, exiting loop")
    
    async def _connect_and_subscribe(self):
        """Connect to WebSocket and subscribe to all wallets"""
        logger.info("Connecting to Hyperliquid WebSocket")
        
        try:
            self.websocket = await websockets.connect(self.ws_url)
            logger.info("Connected to Hyperliquid")
        except Exception as e:
            logger.error(f"Failed to connect to Hyperliquid WebSocket: {e}")
            raise
        
        # Subscribe to all monitored wallets
        for wallet_address in self.subscribed_wallets:
            try:
                await self._subscribe_wallet(wallet_address)
            except Exception as e:
                logger.error(f"Failed to subscribe to wallet {wallet_address}: {e}")
        
        logger.info(f"Subscribed to {len(self.subscribed_wallets)} wallets")
    
    async def _subscribe_wallet(self, wallet_address: str):
        """Subscribe to a specific wallet"""
        subscribe_message = {
            "method": "subscribe",
            "subscription": {
                "type": "userFills",
                "user": wallet_address
            }
        }
        
        try:
            await self.websocket.send(json.dumps(subscribe_message))
            logger.info(f"Subscription message sent for wallet: {wallet_address}")
        except Exception as e:
            logger.error(f"Failed to send subscription for wallet {wallet_address}: {e}")
            raise
    
    async def _process_messages(self):
        """Process incoming WebSocket messages"""
        while self.monitoring_active and self.websocket:
            try:
                message = await asyncio.wait_for(self.websocket.recv(), timeout=30.0)
                data = json.loads(message)
                
                # Update last activity time
                self.last_activity_time = time.time()
                
                # Process the message
                await self._handle_message(data)
                
            except asyncio.TimeoutError:
                # Keepalive check - if no messages for too long, reconnect
                if time.time() - (self.last_activity_time or time.time()) > 60:
                    logger.warning("No messages received for 60 seconds, reconnecting")
                    break
                continue
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse WebSocket message: {e}")
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                break
    
    async def _handle_message(self, data: dict):
        """Handle incoming WebSocket message"""
        channel = data.get("channel")
        
        if channel == "subscriptionResponse":
            logger.info("Subscription confirmed")
            return
        
        if channel == "userFills":
            message_data = data.get("data", {})
            is_snapshot = message_data.get("isSnapshot", False)
            
            if is_snapshot:
                logger.info("Received snapshot - ignoring for alerts")
                return
            
            # This is a real-time fill
            fills = message_data.get("fills", [])
            if fills:
                logger.info("New wallet event detected")
                # Extract wallet address from the message data
                wallet_address = message_data.get("user", "unknown")
                
                for fill in fills:
                    # Generate event key for deduplication
                    event_key = self._generate_event_key(fill, wallet_address)
                    
                    # Call the event callback with the fill data and event key
                    await self.event_callback(fill, wallet_address, event_key)
    
    def _generate_event_key(self, fill: dict, wallet_address: str) -> str:
        """Generate a unique key for event deduplication"""
        # Use available fields to create a deterministic fingerprint
        key_parts = [
            wallet_address.lower(),
            fill.get("coin", ""),
            fill.get("side", ""),
            fill.get("sz", ""),
            fill.get("px", ""),
            str(fill.get("time", 0)),
            str(fill.get("hash", "")),
            str(fill.get("tid", 0))
        ]
        
        key_string = "|".join(key_parts)
        return hashlib.sha256(key_string.encode()).hexdigest()
    
    async def _schedule_reconnect(self):
        """Schedule reconnection with exponential backoff"""
        self.reconnect_attempts += 1
        
        # Calculate delay with exponential backoff
        delay = min(self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)), 
                   self.max_reconnect_delay)
        
        logger.info(f"Reconnecting in {delay} seconds (attempt {self.reconnect_attempts})")
        await asyncio.sleep(delay)
    
    def get_status(self) -> dict:
        """Get current status of the subscription manager"""
        return {
            "connected": self.websocket is not None,
            "monitoring_active": self.monitoring_active,
            "subscribed_wallets": len(self.subscribed_wallets),
            "reconnect_attempts": self.reconnect_attempts,
            "last_activity": self.last_activity_time
        }
    
    def get_time_since_last_activity(self) -> Optional[float]:
        """Get seconds since last activity"""
        if self.last_activity_time is None:
            return None
        return time.time() - self.last_activity_time