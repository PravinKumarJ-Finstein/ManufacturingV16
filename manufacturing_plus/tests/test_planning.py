# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Tests for the date engine and the auto-purchase flow.

They run against the master data seeded by manufacturing_plus.tests.fixtures.
"""

import math

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, cint, flt, getdate

from manufacturing_plus.planning.capacity import get_production_days
from manufacturing_plus.planning.expected_delivery import get_expected_delivery_date
from manufacturing_plus.planning.lead_time import get_item_lead_days
from manufacturing_plus.tests.fixtures import FG, RM_LONG, RM_SHORT, seed


class TestExpectedDeliveryDate(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()

	def test_production_days_sums_every_operation(self):
		# BOM says 60 mins per batch of 500 (= 500/hr) and 60 mins per batch of 250 (= 250/hr):
		# 6,000 -> 12 h = 1.5 d, plus 24 h = 3 d
		result = get_production_days(self.data["bom"], 6000, FG)
		self.assertAlmostEqual(result["days"], 4.5, places=3)
		self.assertEqual(len(result["operations"]), 2)
		self.assertEqual(result["operations"][0]["source"], "bom_batch_size")

	def test_production_days_scale_with_qty(self):
		self.assertAlmostEqual(get_production_days(self.data["bom"], 3000, FG)["days"], 2.25, places=3)

	def test_lead_days_come_from_item_lead_time(self):
		# purchase_time + buffer_time
		self.assertEqual(get_item_lead_days(RM_LONG, self.data["company"]), 30)
		self.assertEqual(get_item_lead_days(RM_SHORT, self.data["company"]), 12)

	def test_only_short_components_drive_the_date(self):
		result = get_expected_delivery_date(
			item_code=FG, qty=6000, transaction_date="2026-09-24", company=self.data["company"]
		)
		self.assertEqual(result["status"], "Computed")
		# the long-lead board is short, the display is not
		self.assertEqual(result["rm_lead_days"], 30)
		self.assertEqual(result["breakdown"]["rm"]["driver_item"], RM_LONG)
		self.assertAlmostEqual(result["production_days"], 4.5, places=3)
		# 30 lead + 4.5 production + whatever buffer the site is set to, rounded up
		buffer_days = cint(frappe.db.get_single_value("Manufacturing Control Setting", "buffer_days"))
		self.assertEqual(result["total_days"], math.ceil(30 + 4.5 + buffer_days))
		self.assertEqual(
			str(result["expected_delivery_date"]),
			str(add_days("2026-09-24", math.ceil(30 + 4.5 + buffer_days))),
		)

	def test_item_without_bom_uses_its_own_lead_time(self):
		result = get_expected_delivery_date(
			item_code=RM_LONG, qty=10, transaction_date="2026-09-24", company=self.data["company"]
		)
		self.assertEqual(result["status"], "Purchased Item")
		self.assertEqual(result["production_days"], 0.0)
		self.assertEqual(result["rm_lead_days"], 30)

	def test_failure_is_reported_not_raised(self):
		result = get_expected_delivery_date(item_code="DOES-NOT-EXIST", qty=1)
		self.assertIn(result["status"], ("Failed", "Purchased Item", "Service Item"))


class TestDeliveryDateFill(FrappeTestCase):
	"""Saving a Sales Order must not ask for a delivery date the app can work out."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()

	def test_saving_fills_the_delivery_date_by_itself(self):
		so = frappe.new_doc("Sales Order")
		so.company = self.data["company"]
		so.customer = frappe.db.get_value("Customer", {}, "name")
		so.transaction_date = "2026-09-24"
		so.append(
			"items",
			{"item_code": FG, "qty": 50, "rate": 2050, "warehouse": self.data["warehouse"]},
		)
		# no delivery_date given anywhere
		so.insert(ignore_permissions=True)

		self.assertTrue(so.items[0].delivery_date, "the line delivery date was left empty")
		self.assertEqual(so.items[0].delivery_date, so.items[0].mp_expected_delivery_date)
		self.assertTrue(so.delivery_date, "the parent delivery date was left empty")

	def test_a_date_the_user_typed_is_kept(self):
		so = frappe.new_doc("Sales Order")
		so.company = self.data["company"]
		so.customer = frappe.db.get_value("Customer", {}, "name")
		so.transaction_date = "2026-09-24"
		so.append(
			"items",
			{
				"item_code": FG,
				"qty": 50,
				"rate": 2050,
				"warehouse": self.data["warehouse"],
				"delivery_date": "2027-01-15",
			},
		)
		so.insert(ignore_permissions=True)

		self.assertEqual(str(so.items[0].delivery_date), "2027-01-15")
		self.assertTrue(so.items[0].mp_expected_delivery_date, "the computed date should still be stored")


class TestShortageNeverExceedsRequirement(FrappeTestCase):
	"""Another order's deficit must not be added to this order's shortage."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()

	def test_short_qty_is_capped_at_the_required_qty(self):
		from unittest.mock import patch

		from manufacturing_plus.planning import lead_time

		bom = frappe.db.get_value("BOM", {"item": FG, "docstatus": 1}, "name")

		# free stock deep in the red, as it is when earlier orders over-committed it
		with patch.object(lead_time, "get_free_qty", return_value={RM_SHORT: -6000.0, RM_LONG: -6000.0}):
			result = lead_time.get_rm_shortage(bom, 100, self.data["company"])

		for component in result["components"]:
			self.assertGreaterEqual(component["available_qty"], 0.0, "available qty went negative")
			self.assertLessEqual(
				component["short_qty"],
				component["required_qty"],
				f"{component['item_code']}: short qty is larger than the requirement",
			)


class TestOwnReservationIsNotCountedAgainstItself(FrappeTestCase):
	"""An order must not be told it is short of stock its own plan is holding."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()

	def test_the_orders_own_reservation_is_ignored(self):
		from manufacturing_plus.planning.stock import get_bin_qty, get_free_qty

		company = self.data["company"]
		on_hand = get_bin_qty([RM_SHORT], company).get(RM_SHORT, 0)
		if on_hand <= 0:
			return

		plan = frappe.get_doc(
			{
				"doctype": "Master Production Schedule",
				"company": company,
				"posting_date": "2026-09-24",
				"from_date": "2026-09-24",
				"to_date": "2026-12-31",
			}
		)
		plan.append(
			"items",
			{
				"item_code": FG,
				"planned_qty": 1,
				"delivery_date": "2026-12-01",
				"bom_no": self.data["bom"],
				"uom": "Nos",
			},
		)
		plan.flags.ignore_permissions = True
		plan.insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "MPS Stock Reservation",
				"master_production_schedule": plan.name,
				"company": company,
				"item_code": RM_SHORT,
				"warehouse": self.data["warehouse"],
				"reserved_qty": 10,
				"sales_order": "_MP-SO-OWN",
				"expiry_date": "2026-12-31",
				"status": "Active",
			}
		).insert(ignore_permissions=True)

		mine = get_free_qty([RM_SHORT], company, exclude_sales_order="_MP-SO-OWN")[RM_SHORT]
		theirs = get_free_qty([RM_SHORT], company)[RM_SHORT]

		self.assertAlmostEqual(
			mine - theirs, 10.0, places=3, msg="the order's own hold was deducted from itself"
		)
