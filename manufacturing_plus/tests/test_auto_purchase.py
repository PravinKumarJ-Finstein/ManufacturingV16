# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""The Sales Order submit flow: MPS, reservation, Material Request, Purchase Order."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from manufacturing_plus.planning.stock import get_free_qty
from manufacturing_plus.purchasing.orchestrator import run_for_sales_order
from manufacturing_plus.tests.fixtures import FG, RM_LONG, RM_SHORT, seed

SUPPLIER = "_MP Test Supplier"


class TestAutoPurchase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()
		cls.company = cls.data["company"]
		_ensure_supplier_and_price(cls.company, cls.data["warehouse"])
		frappe.db.set_single_value("Manufacturing Control Setting", "run_mode", "Synchronous")
		# these tests check one plan per order, so pin the mode
		frappe.db.set_single_value("Manufacturing Control Setting", "mps_mode", "Per Sales Order")
		frappe.clear_cache()

	def test_sales_order_submit_creates_mps_mr_and_po(self):
		so = _make_sales_order(self.company, self.data["warehouse"], qty=6000)
		self.assertTrue(so.items[0].mp_expected_delivery_date, "expected delivery date was not filled")

		so.submit()
		run_name = frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "name")
		self.assertTrue(run_name)
		run = frappe.get_doc("Auto Purchase Run", run_name)

		self.assertIn(run.status, ("Completed", "Partially Completed"))
		self.assertTrue(run.master_production_schedule, "no MPS was created")
		self.assertEqual(
			frappe.db.get_value("Master Production Schedule", run.master_production_schedule, "docstatus"),
			0,
			"the MPS must stay a draft on v16.34.2",
		)

		demand = frappe.get_all(
			"Sales Order Material Demand",
			filters={"sales_order": so.name},
			fields=["item_code", "short_qty", "status", "material_request", "purchase_order"],
		)
		self.assertEqual(len(demand), 2)

		short = next(d for d in demand if d.item_code == RM_LONG)
		self.assertGreater(flt(short.short_qty), 0)
		self.assertTrue(short.material_request, "no Material Request for the short item")
		self.assertTrue(short.purchase_order, "no Purchase Order for the short item")

		in_stock = next(d for d in demand if d.item_code == RM_SHORT)
		self.assertEqual(in_stock.status, "In Stock")
		self.assertFalse(in_stock.material_request, "nothing should be bought for an item in stock")

		po = frappe.get_doc("Purchase Order", short.purchase_order)
		self.assertEqual(po.docstatus, 0, "the PO should be a draft by default")
		self.assertTrue(po.mp_auto_purchased)
		# the core drop-ship link must stay empty, or the Delivery Note qty would shrink
		self.assertFalse(any(row.sales_order for row in po.items))
		self.assertEqual(flt(frappe.db.get_value("Sales Order Item", so.items[0].name, "ordered_qty")), 0.0)

	def test_running_twice_does_not_buy_twice(self):
		so = _make_sales_order(self.company, self.data["warehouse"], qty=400)
		so.submit()

		before_mr = frappe.db.count("Material Request", {"mp_auto_purchase_run": ["is", "set"]})
		before_po = frappe.db.count("Purchase Order", {"mp_auto_purchased": 1})
		run_for_sales_order(so.name, trigger="Manual")

		self.assertEqual(
			before_mr, frappe.db.count("Material Request", {"mp_auto_purchase_run": ["is", "set"]})
		)
		self.assertEqual(before_po, frappe.db.count("Purchase Order", {"mp_auto_purchased": 1}))
		self.assertEqual(frappe.db.count("Master Production Schedule", {"mp_sales_order": so.name}), 1)

	def test_mps_reserves_stock_so_the_next_order_sees_it_short(self):
		free_before = get_free_qty([RM_SHORT], self.company)[RM_SHORT]
		so = _make_sales_order(self.company, self.data["warehouse"], qty=100)
		so.submit()

		free_after = get_free_qty([RM_SHORT], self.company)[RM_SHORT]
		self.assertAlmostEqual(free_after, free_before - 100, places=3)

		so.cancel()
		self.assertAlmostEqual(get_free_qty([RM_SHORT], self.company)[RM_SHORT], free_before, places=3)
		self.assertEqual(
			frappe.db.count("MPS Stock Reservation", {"sales_order": so.name, "status": "Active"}), 0
		)


def _make_sales_order(company: str, warehouse: str, qty: float):
	customer = frappe.db.get_value("Customer", {}, "name")
	so = frappe.new_doc("Sales Order")
	so.company = company
	so.customer = customer
	so.transaction_date = "2026-09-24"
	so.append("items", {"item_code": FG, "qty": qty, "rate": 2050, "warehouse": warehouse})
	so.insert(ignore_permissions=True)
	return so


