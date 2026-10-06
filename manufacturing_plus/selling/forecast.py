# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Forecast Sales Orders, and the firm orders that eat into them.

This is the Kaynes selling flow. A customer first gives a **forecast**: a Sales Order with
*Forecast* ticked, no purchase order number behind it, standing for demand they expect but
have not committed to. Later the real order arrives — the same customer, the same item, with
a PO number — and that firm order **consumes** the forecast instead of adding to it. Without
that step the same demand would be counted twice, once as a forecast and once for real.

How a firm order consumes a forecast
------------------------------------
On submit, each line looks for submitted forecast orders of the same **customer**,
**company** and **job-work** flag carrying the same item, oldest delivery date first. Their
qty is reduced by what this order confirms, and a row is written to the forecast order's
**Forecast Confirmation Details** saying who confirmed how much and when. The firm line keeps
the total it took in *Forecast Quantity*, and which forecast lines it came from in
*Forecast SO Details*.

A forecast order keeps a snapshot of its own lines in **Sales Order Backup** taken at submit,
so the original forecast can still be read after confirmations have reduced it.

Cancelling a firm order gives the quantity back: its confirmation rows are removed and the
forecast lines are raised again, so a cancelled confirmation does not leave the forecast
permanently short.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from manufacturing_plus.planning.settings import is_enabled


def is_forecast(doc) -> bool:
	return bool(doc.get("mp_is_forecast"))


def set_forecast_backup(doc, method=None):
	"""Sales Order before_submit: a forecast keeps a copy of what it promised."""
	if not is_enabled("enable_forecast_orders") or not is_forecast(doc):
		return

	if doc.get("mp_sales_order_backup"):
		return

	for item in doc.items:
		doc.append(
			"mp_sales_order_backup",
			{
				"item_code": item.item_code,
				"item_name": item.item_name,
				"qty": flt(item.qty),
				"uom": item.uom,
				"conversion_factor": flt(item.conversion_factor),
				"stock_uom": item.stock_uom,
				"rate": flt(item.rate),
				"amount": flt(item.amount),
				"delivery_date": item.delivery_date,
				"customer_required_date": item.get("mp_customer_required_date"),
				"warehouse": item.warehouse,
				"item_group": item.item_group,
				"sales_order_item": item.name,
			},
		)


def consume_forecast(doc, method=None):
	"""Sales Order on_submit: a firm order takes its quantity out of the forecast."""
	if not is_enabled("enable_forecast_orders") or is_forecast(doc):
		return

	confirmed_any = False

	for item in doc.items:
		taken, sources = 0.0, []
		outstanding = flt(item.qty)

		for line in forecast_lines(doc, item.item_code):
			if outstanding <= 0:
				break

			available = flt(line.qty)
			if available <= 0:
				continue

			used = min(available, outstanding)
			reduce_forecast_line(line, used, doc, item)
			outstanding -= used
			taken += used
			sources.append({"forecast_so": line.parent, "so_detail": line.name, "qty": used})
			confirmed_any = True

		if taken:
			frappe.db.set_value(
				"Sales Order Item",
				item.name,
				{"mp_forecast_quantity": taken, "mp_forecast_so_details": json.dumps(sources)},
				update_modified=False,
			)

	if confirmed_any:
		frappe.msgprint(_("Forecast confirmed for this order."), indicator="green", alert=True)


def forecast_lines(doc, item_code: str) -> list:
	"""Open forecast lines for the same customer and item, oldest delivery date first."""
	return frappe.db.sql(
		"""
		select soi.name, soi.parent, soi.qty, soi.rate, soi.delivery_date, soi.item_code
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		where soi.item_code = %(item_code)s
		  and so.docstatus = 1
		  and ifnull(so.mp_is_forecast, 0) = 1
		  and so.company = %(company)s
		  and so.customer = %(customer)s
		  and ifnull(so.mp_is_job_work, 0) = %(job_work)s
		  and soi.qty > 0
		order by soi.delivery_date asc, soi.creation asc
		""",
		{
			"item_code": item_code,
			"company": doc.company,
			"customer": doc.customer,
			"job_work": 1 if doc.get("mp_is_job_work") else 0,
		},
		as_dict=True,
	)


