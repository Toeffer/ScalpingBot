"""Strict, layered configuration with environment integrity checks.

Architecture references: §10.4, §10.7, §15.6, and §16.1.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Final, Literal

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    PositiveInt,
    ValidationError,
    WithJsonSchema,
    model_validator,
)
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver

from trading_system.decimal_context import assert_decimal_context, financial_context
from trading_system.exceptions import ConfigurationError, EnvironmentMismatchError

MAX_CONFIG_BYTES: Final = 1_048_576


class _StrictSafeLoader(yaml.SafeLoader):
    """Safe YAML loader which rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _StrictSafeLoader,
    node: MappingNode,
    *,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _parse_quoted_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, str):
        try:
            with financial_context():
                result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("must be a valid decimal string") from exc
    else:
        raise ValueError(  # noqa: TRY004 - Pydantic only wraps ValueError as validation failure.
            "financial values must be quoted decimal strings"
        )
    if not result.is_finite():
        raise ValueError("financial values must be finite")
    return result


QuotedDecimal = Annotated[
    Decimal,
    BeforeValidator(_parse_quoted_decimal),
    PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$"},
        mode="validation",
    ),
]
PositiveDecimal = Annotated[QuotedDecimal, Field(gt=Decimal("0"))]
NonNegativeDecimal = Annotated[QuotedDecimal, Field(ge=Decimal("0"))]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
ServiceName = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")]


class Environment(StrEnum):
    """Deployment environments are explicit and never inferred from a port."""

    LOCAL = "local"
    SIMULATION = "simulation"
    PAPER = "paper"
    LIVE = "live"


class LogLevel(StrEnum):
    """Allowed structured-log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StrictModel(BaseModel):
    """Frozen model which rejects misspelled and future-unknown keys."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class RuntimeConfig(StrictModel):
    """Process identity and mutable-state location."""

    service_name: ServiceName = "trading-engine"
    state_directory: Path
    live_enabled: bool = False


class LoggingConfig(StrictModel):
    """Logging controls whose security features cannot be disabled."""

    level: LogLevel = LogLevel.INFO
    destination: Literal["stdout"] = "stdout"
    format: Literal["json"] = "json"
    redaction_enabled: Literal[True] = True


class KillSwitchConfig(StrictModel):
    """Durable, fail-closed emergency-state configuration."""

    state_file: Path
    fail_closed: Literal[True] = True


class AccountRiskConfig(StrictModel):
    """Account-level limits, all expressed in the configured base currency."""

    max_gross_notional: PositiveDecimal
    max_net_notional: PositiveDecimal
    max_daily_loss: PositiveDecimal
    max_intraday_drawdown: PositiveDecimal
    max_open_orders: PositiveInt
    max_orders_per_minute: PositiveInt
    min_excess_liquidity: NonNegativeDecimal


class InstrumentRiskConfig(StrictModel):
    """Default limits per qualified instrument."""

    max_position: PositiveDecimal
    max_notional: PositiveDecimal
    max_working_quantity: PositiveDecimal
    max_spread_bps: PositiveDecimal


class OrderRiskConfig(StrictModel):
    """Limits for one proposed order."""

    max_quantity: PositiveDecimal
    max_notional: PositiveDecimal
    max_price_deviation_bps: PositiveDecimal


class CurrencyRiskConfig(StrictModel):
    """Currency allowlist and FX freshness controls."""

    enabled_trading_currencies: tuple[CurrencyCode, ...]
    max_fx_exposure_per_currency: NonNegativeDecimal
    fx_rate_max_age_ms: PositiveInt

    @model_validator(mode="after")
    def reject_duplicate_currencies(self) -> CurrencyRiskConfig:
        if len(set(self.enabled_trading_currencies)) != len(self.enabled_trading_currencies):
            raise ValueError("enabled_trading_currencies must not contain duplicates")
        return self


class MarketDataRiskConfig(StrictModel):
    """Freshness and time-synchronization limits."""

    max_quote_age_ms: PositiveInt
    max_clock_skew_ms: PositiveInt


class BrokerConfig(StrictModel):
    """Paper broker identity; credentials never belong in this model."""

    host: Literal["127.0.0.1", "localhost"] = "127.0.0.1"
    port: PositiveInt = 4002
    execution_client_id: PositiveInt = 1
    observer_client_id: PositiveInt = 2
    expected_account_hash: str | None = None
    expected_base_currency: CurrencyCode | None = None
    read_only_required: bool = True
    market_data_line_capacity: PositiveInt = 1
    max_event_queue_size: PositiveInt = 1_000

    @model_validator(mode="after")
    def require_distinct_clients(self) -> BrokerConfig:
        if self.execution_client_id == self.observer_client_id:
            raise ValueError("execution_client_id and observer_client_id must differ")
        return self


class PaperInstrumentConfig(StrictModel):
    """Exactly one explicitly qualified base-currency cash instrument in v1."""

    instrument_id: Annotated[str, Field(min_length=1, max_length=64)]
    con_id: PositiveInt
    exchange: Annotated[str, Field(min_length=1, max_length=32)]
    currency: CurrencyCode
    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "Europe/Berlin"
    regular_session_open: Annotated[str, Field(pattern=r"^\d{2}:\d{2}$")] = "09:00"
    regular_session_close: Annotated[str, Field(pattern=r"^\d{2}:\d{2}$")] = "17:30"