def _ensure_supplier_and_price(company: str, warehouse: str) -> None:
	if not frappe.db.exists("Supplier", SUPPLIER):
		frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": SUPPLIER,
				"supplier_group": frappe.db.get_value("Supplier Group", {}, "name"),
			}
		).insert(ignore_permissions=True)

	for code, rate in ((RM_SHORT, 800), (RM_LONG, 57)):
		if not frappe.db.exists("Item Price", {"item_code": code, "buying": 1}):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": code,
					"price_list": "Standard Buying",
					"buying": 1,
					"price_list_rate": rate,
					"supplier": SUPPLIER,
				}
			).insert(ignore_permissions=True)

		item = frappe.get_doc("Item", code)
		if not item.item_defaults:
			item.append(
				"item_defaults",
				{"company": company, "default_supplier": SUPPLIER, "default_warehouse": warehouse},
			)
			item.save(ignore_permissions=True)


class TestAutoPurchaseRunConnections(FrappeTestCase):
	"""The run must show what it produced: MPS, demand rows, MRs, POs and exceptions."""

	def test_dashboard_links_every_document_the_run_creates(self):
		from frappe.desk.notifications import get_open_count

		from manufacturing_plus.manufacturing_plus.doctype.auto_purchase_run.auto_purchase_run_dashboard import (
			get_data,
		)

		data = get_data()
		linked = [item for group in data["transactions"] for item in group["items"]]
		for doctype in (
			"Master Production Schedule",
			"Sales Order Material Demand",
			"Material Request",
			"Purchase Order",
			"Auto Purchase Exception",
		):
			self.assertIn(doctype, linked)

		run = frappe.db.get_value("Auto Purchase Run", {}, "name", order_by="creation desc")
		if not run:
			return

		counts = get_open_count("Auto Purchase Run", run)["count"]["external_links_found"]
		self.assertEqual(
			{c["doctype"] for c in counts},
			set(linked),
			"a linked doctype is missing from the Connections section",
		)


class TestMPSConnections(FrappeTestCase):
	"""The MPS must show the auto-purchase documents it produced."""

	def test_mps_dashboard_links_the_run_and_its_documents(self):
		from manufacturing_plus.purchasing.dashboards import master_production_schedule

		data = master_production_schedule()
		linked = [item for group in data["transactions"] for item in group["items"]]

		# the MPS screen shows the run and nothing else
		self.assertEqual(linked, ["Auto Purchase Run"])

	def test_it_keeps_whatever_core_already_showed(self):
		from manufacturing_plus.purchasing.dashboards import master_production_schedule

		core = {
			"fieldname": "master_production_schedule",
			"transactions": [{"label": "Core", "items": ["Work Order"]}],
			"non_standard_fieldnames": {"Work Order": "mps"},
		}
		data = master_production_schedule(data=core)

		labels = [group["label"] for group in data["transactions"]]
		self.assertIn("Core", labels, "the core group was dropped")
		self.assertEqual(data["non_standard_fieldnames"]["Work Order"], "mps")


