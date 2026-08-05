"""Typed failures used at security and configuration boundaries."""


class TradingSystemError(Exception):
    """Base class for expected trading-system failures."""


class DecimalContextError(TradingSystemError):
    """The process decimal context is not pinned to the required settings."""


class ConfigurationError(TradingSystemError):
    """Configuration could not be parsed or safely validated."""


class EnvironmentMismatchError(ConfigurationError):
    """The selected environment does not match the loaded configuration."""


class EnvironmentUnavailableError(TradingSystemError):
    """The requested environment is intentionally unavailable in this phase."""


class KillSwitchPersistenceError(TradingSystemError):
    """Durable emergency state could not be read or written safely."""


class KillSwitchLatchedError(TradingSystemError):
    """Startup was blocked by a durable kill-switch latch."""


class PaperReadinessError(TradingSystemError):
    """Paper trading was requested before all mandatory controls were ready."""


class ReconciliationError(TradingSystemError):
    """Broker and durable local state could not be explained safely."""


class RiskRejectedError(TradingSystemError):
    """A centrally evaluated order plan was rejected."""


class OrderStateError(TradingSystemError):
    """An order lifecycle transition violates the state machine."""
