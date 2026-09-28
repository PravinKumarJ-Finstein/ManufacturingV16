# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Master data the tests rely on: two operations, two workstations, a BOM and stock."""

import frappe
from frappe.utils import nowdate

FG = "_MP Test Laptop"
RM_SHORT = "_MP Test Display"
RM_LONG = "_MP Test MBoard"
ASSEMBLY = "_MP Assembly"
TESTING = "_MP Testing"
WS_ASSEMBLY = "_MP WS Assembly"
WS_TESTING = "_MP WS Testing"


def seed() -> dict:
	company = frappe.db.get_value("Company", {}, "name")
	abbr = frappe.db.get_value("Company", company, "abbr")
	warehouse = f"Stores - {abbr}"
	item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")

	for code, name in ((FG, "Laptop"), (RM_SHORT, "Display"), (RM_LONG, "MBoard")):
		if not frappe.db.exists("Item", code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": name,
					"item_group": item_group,
					"stock_uom": "Nos",
					"is_stock_item": 1,
					"is_purchase_item": 0 if code == FG else 1,
					"include_item_in_manufacturing": 1,
				}
			).insert(ignore_permissions=True)

	for code, purchase_time, buffer_time in ((RM_SHORT, 10, 2), (RM_LONG, 25, 5)):
		if not frappe.db.exists("Item Lead Time", code):
			frappe.get_doc(
				{
					"doctype": "Item Lead Time",
					"item_code": code,
					"purchase_time": purchase_time,
					"buffer_time": buffer_time,
				}
			).insert(ignore_permissions=True)

	for operation in (ASSEMBLY, TESTING):
		if not frappe.db.exists("Operation", operation):
			frappe.get_doc({"doctype": "Operation", "__newname": operation}).insert(ignore_permissions=True)

	for workstation in (WS_ASSEMBLY, WS_TESTING):
		if frappe.db.exists("Workstation", workstation):
			doc = frappe.get_doc("Workstation", workstation)
		else:
			doc = frappe.get_doc({"doctype": "Workstation", "workstation_name": workstation, "hour_rate": 0})
			doc.append("working_hours", {"start_time": "09:00:00", "end_time": "17:00:00", "enabled": 1})
		doc.save(ignore_permissions=True)

	bom = frappe.db.get_value("BOM", {"item": FG, "docstatus": 1}, "name")
	if not bom:
		doc = frappe.get_doc(
			{
				"doctype": "BOM",
				"item": FG,
				"quantity": 1,
				"company": company,
				"with_operations": 1,
				"currency": frappe.db.get_value("Company", company, "default_currency"),
			}
		)
		doc.append("items", {"item_code": RM_SHORT, "qty": 1})
		doc.append("items", {"item_code": RM_LONG, "qty": 2})
		doc.append(
			"operations",
			{
				"operation": ASSEMBLY,
				"workstation": WS_ASSEMBLY,
				"time_in_mins": 60,
				"batch_size": 500,
				"hour_rate": 0,
			},
		)
		doc.append(
			"operations",
			{
				"operation": TESTING,
				"workstation": WS_TESTING,
				"time_in_mins": 60,
				"batch_size": 250,
				"hour_rate": 0,
			},
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		bom = doc.name

	frappe.db.set_value("Item", FG, "default_bom", bom)
	_set_operation_rates(bom)

	# Display: plenty. MBoard: short, so it drives the lead time.
	for code, qty in ((RM_SHORT, 8000), (RM_LONG, 2000)):
		current = frappe.db.get_value("Bin", {"item_code": code, "warehouse": warehouse}, "actual_qty")
		if not current:
			_make_opening_stock(company, warehouse, code, qty)

	frappe.db.commit()
	return {"company": company, "warehouse": warehouse, "bom": bom}


def _set_operation_rates(bom: str) -> None:
	"""Keep the rates the tests rely on, even on a BOM made by an earlier run.

	60 mins per batch of 500 = 500 an hour; 60 mins per batch of 250 = 250 an hour.
	"""
	rates = {ASSEMBLY: 500, TESTING: 250}
	for row in frappe.get_all("BOM Operation", filters={"parent": bom}, fields=["name", "operation"]):
		batch_size = rates.get(row.operation)
		if batch_size:
			frappe.db.set_value(
				"BOM Operation",
				row.name,
				{"time_in_mins": 60, "batch_size": batch_size, "fixed_time": 0},
				update_modified=False,
			)


def _make_opening_stock(company: str, warehouse: str, item_code: str, qty: float) -> None:
	account = frappe.db.get_value("Account", {"company": company, "account_type": "Temporary"}, "name")
	doc = frappe.get_doc(
		{
			"doctype": "Stock Reconciliation",
			"company": company,
			"purpose": "Opening Stock",
			"posting_date": nowdate(),
			"expense_account": account,
		}
	)
	doc.append("items", {"item_code": item_code, "warehouse": warehouse, "qty": qty, "valuation_rate": 100})
	doc.insert(ignore_permissions=True)
	doc.submit()
