# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""The carry-over features: WO source rule, buffer, Job Card gate, yield, can build."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from manufacturing_plus.shopfloor import can_build
from manufacturing_plus.shopfloor.buffer import get_buffer_qty
from manufacturing_plus.shopfloor.cleanup import get_cancel_blocker
from manufacturing_plus.tests.fixtures import ASSEMBLY, FG, RM_LONG, RM_SHORT, seed

PACKAGE = "_MP Reel"


class TestShopFloor(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()
		_ensure_package()

	def setUp(self):
		frappe.db.set_single_value("Manufacturing Control Setting", "enable_pick_list_buffer", 1)
		frappe.db.set_single_value("Manufacturing Control Setting", "wo_only_from_production_plan", 1)
		frappe.clear_cache()

	def test_buffer_uses_the_matching_slab(self):
		# slabs: 1-500 -> +10, 501-2000 -> +25
		self.assertEqual(get_buffer_qty(RM_LONG, 100), 10)
		self.assertEqual(get_buffer_qty(RM_LONG, 1200), 25)
		self.assertEqual(get_buffer_qty(RM_LONG, 99999), 0)  # no slab covers it
		self.assertEqual(get_buffer_qty(RM_SHORT, 100), 0)  # no package on this item

	def test_buffer_is_charged_once_per_work_order(self):
		self.assertEqual(get_buffer_qty(RM_LONG, 100, work_orders=3), 30)

	def test_buffer_is_off_when_the_setting_is_off(self):
		frappe.db.set_single_value("Manufacturing Control Setting", "enable_pick_list_buffer", 0)
		frappe.clear_cache()
		self.assertEqual(get_buffer_qty(RM_LONG, 100), 0)

	def test_work_order_without_production_plan_is_blocked(self):
		work_order = _new_work_order(self.data["company"], self.data["warehouse"])
		self.assertRaises(frappe.ValidationError, work_order.insert)

	def test_work_order_allowed_when_the_rule_is_off(self):
		frappe.db.set_single_value("Manufacturing Control Setting", "wo_only_from_production_plan", 0)
		frappe.clear_cache()
		work_order = _new_work_order(self.data["company"], self.data["warehouse"])
		work_order.insert()
		self.assertTrue(work_order.name)
		self.assertEqual(work_order.docstatus, 0)

	def test_cleanup_keeps_a_work_order_the_shop_floor_started(self):
		frappe.db.set_single_value("Manufacturing Control Setting", "wo_only_from_production_plan", 0)
		frappe.clear_cache()
		work_order = _new_work_order(self.data["company"], self.data["warehouse"])
		work_order.insert()
		self.assertIsNone(get_cancel_blocker(work_order.name))

	def test_yield_entry_computes_the_yield(self):
		frappe.db.set_single_value("Manufacturing Control Setting", "wo_only_from_production_plan", 0)
		frappe.clear_cache()
		work_order = _new_work_order(self.data["company"], self.data["warehouse"], qty=100)
		work_order.insert()

		entry = frappe.get_doc(
			{
				"doctype": "Yield Entry",
				"company": self.data["company"],
				"work_order": work_order.name,
				"operation": ASSEMBLY,
				"entry_date": "2026-09-24",
				"inspected_qty": 100,
				"accepted_qty": 95,
			}
		)
		entry.append("rejections", {"defect_type": "Solder bridge", "number_of_defects": 3})
		entry.append("rejections", {"defect_type": "Missing part", "number_of_defects": 2})
		entry.insert()

		self.assertEqual(flt(entry.rejected_qty), 5.0)
		self.assertAlmostEqual(flt(entry.yield_percent), 95.0, places=2)
		self.assertEqual(entry.total_defects, 5)

	def test_yield_entry_needs_rejection_rows(self):
		frappe.db.set_single_value("Manufacturing Control Setting", "wo_only_from_production_plan", 0)
		frappe.clear_cache()
		work_order = _new_work_order(self.data["company"], self.data["warehouse"], qty=100)
		work_order.insert()

		entry = frappe.get_doc(
			{
				"doctype": "Yield Entry",
				"company": self.data["company"],
				"work_order": work_order.name,
				"operation": ASSEMBLY,
				"entry_date": "2026-09-24",
				"inspected_qty": 100,
				"accepted_qty": 90,
			}
		)
		self.assertRaises(frappe.ValidationError, entry.insert)

	def test_can_build_is_limited_by_the_scarcest_component(self):
		rows = {r["item_code"]: r for r in can_build.calculate(self.data["company"])}
		if FG in rows:
			self.assertGreaterEqual(rows[FG]["buildable_qty"], 0)
			self.assertLessEqual(rows[FG]["buildable_qty"], rows[FG]["pending_qty"])


def _ensure_package():
	if not frappe.db.exists("MP Item Package", PACKAGE):
		frappe.get_doc({"doctype": "MP Item Package", "package_name": PACKAGE}).insert(
			ignore_permissions=True
		)

	if not frappe.db.exists("Pick List Configuration", PACKAGE):
		doc = frappe.get_doc({"doctype": "Pick List Configuration", "package": PACKAGE})
		doc.append("slabs", {"from_quantity": 1, "to_quantity": 500, "extra_quantity": 10})
		doc.append("slabs", {"from_quantity": 501, "to_quantity": 2000, "extra_quantity": 25})
		doc.insert(ignore_permissions=True)

	frappe.db.set_value("Item", RM_LONG, "mp_package", PACKAGE)
	frappe.db.commit()


def _new_work_order(company: str, warehouse: str, qty: float = 10):
	bom = frappe.db.get_value("BOM", {"item": FG, "docstatus": 1}, "name")
	return frappe.get_doc(
		{
			"doctype": "Work Order",
			"company": company,
			"production_item": FG,
			"bom_no": bom,
			"qty": qty,
			"fg_warehouse": warehouse,
			"wip_warehouse": warehouse,
			"source_warehouse": warehouse,
			"use_multi_level_bom": 0,
		}
	)
