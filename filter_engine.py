"""
Filter engine for Hyperliquid wallet events.
Evaluates whether events match user-configured filters.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class FilterEngine:
    """Evaluates wallet events against user filters"""
    
    @staticmethod
    def matches_filters(event: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
        """
        Evaluate if an event matches the configured filters
        
        Args:
            event: Hyperliquid event data (fill data)
            filters: Filter configuration dict with keys: asset, side, min_value_usd
        
        Returns:
            True if event matches all filters, False otherwise
        """
        if not filters:
            # No filters means match everything
            return True
        
        # Check if all filter conditions match (AND logic)
        if not FilterEngine._check_asset_filter(event, filters):
            return False
        
        if not FilterEngine._check_side_filter(event, filters):
            return False
        
        if not FilterEngine._check_min_value_filter(event, filters):
            return False
        
        return True
    
    @staticmethod
    def _check_asset_filter(event: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if event matches asset filter"""
        asset_filter = filters.get('asset')
        if not asset_filter:
            return True  # No asset filter
        
        event_asset = event.get('coin', '').upper()
        
        # Normalize event asset (remove -PERP suffix for comparison)
        event_asset_normalized = event_asset.replace('-PERP', '')
        
        # Parse filter assets (comma-separated for multi-asset support)
        filter_assets = [a.strip().upper() for a in asset_filter.split(',')]
        
        # Check if event asset matches any of the filter assets (OR logic)
        for filter_asset in filter_assets:
            filter_asset_normalized = filter_asset.replace('-PERP', '')
            if event_asset_normalized == filter_asset_normalized:
                return True
        
        return False
    
    @staticmethod
    def _check_side_filter(event: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if event matches side filter"""
        side_filter = filters.get('side')
        if not side_filter:
            return True  # No side filter
        
        event_side = event.get('side', '').upper()
        filter_side = side_filter.upper()
        
        # Map Hyperliquid side codes to BUY/SELL
        event_side_normalized = 'BUY' if event_side == 'B' else 'SELL'
        
        return event_side_normalized == filter_side
    
    @staticmethod
    def _check_min_value_filter(event: Dict[str, Any], filters: Dict[str, Any]) -> bool:
        """Check if event matches minimum value filter"""
        min_value = filters.get('min_value_usd')
        if min_value is None:
            return True  # No min value filter
        
        # Calculate trade value from event data
        try:
            size = float(event.get('sz', 0))
            price = float(event.get('px', 0))
            trade_value = size * price
            
            return trade_value >= min_value
        except (ValueError, TypeError):
            logger.warning(f"Failed to calculate trade value for event: {event}")
            return False
    
    @staticmethod
    def validate_filter_type(filter_type: str) -> bool:
        """Validate filter type"""
        valid_types = ['asset', 'side', 'min_value']
        return filter_type in valid_types
    
    @staticmethod
    def validate_side(side: str) -> bool:
        """Validate side value"""
        valid_sides = ['BUY', 'SELL']
        return side.upper() in valid_sides
    
    @staticmethod
    def validate_min_value(value_str: str) -> Optional[float]:
        """Validate and parse minimum value"""
        try:
            value = float(value_str)
            if value < 0:
                return None
            return value
        except ValueError:
            return None