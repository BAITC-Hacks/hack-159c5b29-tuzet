"""Validated, versioned scoring configuration."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


Unit = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=1)]
PositiveFloat = Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0)]
PositiveInt = Annotated[StrictInt, Field(ge=1)]


class Weights(StrictConfig):
    @model_validator(mode="after")
    def valid_sum(self):
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-9:
            raise ValueError("сумма весов должна быть 1")
        return self


class ConsolidatorWeights(Weights):
    in_degree: Unit
    in_kzt: Unit
    in_tx: Unit
    seed_reach: Unit


class DistributorWeights(Weights):
    out_degree: Unit
    out_tx: Unit
    out_kzt: Unit


class TransitWeights(Weights):
    balance: Unit
    temporal: Unit


class CoordinatorWeights(Weights):
    betweenness: Unit
    seed_exposure: Unit
    cross_cluster: Unit


class RoleWeights(StrictConfig):
    consolidator: ConsolidatorWeights
    distributor: DistributorWeights
    transit: TransitWeights
    coordinator: CoordinatorWeights


class TerminalScore(StrictConfig):
    base: Unit
    in_kzt: Unit
    days: Unit
    cap: Unit
    days_scale: PositiveInt

    @model_validator(mode="after")
    def valid_cap(self):
        if self.cap < self.base:
            raise ValueError("cap должен быть не меньше base")
        return self


class RolesConfig(StrictConfig):
    minimum_score: Unit
    censored_role_score_cap: Unit
    consolidator_min_in_degree: PositiveInt
    distributor_min_out_degree: PositiveInt
    transit_min_ratio: PositiveFloat
    transit_max_ratio: PositiveFloat
    coordinator_betweenness_percentile: Annotated[float, Field(strict=True, allow_inf_nan=False, gt=0, le=1)]
    terminal_min_days_after_last_in: PositiveInt
    terminal_score: TerminalScore
    weights: RoleWeights

    @model_validator(mode="after")
    def valid_transit_range(self):
        if self.transit_max_ratio < self.transit_min_ratio:
            raise ValueError("transit_max_ratio должен быть не меньше transit_min_ratio")
        return self


class TypologiesConfig(StrictConfig):
    fan_in_min_counterparties: PositiveInt
    fan_out_min_counterparties: PositiveInt
    max_cycles: PositiveInt
    max_chains: PositiveInt
    max_scatter_gather: PositiveInt
    temporal_min_days: PositiveInt
    temporal_max_days: PositiveInt
    cycle_min_edges: Annotated[StrictInt, Field(ge=2, le=6)]
    cycle_max_edges: Annotated[StrictInt, Field(ge=2, le=6)]
    chain_min_edges: Annotated[StrictInt, Field(ge=2, le=4)]
    chain_max_edges: Annotated[StrictInt, Field(ge=2, le=4)]
    scatter_min_branches: Annotated[StrictInt, Field(ge=2)]
    repeated_min_occurrences: Annotated[StrictInt, Field(ge=2)]
    synchronous_min_counterparties: PositiveInt
    burst_min_operations: PositiveInt
    burst_multiplier: PositiveFloat

    @model_validator(mode="after")
    def valid_ranges(self):
        for name in ("temporal", "cycle", "chain"):
            low = getattr(self, f"{name}_min_days" if name == "temporal" else f"{name}_min_edges")
            high = getattr(self, f"{name}_max_days" if name == "temporal" else f"{name}_max_edges")
            if low > high:
                raise ValueError(f"{name}: минимум больше максимума")
        return self


class PeriodConfig(StrictConfig):
    start: date
    end: date

    @model_validator(mode="after")
    def ordered(self):
        if self.start > self.end:
            raise ValueError("начало периода позже конца")
        return self


class CommunityConfig(StrictConfig):
    seed: StrictInt
    resolution: PositiveFloat


class StructuralWeights(Weights):
    betweenness: Unit
    pagerank: Unit
    cross_cluster: Unit


class FlowWeights(Weights):
    turnover: Unit
    transaction_count: Unit


class PriorityConfig(Weights):
    structural: Unit
    seed_exposure: Unit
    flow: Unit
    typology: Unit
    temporal: Unit
    structural_components: StructuralWeights
    flow_components: FlowWeights

    @model_validator(mode="after")
    def valid_sum(self):
        values = (self.structural, self.seed_exposure, self.flow, self.typology, self.temporal)
        if abs(sum(values) - 1.0) > 1e-9:
            raise ValueError("сумма весов должна быть 1")
        return self


class ScoringConfig(StrictConfig):
    methodology_version: str
    artifact_version: str
    period: PeriodConfig
    community: CommunityConfig
    roles: RolesConfig
    typologies: TypologiesConfig
    priority: PriorityConfig
