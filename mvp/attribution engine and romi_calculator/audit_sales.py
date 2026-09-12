import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path


def audit(path):
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    groups = defaultdict(list)
    dates = []
    for row in rows:
        dt = datetime.strptime(row["Время"], "%d.%m.%Y %H:%M:%S")
        amount = Decimal(row["Сумма"].replace("\u00a0", "").replace(" ", "").replace(",", "."))
        groups[(row["Номер студента"], dt)].append(amount)
        dates.append(dt)
    buyer_groups = Counter(uid for uid, _ in groups)
    equal_groups = [v for v in groups.values() if len(v) > 1 and len(set(v)) == 1]
    total = sum(sum(v) for v in groups.values())
    alternative = sum(v[0] if len(v) > 1 and len(set(v)) == 1 else sum(v) for v in groups.values())
    return {"data_origin": "provided_sales_csv", "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "rows": len(rows), "buyers": len(buyer_groups), "courses": len({r["Курс"] for r in rows}),
            "first_timestamp_naive": min(dates).isoformat(), "last_timestamp_naive": max(dates).isoformat(),
            "timezone": "not specified in source", "calendar_dates_spanned": (max(dates).date()-min(dates).date()).days+1,
            "exact_duplicate_rows": len(rows)-len({tuple(r.values()) for r in rows}),
            "candidate_order_groups": len(groups), "multi_course_groups": sum(len(v)>1 for v in groups.values()),
            "equal_amount_multiline_groups": len(equal_groups),
            "unequal_multiline_amounts": [[str(x) for x in v] for v in groups.values() if len(v)>1 and len(set(v))>1],
            "buyers_with_repeat_groups": sum(n>1 for n in buyer_groups.values()),
            "groups_after_first_observed": sum(n-1 for n in buyer_groups.values()),
            "line_amount_sum_rub": str(total),
            "alternative_equal_rows_are_repeated_order_total_rub": str(alternative),
            "assumption_sensitivity_rub": str(total-alternative),
            "unknown_source_share": 1.0,
            "note": "Candidate groups are not verified orders. Amount sum is not verified cash revenue."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
