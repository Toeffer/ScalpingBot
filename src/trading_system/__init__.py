"""Multi-strategy trading-system foundation."""

from trading_system.app import TradingApplication
from trading_system.config import Environment, TradingConfig

__all__ = ["Environment", "TradingApplication", "TradingConfig"]
__version__ = "0.1.0"
