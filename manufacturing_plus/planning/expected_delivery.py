# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Expected Delivery Date = order date + RM lead days + queue days + production days + buffer."""

import json
import math

import frappe
from frappe.utils import add_days, cint, flt, getdate, nowdate

from manufacturing_plus.planning.calendar_utils import roll_forward
from manufacturing_plus.planning.capacity import get_production_days
from manufacturing_plus.planning.lead_time import get_item_lead_days, get_rm_shortage
from manufacturing_plus.planning.queue import get_queue_days
from manufacturing_plus.planning.settings import is_enabled, setting


@frappe.request_cache
def get_default_bom(item_code: str) -> str | None:
	bom = frappe.db.get_value("Item", item_code, "default_bom")
	if bom:
		return bom

	bom = frappe.db.get_value(
		"BOM", {"item": item_code, "is_active": 1, "is_default": 1, "docstatus": 1}, "name"
	)
	if bom:
		return bom

	template = frappe.db.get_value("Item", item_code, "variant_of")
	return frappe.db.get_value("Item", template, "default_bom") if template else None


def get_stock_qty(item_code: str, qty: float, uom: str | None, conversion_factor: float | None) -> float:
	if conversion_factor:
		return flt(qty) * flt(conversion_factor)

	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	if uom and stock_uom and uom != stock_uom:
		factor = frappe.db.get_value(
			"UOM Conversion Detail", {"parent": item_code, "uom": uom}, "conversion_factor"
		)
		return flt(qty) * (flt(factor) or 1.0)

	return flt(qty)


@frappe.whitelist()
def get_expected_delivery_date(
	item_code,
	qty,
	transaction_date=None,
	warehouse=None,
	company=None,
	uom=None,
	conversion_factor=None,
	bom_no=None,
	sales_order=None,
):
	"""Promised date for one line. Never raises: a failure returns status 'Failed'."""
	frappe.has_permission("Sales Order", throw=False)
	result = {
		"item_code": item_code,
		"expected_delivery_date": None,
		"rm_lead_days": 0,
		"queue_days": 0.0,
		"production_days": 0.0,
		"buffer_days": 0,
		"total_days": 0,
		"bom_no": None,
		"capacity_source": "",
		"status": "Skipped",
		"breakdown": {},
	}

	if not is_enabled("enable_expected_delivery_date") or not item_code or flt(qty) <= 0:
		return result

	try:
		start = getdate(transaction_date or nowdate())
		if setting("compute_from") == "Today (whichever is later)":
			start = max(start, getdate(nowdate()))

		buffer_days = cint(setting("buffer_days", 0))
		stock_qty = get_stock_qty(item_code, qty, uom, flt(conversion_factor))
		bom_no = bom_no or get_default_bom(item_code)
		result["bom_no"] = bom_no
		result["buffer_days"] = buffer_days

		if not bom_no:
			is_stock_item = frappe.db.get_value("Item", item_code, "is_stock_item")
			result["rm_lead_days"] = get_item_lead_days(item_code, company) if is_stock_item else 0
			result["status"] = "Purchased Item" if is_stock_item else "Service Item"
			shortage = {"short": [], "driver_item": None, "components": []}
			production = {"days": 0.0, "operations": [], "status": result["status"], "source": ""}
			queue = {"days": 0.0, "workstations": [], "orders": 0}
		else:
			shortage = get_rm_shortage(bom_no, stock_qty, company, warehouse, None, sales_order)
			production = get_production_days(bom_no, stock_qty, item_code)
			queue = get_queue_days(bom_no, item_code, company, sales_order)

			result["rm_lead_days"] = cint(shortage["lead_days"])
			result["production_days"] = flt(production["days"], 3)
			result["queue_days"] = flt(queue["days"], 3)
			result["capacity_source"] = production["source"]
			result["status"] = production["status"]

		total = (
			flt(result["rm_lead_days"])
			+ flt(result["queue_days"])
			+ flt(result["production_days"])
			+ buffer_days
		)
		total_days = math.ceil(total) if cint(setting("round_up_partial_days", 1)) else int(total)
		result["total_days"] = total_days
		result["expected_delivery_date"] = roll_forward(add_days(start, total_days), company)

		result["breakdown"] = {
			"start": str(start),
			"rm": {
				"days": result["rm_lead_days"],
				"driver_item": shortage.get("driver_item"),
				"short_items": len(shortage.get("short") or []),
			},
			"queue": queue,
			"operations": production.get("operations"),
			"buffer": buffer_days,
			"total": total_days,
			"expected": str(result["expected_delivery_date"]),
		}
	except Exception:
		frappe.log_error(
			title="Expected Delivery Date failed",
			message=f"item={item_code} qty={qty}\n{frappe.get_traceback()}",
		)
		result["status"] = "Failed"

	return result


@frappe.whitelist()
def get_expected_delivery_dates_bulk(items, transaction_date=None, company=None, sales_order=None):
	"""items = JSON list of {idx, item_code, qty, uom, conversion_factor, warehouse}."""
	if isinstance(items, str):
		items = json.loads(items)

	cache: dict = {}
	output = []
	for row in items:
		key = (row.get("item_code"), row.get("warehouse"), flt(row.get("qty")), row.get("uom"))
		if key not in cache:
			cache[key] = get_expected_delivery_date(
				item_code=row.get("item_code"),
				qty=row.get("qty"),
				transaction_date=transaction_date,
				warehouse=row.get("warehouse"),
				company=company,
				uom=row.get("uom"),
				conversion_factor=row.get("conversion_factor"),
				sales_order=sales_order,
			)
		result = dict(cache[key])
		result["idx"] = row.get("idx")
		output.append(result)

	return output
