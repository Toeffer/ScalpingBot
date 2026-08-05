"""Application bootstrap with fail-closed simulation and paper readiness."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import IO

from trading_system.brokers.ibkr.adapter import IbkrAdapter
from trading_system.config import TradingConfig, load_config
from trading_system.decimal_context import assert_decimal_context, configure_decimal_context
from trading_system.domain.system import SystemState
from trading_system.exceptions import (
    KillSwitchLatchedError,
    PaperReadinessError,
    TradingSystemError,
)
from trading_system.operations.logging import StructuredLogger, configure_structured_logging
from trading_system.reconciliation import ReconciliationReport
from trading_system.risk.kill_switch import FileKillSwitchStore
from trading_system.security.live_gate import assert_environment_start_allowed


class PaperRuntime:
    """Explicitly injected runtime dependencies required for paper readiness."""

    def __init__(self, adapter: IbkrAdapter, reconciliation: ReconciliationReport) -> None:
        self.adapter = adapter
        self.reconciliation = reconciliation


class TradingApplication:
    """Bootstrap the system without making a broker connection by default."""

    def __init__(
        self,
        *,
        config: TradingConfig,
        kill_switch: FileKillSwitchStore,
        logger: StructuredLogger,
        paper_runtime: PaperRuntime | None = None,
    ) -> None:
        self._config = config
        self._kill_switch = kill_switch
        self._logger = logger
        self._paper_runtime = paper_runtime
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
        paper_runtime: PaperRuntime | None = None,
    ) -> TradingApplication:
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
        return cls(
            config=config,
            kill_switch=kill_switch,
            logger=logger,
            paper_runtime=paper_runtime,
        )

    @property
    def config(self) -> TradingConfig:
        return self._config

    @property
    def state(self) -> SystemState:
        return self._state

    @property
    def kill_switch(self) -> FileKillSwitchStore:
        return self._kill_switch

    def start(self) -> SystemState:
        try:
            assert_decimal_context()
            if self._kill_switch.is_global_latched():
                raise KillSwitchLatchedError("global kill switch is latched")
            if self._config.environment.value == "paper":
                self._start_paper()
            else:
                assert_environment_start_allowed(self._config)
                self._state = SystemState.READY_SIMULATION
                self._logger.info("startup_ready", state=self._state.value)
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
        return self._state

    def _start_paper(self) -> None:
        blockers = self._config.paper_readiness_failures()
        if blockers:
            raise PaperReadinessError(", ".join(blockers))
        if self._paper_runtime is None:
            raise PaperReadinessError("paper_runtime_not_injected")
        self._paper_runtime.adapter.start_observer()
        if not self._paper_runtime.reconciliation.complete:
            raise PaperReadinessError(", ".join(self._paper_runtime.reconciliation.mismatches))
        self._state = SystemState.READY_PAPER
        self._logger.info("paper_startup_ready", state=self._state.value)

    def stop(self) -> SystemState:
        self._state = SystemState.STOPPED
        self._logger.info("shutdown_complete", state=self._state.value)
        return self._state
