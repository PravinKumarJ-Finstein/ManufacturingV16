# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""The app's own MRP view counts each Sales Order line once."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from manufacturing_plus.manufacturing_plus.report.material_requirement_plan.material_requirement_plan import (
	execute,
	summarise,
)


class TestMaterialRequirementPlan(FrappeTestCase):
	def test_stock_is_not_summed_across_lines(self):
		# the same 2,000 on hand seen by two Sales Order lines is still 2,000
		rows = [
			frappe._dict(
				item_code="RM-1",
				required_qty=6000,
				available_qty=2000,
				short_qty=4000,
				ordered_qty=0,
				received_qty=0,
				lead_time_days=30,
				required_by_date="2026-10-01",
				sales_order="SO-1",
				status="Short",
			),
			frappe._dict(
				item_code="RM-1",
				required_qty=3000,
				available_qty=2000,
				short_qty=1000,
				ordered_qty=0,
				received_qty=0,
				lead_time_days=30,
				required_by_date="2026-10-05",
				sales_order="SO-2",
				status="Short",
			),
		]
		summary = summarise(rows)[0]

		self.assertEqual(flt(summary["required_qty"]), 9000.0)
		self.assertEqual(flt(summary["available_qty"]), 2000.0, "stock must not be added up per line")
		self.assertEqual(flt(summary["short_qty"]), 5000.0)
		self.assertEqual(summary["sales_order_count"], 2)
		self.assertEqual(summary["required_by_date"], "2026-10-01", "the earliest date should win")

	def test_still_to_buy_takes_off_what_is_ordered(self):
		rows = [
			frappe._dict(
				item_code="RM-2",
				required_qty=5000,
				available_qty=0,
				short_qty=5000,
				ordered_qty=3000,
				received_qty=0,
				lead_time_days=10,
				required_by_date="2026-10-01",
				sales_order="SO-1",
				status="Partially Ordered",
			)
		]
		summary = summarise(rows)[0]
		self.assertEqual(flt(summary["to_buy_qty"]), 2000.0)

	def test_report_runs_and_defaults_to_open_lines(self):
		columns, rows = execute({"company": frappe.db.get_value("Company", {}, "name"), "group_by_item": 1})
		self.assertTrue(columns)
		for row in rows:
			self.assertGreaterEqual(flt(row["short_qty"]), 0.0)

	def test_line_view_has_the_sales_order_column(self):
		columns, _rows = execute({"group_by_item": 0})
		self.assertIn("sales_order", [c["fieldname"] for c in columns])

	def test_filtering_by_mps_shows_only_that_plan(self):
		mps = frappe.db.get_value(
			"Sales Order Material Demand",
			{"master_production_schedule": ["is", "set"]},
			"master_production_schedule",
		)
		if not mps:
			return

		_columns, rows = execute(
			{"master_production_schedule": mps, "group_by_item": 0, "include_covered": 1}
		)
		self.assertTrue(rows, "the MPS filter returned nothing")

		# a period plan holds several orders; every row must belong to one the plan lists
		listed = {row.sales_order for row in frappe.get_doc("Master Production Schedule", mps).sales_orders}
		for row in rows:
			self.assertEqual(row["master_production_schedule"], mps)
			self.assertIn(row["sales_order"], listed, "a row from an order the plan does not list")
