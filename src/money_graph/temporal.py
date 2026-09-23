"""Day-granularity, capacity-constrained transaction matching."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd


def match_transactions(transactions: pd.DataFrame, min_days: int, max_days: int, *, synchronous_min_counterparties: int = 3, burst_min_operations: int = 5, burst_multiplier: float = 3) -> tuple[dict[int, int], dict[int, int], list[dict[str, Any]], dict[int, dict[str, Any]]]:
    incoming = {int(gid): list(group.itertuples(index=False)) for gid, group in transactions.groupby("dst", sort=True)}
    outgoing = {int(gid): list(group.itertuples(index=False)) for gid, group in transactions.groupby("src", sort=True)}
    strict: dict[int, int] = defaultdict(int)
    same_day: dict[int, int] = defaultdict(int)
    matches: list[dict[str, Any]] = []
    for gid in sorted(set(incoming) & set(outgoing)):
        receipts = [{"row": row, "remaining": int(row.sum_tiyn)} for row in incoming[gid]]
        for sent in outgoing[gid]:
            remaining = int(sent.sum_tiyn)
            same_day[gid] += sum((pd.Timestamp(sent.date) - pd.Timestamp(item["row"].date)).days == 0 for item in receipts)
            for item in receipts:
                days = (pd.Timestamp(sent.date) - pd.Timestamp(item["row"].date)).days
                if days < min_days or days > max_days or not item["remaining"]:
                    continue
                amount = min(remaining, item["remaining"])
                if amount:
                    item["remaining"] -= amount
                    remaining -= amount
                    strict[gid] += amount
                    matches.append({
                        "node_id": str(gid), "incoming_transaction_id": item["row"].transaction_id,
                        "outgoing_transaction_id": sent.transaction_id,
                        "source": str(int(item["row"].src)), "target": str(int(sent.dst)),
                        "incoming_date": str(pd.Timestamp(item["row"].date).date()),
                        "outgoing_date": str(pd.Timestamp(sent.date).date()),
                        "days": days, "matched_tiyn": amount,
                    })
                if remaining == 0:
                    break
    daily: dict[int, dict[str, Any]] = {}
    for gid in sorted(set(incoming) | set(outgoing)):
        records: dict[str, dict[str, Any]] = defaultdict(lambda: {"in_count": 0, "out_count": 0, "in_tiyn": 0, "out_tiyn": 0, "senders": set(), "receivers": set()})
        for row in incoming.get(gid, []):
            item = records[str(pd.Timestamp(row.date).date())]
            item["in_count"] += 1
            item["in_tiyn"] += int(row.sum_tiyn)
            item["senders"].add(int(row.src))
        for row in outgoing.get(gid, []):
            item = records[str(pd.Timestamp(row.date).date())]
            item["out_count"] += 1
            item["out_tiyn"] += int(row.sum_tiyn)
            item["receivers"].add(int(row.dst))
        active_counts = [item["in_count"] + item["out_count"] for item in records.values()]
        median = float(pd.Series(active_counts).median()) if active_counts else 0.0
        daily[gid] = {
            "days": [{"date": day, "in_count": value["in_count"], "out_count": value["out_count"],
                      "in_kzt": value["in_tiyn"] / 100, "out_kzt": value["out_tiyn"] / 100,
                      "sender_count": len(value["senders"]), "receiver_count": len(value["receivers"])}
                     for day, value in sorted(records.items())],
            "synchronous_fan_in_days": sum(len(item["senders"]) >= synchronous_min_counterparties for item in records.values()),
            "synchronous_fan_out_days": sum(len(item["receivers"]) >= synchronous_min_counterparties for item in records.values()),
            "burst_days": sum(item["in_count"] + item["out_count"] >= burst_min_operations and item["in_count"] + item["out_count"] > burst_multiplier * median for item in records.values()),
            "largest_day_share": max((item["in_tiyn"] + item["out_tiyn"] for item in records.values()), default=0) / max(sum(item["in_tiyn"] + item["out_tiyn"] for item in records.values()), 1),
        }
    return strict, same_day, matches, daily
