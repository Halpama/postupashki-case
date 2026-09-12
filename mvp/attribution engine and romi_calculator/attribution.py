from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

MODELS = ("first_touch", "last_touch", "linear", "time_decay",
          "position_based", "last_non_direct")
KINDS = {"paid", "owned", "organic", "direct"}
EVIDENCE = {"tracked", "self_report", "inferred"}
EVENTS = {"click", "bot_start", "source_bound_lead"}
VERSION = "rules-v1"


def timestamp(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timestamp must have a timezone")
    return dt


def cents(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount * 100 != (amount * 100).to_integral_value():
        raise ValueError("Money must be finite and have at most two decimals")
    return int(amount * 100)


def prepare(orders, touches):
    order_ids, user_times = set(), set()
    clean_orders = []
    for o in orders:
        for key in ("order_id", "user_id", "paid_at", "net_revenue"):
            if key not in o or o[key] is None or o[key] == "":
                raise ValueError(f"Missing order field: {key}")
        if o["order_id"] in order_ids:
            raise ValueError("Duplicate order_id")
        order_ids.add(o["order_id"])
        dt = timestamp(o["paid_at"])
        if (o["user_id"], dt) in user_times:
            raise ValueError("Same-user simultaneous orders: consolidate or resolve upstream")
        user_times.add((o["user_id"], dt))
        clean_orders.append(dict(o, _time=dt, _cents=cents(o["net_revenue"])))
    clean_touches = []
    ids = {}
    for t in touches:
        for key in ("touch_id", "user_id", "occurred_at", "source_id", "kind",
                    "event_type", "evidence"):
            if not t.get(key):
                raise ValueError(f"Missing touch field: {key}")
        if t["kind"] not in KINDS or t["evidence"] not in EVIDENCE:
            raise ValueError("Unknown touch kind/evidence")
        if t["touch_id"] in ids:
            if ids[t["touch_id"]] != t:
                raise ValueError("Conflicting duplicate touch_id")
            continue
        ids[t["touch_id"]] = t
        clean_touches.append(dict(t, _time=timestamp(t["occurred_at"])))
    by_user = defaultdict(list)
    for t in sorted(clean_touches, key=lambda t: (t["_time"], t["touch_id"])):
        if t["evidence"] != "tracked" or t["event_type"] not in EVENTS:
            continue
        by_user[t["user_id"]].append(t)
    return sorted(clean_orders, key=lambda o: (o["_time"], o["order_id"])), by_user


def model_weights(path, model, paid_at, half_life_days=7):
    if model == "last_non_direct":
        non_direct = [t for t in path if t["kind"] != "direct"]
        chosen = (non_direct or path)[-1:]
        return chosen, [Decimal(1)] if chosen else []
    if not path:
        return [], []
    n = len(path)
    if model == "first_touch":
        return path[:1], [Decimal(1)]
    if model == "last_touch":
        return path[-1:], [Decimal(1)]
    if model == "linear":
        raw = [Decimal(1)] * n
    elif model == "time_decay":
        raw = [Decimal(2) ** (-Decimal(str((paid_at-t["_time"]).total_seconds()))
                             / Decimal(str(86400 * half_life_days))) for t in path]
    elif model == "position_based":
        if n <= 2:
            raw = [Decimal(1)] * n
        else:
            raw = [Decimal("0.4")] + [Decimal("0.2") / (n-2)] * (n-2) + [Decimal("0.4")]
    else:
        raise ValueError(f"Unknown model: {model}")
    total = sum(raw)
    return path, [w / total for w in raw]


def allocate_cents(total, weights):
    magnitude = abs(total)
    exact = [magnitude * w for w in weights]
    result = [int(x.to_integral_value(rounding=ROUND_FLOOR)) for x in exact]
    remainder = magnitude - sum(result)
    for i in sorted(range(len(result)), key=lambda i: (-(exact[i]-result[i]), i))[:remainder]:
        result[i] += 1
    return [v if total >= 0 else -v for v in result]


def attribute(orders, touches, model="last_non_direct", window_days=30,
              half_life_days=7, tracking_started_at=None):
    if model not in MODELS or window_days <= 0 or half_life_days <= 0:
        raise ValueError("Invalid attribution configuration")
    clean_orders, by_user = prepare(orders, touches)
    started = timestamp(tracking_started_at) if tracking_started_at else None
    previous = {}
    result = []
    for order in clean_orders:
        uid, paid_at = order["user_id"], order["_time"]
        lower = paid_at - timedelta(days=window_days)
        prev = previous.get(uid)
        path = [t for t in by_user[uid] if lower <= t["_time"] < paid_at
                and (prev is None or t["_time"] > prev)]
        sessions, collapsed = {}, []
        for t in path:
            key = (t["source_id"], t.get("placement_id"), t.get("creative_id"))
            if key in sessions and t["_time"] - sessions[key] < timedelta(minutes=30):
                continue
            sessions[key] = t["_time"]
            collapsed.append(t)
        path = collapsed
        chosen, weights = model_weights(path, model, paid_at, half_life_days)
        previous[uid] = paid_at
        boundary = max(lower, prev) if prev else lower
        if not chosen:
            chosen = [{"touch_id": None, "source_id": "unknown", "kind": "unknown"}]
            weights = [Decimal(1)]
        parts = allocate_cents(order["_cents"], weights)
        for touch, weight, part in zip(chosen, weights, parts):
            result.append({"order_id": order["order_id"], "model": model,
                           "model_version": VERSION, "window_days": window_days,
                           "half_life_days": half_life_days,
                           "touch_id": touch["touch_id"], "source_id": touch["source_id"],
                           "placement_id": touch.get("placement_id"),
                           "creative_id": touch.get("creative_id"), "kind": touch["kind"],
                           "weight": float(weight), "attributed_revenue": f"{Decimal(part)/100:.2f}",
                           "repeat_in_observed_history": prev is not None,
                           "window_completeness": ("unknown" if started is None else
                                                   "complete" if started <= boundary else "partial"),
                           "path_timestamp_tie": len({t["_time"] for t in path}) < len(path)})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON with orders, touches, data_origin")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=MODELS, default="last_non_direct")
    parser.add_argument("--window-days", type=float, default=30)
    parser.add_argument("--half-life-days", type=float, default=7)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    if data.get("data_origin") not in {"synthetic", "real"}:
        parser.error("data_origin must explicitly be synthetic or real")
    result = attribute(data["orders"], data["touches"], args.model, args.window_days,
                       args.half_life_days, data.get("tracking_started_at"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"data_origin": data["data_origin"], "allocations": result},
                                      ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
