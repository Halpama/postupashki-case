import csv
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from attribution import MODELS, attribute
from incrementality import conversion_itt, sample_size


def fixture():
    def order(oid, uid, at, value):
        return dict(order_id=oid, user_id=uid, paid_at=at+"+03:00", net_revenue=value)
    def touch(tid, uid, at, source, kind, evidence="tracked", event_type="bot_start"):
        return dict(touch_id=tid, user_id=uid, occurred_at=at+"+03:00", source_id=source,
                    placement_id=source+"_placement", creative_id=source+"_creative",
                    kind=kind, evidence=evidence, event_type=event_type)
    return {"data_origin": "synthetic", "tracking_started_at": "2026-07-01T00:00:00+03:00",
            "description": "Entirely fictional users, orders and events. Not historical marketing reconstruction.",
            "orders": [order("demo_o1", "demo_u1", "2026-09-10T12:00:00", "9990.00"),
                       order("demo_o2", "demo_u1", "2026-09-12T12:00:00", "4000.00"),
                       order("demo_o3", "demo_u2", "2026-09-10T12:00:00", "3000.00"),
                       order("demo_o4", "demo_u3", "2026-09-10T12:00:00", "2000.00"),
                       order("demo_o5", "demo_u4", "2026-09-10T12:00:00", "1000.00")],
            "touches": [touch("t1", "demo_u1", "2026-08-20T12:00:00", "paid_A", "paid"),
                        touch("t2", "demo_u1", "2026-09-03T12:00:00", "owned_native", "owned"),
                        touch("t3", "demo_u1", "2026-09-09T12:00:00", "owned_sale", "owned"),
                        touch("t4", "demo_u3", "2026-09-09T12:00:00", "organic_search", "organic"),
                        touch("t5", "demo_u4", "2026-09-09T12:00:00", "direct", "direct"),
                        touch("t6", "demo_u2", "2026-09-09T12:00:00", "unverified_post", "owned", "inferred"),
                        touch("t7", "demo_u1", "2026-09-13T12:00:00", "future_paid_B", "paid")]}


def main():
    out = Path("outputs")
    out.mkdir(exist_ok=True)
    data = fixture()
    print("Business configuration:")
    print("  external paid media: model=last_non_direct, window_days=7")
    print("  owned channel and cohort LTV: model=last_non_direct, window_days=30")
    print("  14/30/60-day runs below are sensitivity analysis, not additional business defaults.")
    Path("examples").mkdir(exist_ok=True)
    Path("examples/synthetic_journeys.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")
    summary, detail = [], []
    for window in (7, 14, 30, 60):
        for model in MODELS:
            rows = attribute(data["orders"], data["touches"], model, window, 7, data["tracking_started_at"])
            totals = defaultdict(Decimal)
            for row in rows:
                totals[row["source_id"]] += Decimal(row["attributed_revenue"])
                detail.append(dict(data_origin="synthetic", **row))
            assert sum(totals.values()) == Decimal("19990.00")
            for source, revenue in sorted(totals.items()):
                summary.append({"data_origin": "synthetic", "model": model, "window_days": window,
                                "source_id": source, "attributed_revenue_rub": f"{revenue:.2f}"})
    for name, rows in (("synthetic_model_comparison.csv", summary), ("synthetic_allocations.csv", detail)):
        with (out/name).open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    experiment = {"data_origin": "synthetic", "description": "Hypothetical randomized eligible audience; not real customers.",
                  "n_treatment": 1000, "buyers_treatment": 65, "n_control": 1000, "buyers_control": 50,
                  **conversion_itt(65, 1000, 50, 1000),
                  "planning_n_per_arm_5_to_6_5_percent": sample_size(.05, .065),
                  "planning_alpha": .05, "planning_power": .8}
    (out/"synthetic_experiment.json").write_text(json.dumps(experiment, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(experiment, ensure_ascii=False, indent=2))
    print("Synthetic comparisons saved for 6 models × 4 windows. All totals reconcile to 19,990 RUB.")


if __name__ == "__main__":
    main()