class TestRerun(FrappeTestCase):
	"""A partly finished run must be repeatable without ordering anything twice."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()
		_ensure_supplier_and_price(cls.data["company"], cls.data["warehouse"])
		frappe.db.set_single_value("Manufacturing Control Setting", "run_mode", "Synchronous")

	def test_rerun_orders_only_what_is_still_outstanding(self):
		from manufacturing_plus.purchasing.orchestrator import rerun

		so = _make_sales_order(self.company_or_default(), self.data["warehouse"], qty=2500)
		so.submit()

		first = frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "name")
		mr_before = frappe.db.count("Material Request", {"mp_auto_purchase_run": ["is", "set"]})
		po_before = frappe.db.count("Purchase Order", {"mp_auto_purchased": 1})

		second = rerun(first)
		self.assertEqual(first, second, "a re-run must update the same run, not open a new one")
		self.assertEqual(frappe.db.get_value("Auto Purchase Run", first, "attempts"), 2)

		self.assertEqual(
			mr_before, frappe.db.count("Material Request", {"mp_auto_purchase_run": ["is", "set"]})
		)
		self.assertEqual(po_before, frappe.db.count("Purchase Order", {"mp_auto_purchased": 1}))
		# works in either MPS mode: the run keeps pointing at the same plan
		self.assertTrue(frappe.db.get_value("Auto Purchase Run", first, "master_production_schedule"))

	def test_rerun_does_not_multiply_run_documents(self):
		from manufacturing_plus.purchasing.orchestrator import rerun, run_for_sales_order

		so = _make_sales_order(self.company_or_default(), self.data["warehouse"], qty=300)
		so.submit()

		before = frappe.db.count("Auto Purchase Run")
		first = frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "name")
		rerun(first)
		run_for_sales_order(so.name, trigger="Manual")  # even the entry point reuses it

		self.assertEqual(before, frappe.db.count("Auto Purchase Run"))
		self.assertEqual(frappe.db.count("Auto Purchase Run", {"sales_order": so.name}), 1)

	def test_rerun_needs_a_submitted_sales_order(self):
		from manufacturing_plus.purchasing.orchestrator import rerun

		run = frappe.get_doc(
			{"doctype": "Auto Purchase Run", "company": self.company_or_default(), "status": "Failed"}
		).insert(ignore_permissions=True)
		self.assertRaises(frappe.ValidationError, rerun, run.name)

	def company_or_default(self):
		return self.data["company"]


class TestMPSMode(FrappeTestCase):
	"""Per Period keeps the core MRP report honest: one plan, every open order in it."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()
		_ensure_supplier_and_price(cls.data["company"], cls.data["warehouse"])
		frappe.db.set_single_value("Manufacturing Control Setting", "run_mode", "Synchronous")

	def tearDown(self):
		frappe.db.set_single_value("Manufacturing Control Setting", "mps_mode", "Per Period")
		frappe.db.set_single_value("Manufacturing Control Setting", "plan_includes_open_orders", 0)
		frappe.clear_cache()

	def _set_mode(self, mode, period="Monthly"):
		frappe.db.set_single_value("Manufacturing Control Setting", "mps_mode", mode)
		frappe.db.set_single_value("Manufacturing Control Setting", "mps_period", period)
		frappe.clear_cache()

	def test_period_mode_reuses_one_plan_for_the_period(self):
		self._set_mode("Per Period")

		first = _make_sales_order(self.data["company"], self.data["warehouse"], qty=60)
		first.submit()
		second = _make_sales_order(self.data["company"], self.data["warehouse"], qty=80)
		second.submit()

		mps_one = frappe.db.get_value(
			"Auto Purchase Run", {"sales_order": first.name}, "master_production_schedule"
		)
		mps_two = frappe.db.get_value(
			"Auto Purchase Run", {"sales_order": second.name}, "master_production_schedule"
		)
		self.assertEqual(mps_one, mps_two, "both orders should land in the same period plan")

		plan = frappe.get_doc("Master Production Schedule", mps_one)
		listed = {row.sales_order for row in plan.sales_orders}
		self.assertIn(first.name, listed)
		self.assertIn(second.name, listed)

	def test_the_plan_only_gains_the_order_being_submitted(self):
		self._set_mode("Per Period")
		frappe.db.set_single_value("Manufacturing Control Setting", "plan_includes_open_orders", 0)
		frappe.clear_cache()

		before = _make_sales_order(self.data["company"], self.data["warehouse"], qty=40)
		before.submit()
		plan_name = frappe.db.get_value(
			"Auto Purchase Run", {"sales_order": before.name}, "master_production_schedule"
		)
		listed_before = {
			row.sales_order for row in frappe.get_doc("Master Production Schedule", plan_name).sales_orders
		}

		after = _make_sales_order(self.data["company"], self.data["warehouse"], qty=45)
		after.submit()
		listed_after = {
			row.sales_order for row in frappe.get_doc("Master Production Schedule", plan_name).sales_orders
		}

		# exactly one order joined the plan: the one just submitted
		self.assertEqual(listed_after - listed_before, {after.name})

	def test_sweep_adds_every_open_order_when_asked(self):
		self._set_mode("Per Period")
		frappe.db.set_single_value("Manufacturing Control Setting", "plan_includes_open_orders", 1)
		frappe.clear_cache()

		so = _make_sales_order(self.data["company"], self.data["warehouse"], qty=70)
		so.submit()
		plan = frappe.get_doc(
			"Master Production Schedule",
			frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "master_production_schedule"),
		)

		listed = {row.sales_order for row in plan.sales_orders}
		open_orders = frappe.get_all(
			"Sales Order",
			filters={
				"docstatus": 1,
				"company": self.data["company"],
				"status": ["not in", ("Closed", "Completed", "Stopped")],
			},
			pluck="name",
		)
		self.assertEqual(set(open_orders) - listed, set(), "an open order is missing from the plan")

	def tearDownClass_noop(self):
		pass

	def test_the_plan_gets_the_top_warehouse_and_its_items_selected(self):
		self._set_mode("Per Period")

		so = _make_sales_order(self.data["company"], self.data["warehouse"], qty=55)
		so.submit()
		plan = frappe.get_doc(
			"Master Production Schedule",
			frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "master_production_schedule"),
		)

		root = frappe.db.get_value(
			"Warehouse",
			{"company": self.data["company"], "is_group": 1, "parent_warehouse": ["in", ("", None)]},
			"name",
		)
		self.assertEqual(plan.parent_warehouse, root)

		planned = {row.item_code for row in plan.items}
		chosen = {row.item_code for row in plan.select_items}
		self.assertTrue(planned)
		self.assertEqual(planned - chosen, set(), "every planned item should be in Select Items")

	def test_per_sales_order_mode_still_makes_one_plan_per_order(self):
		self._set_mode("Per Sales Order")

		so = _make_sales_order(self.data["company"], self.data["warehouse"], qty=90)
		so.submit()
		self.assertEqual(frappe.db.count("Master Production Schedule", {"mp_sales_order": so.name}), 1)
