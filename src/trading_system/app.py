"""Phase-0 application bootstrap with fail-closed startup."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import IO

from trading_system.config import TradingConfig, load_config
from trading_system.decimal_context import assert_decimal_context, configure_decimal_context
from trading_system.domain.system import SystemState
from trading_system.exceptions import KillSwitchLatchedError, TradingSystemError
from trading_system.operations.logging import StructuredLogger, configure_structured_logging
from trading_system.risk.kill_switch import FileKillSwitchStore
from trading_system.security.live_gate import assert_environment_start_allowed


class TradingApplication:
    """Security baseline only; this class has no broker dependency or order path."""

    def __init__(
        self,
        *,
        config: TradingConfig,
        kill_switch: FileKillSwitchStore,
        logger: StructuredLogger,
    ) -> None:
        self._config = config
        self._kill_switch = kill_switch
        self._logger = logger
        self._state = SystemState.BOOTING

    @classmethod
    def bootstrap(
        cls,
        defaults_path: Path,
        environment_path: Path,
        *,
        environ: Mapping[str, str] | None = None,
        log_stream: IO[str] | None = None,
        artifact_digest: str = "development-unverified",
    ) -> TradingApplication:
        """Pin arithmetic before parsing any financial configuration (§12.4)."""
        configure_decimal_context()
        assert_decimal_context()
        config = load_config(defaults_path, environment_path, environ=environ)
        logger = configure_structured_logging(
            config.logging,
            service=config.runtime.service_name,
            environment=config.environment,
            config_hash=config.canonical_hash(),
            artifact_digest=artifact_digest,
            stream=log_stream,
        )
        kill_switch = FileKillSwitchStore(config.kill_switch.state_file)
        kill_switch.initialize()
        return cls(config=config, kill_switch=kill_switch, logger=logger)

    @property
    def config(self) -> TradingConfig:
        """Return immutable validated configuration."""
        return self._config

    @property
    def state(self) -> SystemState:
        """Return the explicit lifecycle state."""
        return self._state

    @property
    def kill_switch(self) -> FileKillSwitchStore:
        """Return the durable kill-switch store for read-only operator tooling."""
        return self._kill_switch

    def start(self) -> SystemState:
        """Enter simulation readiness only after all Phase-0 controls pass."""
        try:
            assert_decimal_context()
            if self._kill_switch.is_global_latched():
                raise KillSwitchLatchedError("global kill switch is latched")
            assert_environment_start_allowed(self._config)
        except TradingSystemError as exc:
            self._state = SystemState.HALTED
            self._logger.critical(
                "startup_safety_check_failed",
                exc_info=exc,
                error_type=type(exc).__name__,
                requested_environment=self._config.environment.value,
            )
            raise
        except Exception as exc:
            self._state = SystemState.HALTED
            self._logger.critical(
                "startup_unexpected_exception",
                exc_info=exc,
                requested_environment=self._config.environment.value,
            )
            raise
        self._state = SystemState.READY_SIMULATION
        self._logger.info("startup_ready", state=self._state.value)
        return self._state

    def stop(self) -> SystemState:
        """Stop the Phase-0 process without any broker-side action."""
        self._state = SystemState.STOPPED
        self._logger.info("shutdown_complete", state=self._state.value)
        return self._state
