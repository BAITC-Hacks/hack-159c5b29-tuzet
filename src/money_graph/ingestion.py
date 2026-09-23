"""Strict input and scoring configuration contracts."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import ValidationError

from .config_model import ScoringConfig


class DataContractError(ValueError):
    """The input or scoring configuration violates its published contract."""


@dataclass(frozen=True)
class InputData:
    edges: pd.DataFrame
    nodes: pd.DataFrame
    transactions: pd.DataFrame


def money_to_tiyn(value: Any) -> int:
    try:
        money = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise DataContractError(f"Некорректная сумма: {value}") from error
    if not money.is_finite() or money <= 0 or money.as_tuple().exponent < -2:
        raise DataContractError(f"Сумма должна быть положительной с точностью до 0,01 KZT: {value}")
    return int(money * 100)


def load_config(path: Path | None = None) -> dict[str, Any]:
    try:
        if path is None:
            source = Path(__file__).resolve().parents[2] / "config" / "scoring.yaml"
            resource = source if source.is_file() else files("money_graph").joinpath("scoring.yaml")
        else:
            resource = path
        with resource.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
        return ScoringConfig.model_validate(raw).model_dump(mode="json")
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "config"
        explanation = {
            "int_type": "ожидается целое число",
            "extra_forbidden": "неизвестный параметр",
            "missing": "обязательный параметр отсутствует",
            "finite_number": "ожидается конечное число",
            "float_type": "ожидается конечное число",
        }.get(first["type"], first["msg"])
        raise DataContractError(f"Некорректная конфигурация: {location}: {explanation}") from error
    except (yaml.YAMLError, OSError) as error:
        raise DataContractError(f"Некорректная конфигурация: {error}") from error


def _int_column(frame: pd.DataFrame, column: str, label: str) -> None:
    values = frame[column]
    if values.isna().any() or not pd.api.types.is_integer_dtype(values.dtype) or pd.api.types.is_bool_dtype(values.dtype):
        raise DataContractError(f"{label}.{column} должен быть целым без пропусков")


def load_and_validate(data_dir: Path, config: dict[str, Any] | None = None) -> InputData:
    config = config or load_config()
    names = ("edges", "nodes", "transactions")
    paths = {name: data_dir / f"{name}.parquet" for name in names}
    missing_files = [str(path) for path in paths.values() if not path.is_file()]
    if missing_files:
        raise DataContractError("Не найдены входные файлы: " + ", ".join(missing_files))
    frames = {name: pd.read_parquet(path).copy() for name, path in paths.items()}
    expected_columns = {
        "edges": {"src", "dst", "sum_kzt", "n_tx", "depth"},
        "nodes": {"gid", "depth", "is_seed"},
        "transactions": {"src", "dst", "date", "sum_kzt"},
    }
    for name, frame in frames.items():
        absent = expected_columns[name] - set(frame.columns)
        if absent or frame[list(expected_columns[name])].isna().any().any():
            raise DataContractError(f"{name}: отсутствуют или пусты обязательные поля {sorted(absent)}")
    edges, nodes, tx = frames["edges"], frames["nodes"], frames["transactions"]
    for name, frame, columns in (("edges", edges, ("src", "dst", "n_tx", "depth")), ("nodes", nodes, ("gid", "depth")), ("transactions", tx, ("src", "dst"))):
        for column in columns:
            _int_column(frame, column, name)
    if not pd.api.types.is_bool_dtype(nodes.is_seed.dtype):
        raise DataContractError("nodes.is_seed должен быть bool")
    if nodes.gid.duplicated().any() or edges.duplicated(["src", "dst"]).any():
        raise DataContractError("Повторяются gid или пары src/dst")
    if not nodes.depth.between(0, 4).all() or not edges.depth.between(1, 4).all():
        raise DataContractError("depth вне диапазона 0..4")
    if not (nodes.loc[nodes.is_seed, "depth"] == 0).all() or (nodes.loc[~nodes.is_seed, "depth"] == 0).any():
        raise DataContractError("is_seed и depth=0 не согласованы")
    gids = set(nodes.gid)
    if not (set(edges.src) | set(edges.dst) | set(tx.src) | set(tx.dst)).issubset(gids):
        raise DataContractError("В переводах найден gid без записи в nodes")
    if (edges.n_tx <= 0).any():
        raise DataContractError("n_tx должен быть положительным")
    source_depth = edges.src.map(nodes.set_index("gid").depth)
    if not (edges.depth == source_depth + 1).all():
        raise DataContractError("edges.depth должен равняться nodes.depth отправителя + 1")
    edge_amounts = edges.sum_kzt.map(money_to_tiyn)
    tx_amounts = tx.sum_kzt.map(money_to_tiyn)
    limit = 2**63 - 1
    if max(sum(map(int, edge_amounts)), sum(map(int, tx_amounts))) > limit:
        raise DataContractError("Общий оборот превышает допустимый диапазон целых тиын")
    edges["sum_tiyn"] = edge_amounts.astype("int64")
    tx["sum_tiyn"] = tx_amounts.astype("int64")
    tx["date"] = pd.to_datetime(tx.date, errors="coerce")
    if tx.date.isna().any() or not (tx.date == tx.date.dt.normalize()).all() or not tx.date.between(pd.Timestamp(config["period"]["start"]), pd.Timestamp(config["period"]["end"])).all():
        raise DataContractError("Дата операции вне периода наблюдения")
    actual = tx.groupby(["src", "dst"], as_index=False).agg(sum_tiyn=("sum_tiyn", "sum"), n_tx=("sum_tiyn", "size"))
    compared = edges[["src", "dst", "sum_tiyn", "n_tx"]].merge(actual, on=["src", "dst"], how="outer", suffixes=("_edge", "_tx"), indicator=True)
    if not (compared["_merge"] == "both").all() or not (compared.n_tx_edge == compared.n_tx_tx).all() or not ((compared.sum_tiyn_edge - compared.sum_tiyn_tx).abs() <= 1).all():
        raise DataContractError("Суммы или число операций edges и transactions не совпадают")
    tx = tx.sort_values(["date", "src", "dst", "sum_tiyn"], kind="stable").reset_index(drop=True)
    tx["duplicate_ordinal"] = tx.groupby(["date", "src", "dst", "sum_tiyn"]).cumcount() + 1
    tx["transaction_id"] = tx.apply(lambda row: f"{row.date.date()}:{int(row.src)}:{int(row.dst)}:{int(row.sum_tiyn)}:{int(row.duplicate_ordinal)}", axis=1)
    return InputData(
        edges=edges.sort_values(["src", "dst"]).reset_index(drop=True),
        nodes=nodes.sort_values("gid").reset_index(drop=True),
        transactions=tx,
    )
