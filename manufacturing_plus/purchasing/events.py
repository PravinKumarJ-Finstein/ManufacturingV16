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

	if doc.get("mp_is_forecast") and not is_enabled("plan_forecast_orders"):
		# a forecast is demand the customer has not committed to: nothing is bought for it
		frappe.msgprint(
			_("This is a forecast order, so no plan and no purchase are created.")
			+ "<br>"
			+ _("Switch on Plan And Buy For Forecast Orders to change that."),
			indicator="blue",
			alert=True,
		)
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


def refresh_after_update_items(doc, method=None):
	"""Sales Order on_update_after_submit: Update Items changed the order, so follow it.

	"Update Items" edits the lines of a submitted order in place. Everything downstream was
	built from the old quantities, so the plan is brought back in line and the auto purchase
	is run again on the same run — what is already ordered stays, only the difference is
	bought.
	"""
	if not is_enabled("enable_auto_purchase"):
		return

	if not is_enabled("refresh_plan_on_update_items"):
		return

	if doc.get("mp_is_forecast") and not is_enabled("plan_forecast_orders"):
		return

	from manufacturing_plus.purchasing.orchestrator import rerun, sync_mps_with_sales_order

	run = frappe.db.get_value("Auto Purchase Run", {"sales_order": doc.name}, "name")
	if not run:
		# the order was never run through auto purchase, so there is nothing to follow
		return

	mps = sync_mps_with_sales_order(doc)
	if mps:
		frappe.msgprint(
			_("Plan {0} updated with the new quantities.").format(frappe.bold(mps)),
			indicator="green",
			alert=True,
		)

	if setting("run_mode", "Background") == "Synchronous":
		rerun(run)
		return

	frappe.enqueue(
		"manufacturing_plus.purchasing.orchestrator.rerun",
		queue="long",
		timeout=1800,
		enqueue_after_commit=True,
		job_id=f"mp_auto_purchase_rerun::{doc.name}",
		deduplicate=True,
		run_name=run,
	)
	frappe.msgprint(
		_("Auto purchase is running again for {0}. Anything already ordered is left alone.").format(
			frappe.bold(doc.name)
		),
		indicator="blue",
		alert=True,
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
			["name", "sales_order", "sales_order_item", "short_qty"],
			as_dict=True,
		)
		if not demand:
			continue

		# an order that grew is bought in instalments, so count every live line, not just this one
		ordered = ordered_qty_for_demand(row.mp_demand_key)

		frappe.db.set_value(
			"Sales Order Material Demand",
			demand.name,
			{
				"purchase_order": doc.name,
				"purchase_order_item": row.name,
				"ordered_qty": ordered,
				"expected_receipt_date": row.schedule_date,
				"status": "Ordered" if ordered >= flt(demand.short_qty) else "Partially Ordered",
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


def ordered_qty_for_demand(demand_key: str) -> float:
	"""Everything still on order for this demand row, over however many Purchase Orders.

	Drafts count: this flow leaves Purchase Orders as drafts unless auto-submit is on, and a
	draft is still an order someone has raised. Only a cancelled one gives its qty back.
	"""
	rows = frappe.db.sql(
		"""
		select sum(poi.qty) as qty
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where poi.mp_demand_key = %(key)s and po.docstatus < 2
		""",
		{"key": demand_key},
	)
	return flt(rows[0][0]) if rows else 0.0


def release_on_purchase_order_cancel(doc, method=None):
	"""A cancelled Purchase Order gives its qty back: what is left on order is recounted."""
	for row in doc.items:
		if not row.get("mp_demand_key"):
			continue

		demand = frappe.db.get_value(
			"Sales Order Material Demand",
			{"demand_key": row.mp_demand_key},
			["name", "short_qty"],
			as_dict=True,
		)
		if not demand:
			continue

		ordered = ordered_qty_for_demand(row.mp_demand_key)
		values = {"ordered_qty": ordered}
		if ordered <= 0:
			values.update({"status": "Short", "purchase_order": None, "purchase_order_item": None})
		else:
			values["status"] = "Ordered" if ordered >= flt(demand.short_qty) else "Partially Ordered"

		frappe.db.set_value("Sales Order Material Demand", demand.name, values, update_modified=False)


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
