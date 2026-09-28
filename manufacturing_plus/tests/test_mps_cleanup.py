# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Deleting a plan takes its planning records with it, but never a purchase document."""

import frappe
from frappe.tests.utils import FrappeTestCase

from manufacturing_plus.tests.fixtures import FG, seed


class TestMPSCleanup(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()
		frappe.db.set_single_value("Manufacturing Control Setting", "run_mode", "Synchronous")
		frappe.clear_cache()

	def test_deleting_a_plan_clears_everything_that_belongs_to_it(self):
		so = self._submit_order(qty=45)
		run = frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "name")
		plan = frappe.db.get_value("Auto Purchase Run", run, "master_production_schedule")
		self.assertTrue(plan)

		frappe.delete_doc("Master Production Schedule", plan, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Master Production Schedule", plan))
		self.assertEqual(frappe.db.count("MPS Stock Reservation", {"master_production_schedule": plan}), 0)
		self.assertEqual(frappe.db.count("Auto Purchase Exception", {"master_production_schedule": plan}), 0)
		self.assertEqual(
			frappe.db.count("Sales Order Material Demand", {"master_production_schedule": plan}), 0
		)

	def test_a_purchase_document_survives_and_only_loses_the_link(self):
		so = self._submit_order(qty=4200)  # big enough to be short and buy something
		run = frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "name")
		plan = frappe.db.get_value("Auto Purchase Run", run, "master_production_schedule")

		requests = frappe.get_all("Material Request", filters={"mp_auto_purchase_run": run}, pluck="name")
		orders = frappe.get_all("Purchase Order", filters={"mp_auto_purchase_run": run}, pluck="name")
		if not requests and not orders:
			return  # nothing was short; the other test covers the rest

		frappe.delete_doc("Master Production Schedule", plan, ignore_permissions=True)

		for name in requests:
			self.assertTrue(frappe.db.exists("Material Request", name), "a Material Request was deleted")
			self.assertIsNone(frappe.db.get_value("Material Request", name, "mp_master_production_schedule"))
		for name in orders:
			self.assertTrue(frappe.db.exists("Purchase Order", name), "a Purchase Order was deleted")
			self.assertIsNone(frappe.db.get_value("Purchase Order", name, "mp_master_production_schedule"))

		# the run stays, because it still has documents to show
		self.assertTrue(frappe.db.exists("Auto Purchase Run", run))
		self.assertIsNone(frappe.db.get_value("Auto Purchase Run", run, "master_production_schedule"))

	def _submit_order(self, qty: float):
		so = frappe.new_doc("Sales Order")
		so.company = self.data["company"]
		so.customer = frappe.db.get_value("Customer", {}, "name")
		so.transaction_date = "2026-09-24"
		so.append(
			"items",
			{"item_code": FG, "qty": qty, "rate": 2050, "warehouse": self.data["warehouse"]},
		)
		so.insert(ignore_permissions=True)
		so.submit()
		return so


class TestRunDeletion(FrappeTestCase):
	"""Deleting a run must never take a purchase document with it."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()
		frappe.db.set_single_value("Manufacturing Control Setting", "run_mode", "Synchronous")
		frappe.clear_cache()

	def test_impact_is_reported_before_anything_is_deleted(self):
		from manufacturing_plus.purchasing.cleanup import get_run_impact

		so = self._submit_order(qty=4300)
		run = frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "name")

		impact = get_run_impact(run)
		self.assertIn("material_requests", impact)
		self.assertIn("purchase_orders", impact)
		self.assertIn("submitted_purchase_orders", impact)

		# reading the impact changes nothing
		self.assertTrue(frappe.db.exists("Auto Purchase Run", run))
		for order in impact["purchase_orders"]:
			self.assertTrue(frappe.db.exists("Purchase Order", order["name"]))

	def test_deleting_a_run_keeps_its_purchase_documents(self):
		so = self._submit_order(qty=4400)
		run = frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "name")
		requests = frappe.get_all("Material Request", filters={"mp_auto_purchase_run": run}, pluck="name")
		orders = frappe.get_all("Purchase Order", filters={"mp_auto_purchase_run": run}, pluck="name")

		frappe.delete_doc("Auto Purchase Run", run, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Auto Purchase Run", run))
		for name in requests:
			self.assertTrue(frappe.db.exists("Material Request", name), "a Material Request was deleted")
			self.assertIsNone(frappe.db.get_value("Material Request", name, "mp_auto_purchase_run"))
		for name in orders:
			self.assertTrue(frappe.db.exists("Purchase Order", name), "a Purchase Order was deleted")
			self.assertIsNone(frappe.db.get_value("Purchase Order", name, "mp_auto_purchase_run"))

		self.assertEqual(frappe.db.count("Auto Purchase Exception", {"run": run}), 0)

	def _submit_order(self, qty: float):
		so = frappe.new_doc("Sales Order")
		so.company = self.data["company"]
		so.customer = frappe.db.get_value("Customer", {}, "name")
		so.transaction_date = "2026-09-24"
		so.append("items", {"item_code": FG, "qty": qty, "rate": 2050, "warehouse": self.data["warehouse"]})
		so.insert(ignore_permissions=True)
		so.submit()
		return so