def reduce_forecast_line(line, used: float, firm_order, firm_item) -> None:
	"""Take `used` off the forecast line and record who took it.

	The forecast order is submitted, so the qty is written straight to the database: saving
	the document would put it through update-after-submit validation, which refuses a
	changed qty. The confirmation row is inserted the same way, against the parent that is
	already there.
	"""
	frappe.db.set_value("Sales Order Item", line.name, "qty", flt(line.qty) - used, update_modified=False)

	rate = flt(line.rate)
	frappe.get_doc(
		{
			"doctype": "MP Forecast Confirmation",
			"parent": line.parent,
			"parenttype": "Sales Order",
			"parentfield": "mp_forecast_confirmation_details",
			"sales_order": firm_order.name,
			"item_code": line.item_code,
			"quantity": used,
			"confirmed_on": firm_order.get("po_date") or firm_order.transaction_date or nowdate(),
			"delivery_date": firm_item.delivery_date,
			"rate": rate,
			"total_amount": rate * used,
			"forecast_so_item": line.name,
			"confirmed_so_item": firm_item.name,
		}
	).insert(ignore_permissions=True)

	refresh_forecast_totals(line.parent)


def release_forecast(doc, method=None):
	"""Sales Order on_cancel: a cancelled firm order gives the forecast its qty back."""
	if not is_enabled("enable_forecast_orders") or is_forecast(doc):
		return

	rows = frappe.get_all(
		"MP Forecast Confirmation",
		filters={"sales_order": doc.name, "parenttype": "Sales Order"},
		fields=["name", "parent", "quantity", "forecast_so_item"],
	)
	if not rows:
		return

	touched = set()
	for row in rows:
		if row.forecast_so_item and frappe.db.exists("Sales Order Item", row.forecast_so_item):
			current = flt(frappe.db.get_value("Sales Order Item", row.forecast_so_item, "qty"))
			frappe.db.set_value(
				"Sales Order Item",
				row.forecast_so_item,
				"qty",
				current + flt(row.quantity),
				update_modified=False,
			)
			touched.add(row.parent)

		frappe.delete_doc("MP Forecast Confirmation", row.name, force=True, ignore_permissions=True)

	for parent in touched:
		refresh_forecast_totals(parent)

	frappe.msgprint(
		_("Forecast quantity returned to {0}.").format(frappe.bold(", ".join(sorted(touched)))),
		indicator="orange",
		alert=True,
	)


def refresh_forecast_totals(sales_order: str) -> None:
	"""Keep the forecast order's totals honest after its lines move."""
	doc = frappe.get_doc("Sales Order", sales_order)

	for item in doc.items:
		item.amount = flt(item.rate) * flt(item.qty)
		item.stock_qty = flt(item.qty) * flt(item.conversion_factor or 1)

	doc.calculate_taxes_and_totals()
	doc.set_total_in_words()

	frappe.db.set_value(
		"Sales Order",
		doc.name,
		{
			"total_qty": doc.total_qty,
			"total": doc.total,
			"net_total": doc.net_total,
			"grand_total": doc.grand_total,
			"rounded_total": doc.rounded_total,
			"in_words": doc.in_words,
		},
		update_modified=False,
	)

	for item in doc.items:
		frappe.db.set_value(
			"Sales Order Item",
			item.name,
			{"amount": item.amount, "stock_qty": item.stock_qty},
			update_modified=False,
		)


@frappe.whitelist()
def get_forecast_coverage(sales_order: str) -> dict:
	"""For a forecast order: how much of it customers have since confirmed."""
	frappe.has_permission("Sales Order", "read", throw=True)

	doc = frappe.get_doc("Sales Order", sales_order)
	backup = {row.sales_order_item: row for row in doc.get("mp_sales_order_backup") or []}

	rows = []
	for item in doc.items:
		original = flt(backup[item.name].qty) if item.name in backup else flt(item.qty)
		rows.append(
			{
				"item_code": item.item_code,
				"forecast_qty": original,
				"remaining_qty": flt(item.qty),
				"confirmed_qty": max(original - flt(item.qty), 0.0),
			}
		)

	return {"is_forecast": is_forecast(doc), "rows": rows}