class PaperProbeConfig(StrictModel):
    """Paper-only integration probe, disabled unless explicitly enabled."""

    enabled: bool = False
    quantity: PositiveDecimal = Decimal("1")
    entry_time: Annotated[str, Field(pattern=r"^\d{2}:\d{2}$")] = "10:00"
    exit_time: Annotated[str, Field(pattern=r"^\d{2}:\d{2}$")] = "10:05"


class PersistenceConfig(StrictModel):
    """Only a secret reference is configured; never a database password."""

    database_url_secret_ref: str | None = None
    migration_required: Literal[True] = True


class OperationsConfig(StrictModel):
    notification_endpoint_secret_ref: str | None = None


class RiskConfig(StrictModel):
    """Phase-0 validated risk configuration."""

    base_currency: CurrencyCode
    account: AccountRiskConfig
    per_instrument: InstrumentRiskConfig
    per_order: OrderRiskConfig
    currency: CurrencyRiskConfig
    market_data: MarketDataRiskConfig

    @model_validator(mode="after")
    def require_base_currency_only(self) -> RiskConfig:
        enabled = self.currency.enabled_trading_currencies
        if enabled != (self.base_currency,):
            raise ValueError("Phase 0 permits only the base currency; FX risk is not implemented")
        return self


class TradingConfig(StrictModel):
    """Complete configuration input to the Phase-0 application."""

    schema_version: Literal[1]
    environment: Environment
    runtime: RuntimeConfig
    logging: LoggingConfig
    kill_switch: KillSwitchConfig
    risk: RiskConfig
    broker: BrokerConfig = BrokerConfig()
    paper_instrument: PaperInstrumentConfig | None = None
    paper_probe: PaperProbeConfig = PaperProbeConfig()
    persistence: PersistenceConfig = PersistenceConfig()
    operations: OperationsConfig = OperationsConfig()

    @model_validator(mode="after")
    def prevent_cross_environment_live_flag(self) -> TradingConfig:
        if self.runtime.live_enabled and self.environment is not Environment.LIVE:
            raise ValueError("live_enabled is valid only in the live environment")
        return self

    def paper_readiness_failures(self) -> tuple[str, ...]:
        """Return configuration-only paper blockers without opening a socket."""
        if self.environment is not Environment.PAPER:
            return ()
        failures: list[str] = []
        if self.paper_instrument is None:
            failures.append("paper_instrument_not_configured")
        elif self.paper_instrument.currency != self.risk.base_currency:
            failures.append("paper_instrument_not_in_base_currency")
        if self.broker.expected_account_hash is None:
            failures.append("expected_account_hash_not_configured")
        if self.broker.expected_base_currency != self.risk.base_currency:
            failures.append("broker_base_currency_not_configured")
        if self.persistence.database_url_secret_ref is None:
            failures.append("database_secret_reference_not_configured")
        return tuple(failures)

    def canonical_hash(self) -> str:
        """Return the configuration digest recorded in startup audit data (§15.6)."""
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink():
            raise ConfigurationError(f"configuration path must not be a symlink: {path}")
        size = path.stat().st_size
        if size > MAX_CONFIG_BYTES:
            raise ConfigurationError(f"configuration file exceeds {MAX_CONFIG_BYTES} bytes")
        loader = _StrictSafeLoader(path.read_text(encoding="utf-8"))
        parsed = loader.get_single_data()
    except ConfigurationError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"cannot read configuration file: {path}") from exc
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise ConfigurationError(f"configuration root must be a string-keyed mapping: {path}")
    return parsed


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _summarize_validation_error(error: ValidationError) -> str:
    summaries = []
    for item in error.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in item["loc"])
        summaries.append(f"{location}: {item['msg']}")
    return "; ".join(summaries)


def selected_environment(environ: Mapping[str, str] | None = None) -> Environment:
    """Read the sole environment selector; simulation is the safe default."""
    source = os.environ if environ is None else environ
    raw_value = source.get("TRADING_ENV", Environment.SIMULATION.value)
    try:
        return Environment(raw_value)
    except ValueError as exc:
        allowed = ", ".join(environment.value for environment in Environment)
        raise ConfigurationError(f"TRADING_ENV must be one of: {allowed}") from exc


def load_config(
    defaults_path: Path,
    environment_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> TradingConfig:
    """Load, merge, strictly validate, and bind configuration to TRADING_ENV."""
    assert_decimal_context()
    merged = _deep_merge(
        _load_yaml_mapping(defaults_path),
        _load_yaml_mapping(environment_path),
    )
    try:
        config = TradingConfig.model_validate(merged)
    except ValidationError as exc:
        summary = _summarize_validation_error(exc)
        raise ConfigurationError(f"configuration validation failed: {summary}") from exc

    expected = selected_environment(environ)
    if config.environment is not expected:
        raise EnvironmentMismatchError(
            f"TRADING_ENV={expected.value} does not match "
            f"configuration environment={config.environment.value}"
        )
    return config
