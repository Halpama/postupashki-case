import copy
import unittest
from collections import defaultdict
from decimal import Decimal

from attribution import MODELS, attribute
from demo import fixture
from incrementality import conversion_itt, sample_size


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.data = fixture()

    def run_model(self, model="last_non_direct", window=30):
        return attribute(self.data["orders"], self.data["touches"], model, window,
                         tracking_started_at=self.data["tracking_started_at"])

    def test_money_reconciles_per_order_every_model_window(self):
        for model in MODELS:
            for window in (7, 14, 30, 60):
                sums, weights = defaultdict(Decimal), defaultdict(float)
                for row in self.run_model(model, window):
                    sums[row["order_id"]] += Decimal(row["attributed_revenue"])
                    weights[row["order_id"]] += row["weight"]
                for order in self.data["orders"]:
                    self.assertEqual(sums[order["order_id"]], Decimal(order["net_revenue"]))
                    self.assertAlmostEqual(weights[order["order_id"]], 1)

    def test_repeat_future_inferred_and_organic(self):
        rows = {r["order_id"]: r for r in self.run_model()}
        self.assertEqual(rows["demo_o1"]["source_id"], "owned_sale")
        self.assertEqual(rows["demo_o2"]["kind"], "unknown")
        self.assertTrue(rows["demo_o2"]["repeat_in_observed_history"])
        self.assertEqual(rows["demo_o3"]["kind"], "unknown")
        self.assertEqual(rows["demo_o4"]["kind"], "organic")
        self.assertEqual(rows["demo_o5"]["kind"], "direct")

    def test_expected_three_touch_weights(self):
        expected = {"first_touch": [1], "last_touch": [1], "linear": [1/3]*3,
                    "position_based": [.4, .2, .4], "last_non_direct": [1]}
        for model, weights in expected.items():
            rows = [r for r in self.run_model(model) if r["order_id"] == "demo_o1"]
            for row, weight in zip(rows, weights):
                self.assertAlmostEqual(row["weight"], weight)
            self.assertEqual(len(rows), len(weights))
        decay = [r for r in self.run_model("time_decay") if r["order_id"] == "demo_o1"]
        self.assertLess(decay[0]["weight"], decay[1]["weight"])
        self.assertLess(decay[1]["weight"], decay[2]["weight"])

    def test_direct_does_not_overwrite_known_source(self):
        t = copy.deepcopy(self.data["touches"][2])
        t.update(touch_id="later_direct", occurred_at="2026-09-10T11:00:00+03:00",
                 kind="direct", source_id="direct")
        self.data["touches"].append(t)
        self.assertEqual(self.run_model()[0]["source_id"], "owned_sale")
        self.assertEqual(self.run_model("last_touch")[0]["source_id"], "direct")

    def test_window_boundaries(self):
        self.data["orders"] = self.data["orders"][:1]
        self.data["touches"] = self.data["touches"][:1]
        t = self.data["touches"][0]
        t["occurred_at"] = "2026-08-11T12:00:00+03:00"
        self.assertEqual(self.run_model()[0]["kind"], "paid")
        t["occurred_at"] = "2026-08-11T11:59:59+03:00"
        self.assertEqual(self.run_model()[0]["kind"], "unknown")
        t["occurred_at"] = "2026-09-10T12:00:00+03:00"
        self.assertEqual(self.run_model()[0]["kind"], "unknown")

    def test_idempotent_dedup_and_conflicting_duplicate(self):
        baseline = self.run_model("linear")
        self.data["touches"].append(copy.deepcopy(self.data["touches"][0]))
        self.assertEqual(self.run_model("linear"), baseline)
        self.data["touches"][-1]["source_id"] = "conflict"
        with self.assertRaises(ValueError):
            self.run_model()

    def test_session_dedup_and_timestamp_tie(self):
        t = copy.deepcopy(self.data["touches"][0])
        t.update(touch_id="extra_click", occurred_at="2026-08-20T12:10:00+03:00")
        self.data["touches"].append(t)
        self.assertEqual(len([r for r in self.run_model("linear") if r["order_id"] == "demo_o1"]), 3)
        t.update(source_id="different", occurred_at="2026-08-20T12:00:00+03:00")
        self.assertTrue(self.run_model("linear")[0]["path_timestamp_tie"])

    def test_fractional_cents_and_refunds(self):
        for amount in ("0.01", "-0.01", "0.00", "123.45"):
            self.data["orders"][0]["net_revenue"] = amount
            parts = [r for r in self.run_model("linear") if r["order_id"] == "demo_o1"]
            self.assertEqual(sum(Decimal(r["attributed_revenue"]) for r in parts), Decimal(amount))

    def test_new_episode_keeps_touch_after_previous_payment(self):
        self.data["orders"][1]["paid_at"] = "2026-09-10T12:20:00+03:00"
        a = copy.deepcopy(self.data["touches"][0])
        a.update(touch_id="before", occurred_at="2026-09-10T11:50:00+03:00")
        b = dict(a, touch_id="after", occurred_at="2026-09-10T12:10:00+03:00")
        self.data["touches"].extend([a, b])
        rows = {r["order_id"]: r for r in self.run_model()}
        self.assertEqual(rows["demo_o2"]["touch_id"], "after")

    def test_bad_order_and_timezone_are_rejected(self):
        self.data["orders"].append(copy.deepcopy(self.data["orders"][0]))
        with self.assertRaises(ValueError):
            self.run_model()
        self.data["orders"].pop()
        self.data["orders"][0]["paid_at"] = "2026-09-10T12:00:00"
        with self.assertRaises(ValueError):
            self.run_model()

    def test_partial_or_unknown_history_is_visible(self):
        self.data["tracking_started_at"] = "2026-09-01T00:00:00+03:00"
        self.assertEqual(self.run_model()[0]["window_completeness"], "partial")
        rows = attribute(self.data["orders"], self.data["touches"])
        self.assertEqual(rows[0]["window_completeness"], "unknown")


class IncrementalityTests(unittest.TestCase):
    def test_demo_lift_is_inconclusive(self):
        r = conversion_itt(65, 1000, 50, 1000)
        self.assertAlmostEqual(r["absolute_lift"], .015)
        self.assertAlmostEqual(r["relative_lift"], .3)
        self.assertLess(r["ci_low"], 0)
        self.assertGreater(r["ci_high"], 0)
        self.assertGreater(sample_size(.05, .065), 3000)

    def test_zero_conversions_still_have_uncertainty(self):
        r = conversion_itt(0, 100, 0, 100)
        self.assertIsNone(r["relative_lift"])
        self.assertLess(r["ci_low"], 0)
        self.assertGreater(r["ci_high"], 0)

    def test_invalid_sample(self):
        for args in ((2, 1, 0, 1), (0, 0, 0, 1), (1.5, 10, 0, 10)):
            with self.assertRaises(ValueError):
                conversion_itt(*args)


if __name__ == "__main__":
    unittest.main()
