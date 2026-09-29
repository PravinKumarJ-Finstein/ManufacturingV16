# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Document hooks for the purchasing side."""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from manufacturing_plus.planning.settings import is_enabled, setting
from manufacturing_plus.purchasing import reservation


def enqueue_auto_purchase(doc, method=None):
	"""Sales Order on_submit. Never blocks the submit."""
	if not is_enabled("enable_auto_purchase"):
		return

	from manufacturing_plus.purchasing.orchestrator import run_for_sales_order

	warn_items_without_bom(doc)

	if setting("run_mode", "Background") == "Synchronous":
		run_for_sales_order(doc.name)
		return

	frappe.enqueue(
		"manufacturing_plus.purchasing.orchestrator.run_for_sales_order",
		queue="long",
		timeout=1800,
		enqueue_after_commit=True,
		job_id=f"mp_auto_purchase::{doc.name}",
		deduplicate=True,
		sales_order=doc.name,
	)


def release_on_sales_order_cancel(doc, method=None):
	"""Sales Order on_cancel: free the stock and mark the demand superseded."""
	reservation.release_for_sales_order(doc.name)

	for name in frappe.get_all(
		"Sales Order Material Demand",
		filters={"sales_order": doc.name, "status": ["not in", ("Received", "Superseded")]},
		pluck="name",
	):
		frappe.db.set_value(
			"Sales Order Material Demand", name, "status", "Superseded", update_modified=False
		)


def sync_dates_from_purchase_order(doc, method=None):
	"""Purchase Order submit / update: push the real date back to the Sales Order line."""
	touched = set()

	for row in doc.items:
		if not row.get("mp_demand_key"):
			continue

		demand = frappe.db.get_value(
			"Sales Order Material Demand",
			{"demand_key": row.mp_demand_key},
			["name", "sales_order", "sales_order_item"],
			as_dict=True,
		)
		if not demand:
			continue

		frappe.db.set_value(
			"Sales Order Material Demand",
			demand.name,
			{
				"purchase_order": doc.name,
				"purchase_order_item": row.name,
				"ordered_qty": flt(row.qty),
				"expected_receipt_date": row.schedule_date,
				"status": "Ordered",
			},
			update_modified=False,
		)
		touched.add((demand.sales_order, demand.sales_order_item))

	for sales_order, so_item in touched:
		update_so_line_risk(sales_order, so_item)


def update_so_line_risk(sales_order: str, sales_order_item: str) -> None:
	"""Material available date = latest expected receipt; flag the line when it slips."""
	rows = frappe.get_all(
		"Sales Order Material Demand",
		filters={"sales_order_item": sales_order_item, "status": ["!=", "Superseded"]},
		fields=["expected_receipt_date", "status"],
	)
	if not rows:
		return

	dates = [getdate(r.expected_receipt_date) for r in rows if r.expected_receipt_date]
	available = max(dates) if dates else None
	statuses = {r.status for r in rows}

	if statuses == {"In Stock"}:
		material_status = "In Stock"
	elif "Short" in statuses or "Exception" in statuses:
		material_status = "Short"
	elif "Received" in statuses and len(statuses) == 1:
		material_status = "Received"
	else:
		material_status = "Ordered"

	values = {"mp_material_status": material_status, "mp_material_available_date": available}

	promised = frappe.db.get_value("Sales Order Item", sales_order_item, "mp_expected_delivery_date")
	if available and promised and getdate(available) > getdate(promised):
		values["mp_delivery_risk"] = "At Risk"
		values["mp_delivery_gap_days"] = (getdate(available) - getdate(promised)).days
	elif available:
		values["mp_delivery_risk"] = "Confirmed"
		values["mp_delivery_gap_days"] = 0

	for field, value in values.items():
		frappe.db.set_value("Sales Order Item", sales_order_item, field, value, update_modified=False)

	if values.get("mp_delivery_risk") == "At Risk":
		frappe.get_doc("Sales Order", sales_order).add_comment(
			"Comment",
			f"Material for one line now arrives {available}, "
			f"{values['mp_delivery_gap_days']} day(s) after the promised date {promised}.",
		)


def release_on_purchase_order_cancel(doc, method=None):
	for row in doc.items:
		if row.get("mp_demand_key"):
			frappe.db.set_value(
				"Sales Order Material Demand",
				{"demand_key": row.mp_demand_key},
				{"status": "Short", "purchase_order": None, "purchase_order_item": None, "ordered_qty": 0},
				update_modified=False,
			)


def close_demand_on_receipt(doc, method=None):
	"""Purchase Receipt submit: close the demand rows the receipt covers."""
	for row in doc.items:
		if not row.get("purchase_order_item"):
			continue

		demand = frappe.db.get_value(
			"Sales Order Material Demand",
			{"purchase_order_item": row.purchase_order_item},
			["name", "sales_order", "sales_order_item", "ordered_qty", "received_qty"],
			as_dict=True,
		)
		if not demand:
			continue

		received = flt(demand.received_qty) + flt(row.qty)
		frappe.db.set_value(
			"Sales Order Material Demand",
			demand.name,
			{
				"received_qty": received,
				"status": "Received" if received >= flt(demand.ordered_qty) else "Partially Ordered",
			},
			update_modified=False,
		)
		update_so_line_risk(demand.sales_order, demand.sales_order_item)


def release_reservation_on_work_order(doc, method=None):
	reservation.release_for_work_order(doc, method)


def warn_items_without_bom(doc) -> None:
	"""Say so at submit time when a line cannot be planned or bought.

	An MPS explodes a BOM into raw material, so a line with no default BOM has nothing to
	plan and nothing to buy: no plan row, no demand row, no Material Request, no Purchase
	Order. The delivery date is still worked out for it, from the item's own lead time.
	"""
	from manufacturing_plus.planning.expected_delivery import get_default_bom

	without_bom = sorted({item.item_code for item in doc.items if not get_default_bom(item.item_code)})
	if not without_bom:
		return

	items = ", ".join(frappe.bold(code) for code in without_bom)
	everything = len(without_bom) == len({item.item_code for item in doc.items})

	if everything:
		message = _("No item on this order has a default BOM: {0}.").format(items) + "<br><br>"
		if is_enabled("create_mps_on_so_submit"):
			message += _("No Master Production Schedule and no automatic Purchase Order are created.")
		else:
			message += _("No automatic Purchase Order is created.")
	else:
		message = _("These items have no default BOM: {0}.").format(items) + "<br><br>"
		message += _(
			"They are left out of the Master Production Schedule and of the automatic purchase. "
			"The rest of the order is planned as usual."
		)

	message += "<br><br>" + _(
		"Set a default BOM on the item to have it planned and its raw material purchased."
	)

	frappe.msgprint(message, title=_("No BOM: nothing planned for this item"), indicator="orange")
