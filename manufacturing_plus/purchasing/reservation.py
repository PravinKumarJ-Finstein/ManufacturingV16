# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""MPS stock reservation: the hold the core MRP cannot give us."""

import frappe
from frappe.utils import add_days, cint, flt, now_datetime, nowdate

from manufacturing_plus.planning.settings import setting


def reserve_for_mps(mps_name: str, company: str, rows: list[dict], sales_order: str | None = None) -> int:
	"""rows = [{item_code, warehouse, qty, sales_order_item}] — qty actually taken from stock."""
	if not cint(setting("reserve_stock_on_mps", 1)):
		return 0

	expiry = add_days(nowdate(), cint(setting("reservation_expiry_days", 30)) or 30)
	created = 0

	for row in rows:
		qty = flt(row.get("qty"))
		if qty <= 0:
			continue

		# A re-run of the same Sales Order must not reserve the same stock twice.
		existing = frappe.db.get_value(
			"MPS Stock Reservation",
			{
				"master_production_schedule": mps_name,
				"item_code": row.get("item_code"),
				"sales_order_item": row.get("sales_order_item"),
				"status": "Active",
			},
			"name",
		)
		if existing:
			frappe.db.set_value("MPS Stock Reservation", existing, "reserved_qty", qty, update_modified=False)
			continue

		doc = frappe.get_doc(
			{
				"doctype": "MPS Stock Reservation",
				"master_production_schedule": mps_name,
				"company": company,
				"item_code": row.get("item_code"),
				"warehouse": row.get("warehouse"),
				"reserved_qty": qty,
				"sales_order": sales_order,
				"sales_order_item": row.get("sales_order_item"),
				"expiry_date": expiry,
				"status": "Active",
			}
		)
		doc.insert(ignore_permissions=True)
		created += 1

	return created


def release(filters: dict, reason: str) -> int:
	"""Release every active reservation matching the filters."""
	filters = dict(filters or {})
	filters["status"] = "Active"
	names = frappe.get_all("MPS Stock Reservation", filters=filters, pluck="name")

	for name in names:
		frappe.db.set_value(
			"MPS Stock Reservation",
			name,
			{"status": "Released", "released_on": now_datetime(), "release_reason": reason},
			update_modified=False,
		)

	return len(names)


def release_for_sales_order(sales_order: str, reason: str = "Sales Order cancelled") -> int:
	return release({"sales_order": sales_order}, reason)


def release_expired() -> int:
	"""Daily job: nothing may stay reserved for ever."""
	names = frappe.get_all(
		"MPS Stock Reservation",
		filters={"status": "Active", "expiry_date": ["<", nowdate()]},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value(
			"MPS Stock Reservation",
			name,
			{"status": "Expired", "released_on": now_datetime(), "release_reason": "Expired"},
			update_modified=False,
		)
	return len(names)


def release_for_work_order(doc, method=None):
	"""The Work Order now holds the material, so our own hold is no longer needed."""
	if not cint(setting("release_reservation_on_work_order", 1)):
		return

	if doc.get("sales_order"):
		release({"sales_order": doc.sales_order}, f"Work Order {doc.name} submitted")
