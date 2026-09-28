# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Supplier, price, MOQ / packing qty and the order-by date."""

import math

import frappe
from frappe.utils import add_days, cint, flt, getdate, nowdate

from manufacturing_plus.planning.settings import setting


@frappe.request_cache
def get_supplier(item_code: str, company: str) -> str | None:
	supplier = frappe.db.get_value(
		"Item Default", {"parent": item_code, "company": company}, "default_supplier"
	)
	if supplier:
		return supplier

	return frappe.db.get_value("Item Supplier", {"parent": item_code}, "supplier")


@frappe.request_cache
def get_purchase_params(item_code: str, company: str) -> dict:
	item = (
		frappe.db.get_value(
			"Item",
			item_code,
			["min_order_qty", "purchase_uom", "stock_uom", "safety_stock", "last_purchase_rate"],
			as_dict=True,
		)
		or frappe._dict()
	)

	spq = 0.0
	if frappe.db.has_column("Item", "standard_packing_quantity"):
		spq = flt(frappe.db.get_value("Item", item_code, "standard_packing_quantity"))

	return {
		"min_order_qty": flt(item.get("min_order_qty")),
		"packing_qty": spq,
		"purchase_uom": item.get("purchase_uom") or item.get("stock_uom"),
		"stock_uom": item.get("stock_uom"),
		"last_purchase_rate": flt(item.get("last_purchase_rate")),
	}


def get_rate(item_code: str, supplier: str | None, company: str) -> float | None:
	"""Item Price for the supplier, then any buying price, then the configured fallback."""
	filters = {"item_code": item_code, "buying": 1}
	price = None

	if supplier:
		price = frappe.db.get_value("Item Price", dict(filters, supplier=supplier), "price_list_rate")
	if price is None:
		price = frappe.db.get_value("Item Price", filters, "price_list_rate")

	if price is not None:
		return flt(price)

	action = setting("price_missing_action", "Block")
	if action == "Last Purchase Rate":
		rate = get_purchase_params(item_code, company)["last_purchase_rate"]
		return rate or None
	if action == "Zero Rate":
		return 0.0

	return None


def round_qty(qty: float, params: dict) -> float:
	"""Round up to the packing qty, then up to the MOQ, then to the packing qty again."""
	qty = flt(qty)
	packing = flt(params.get("packing_qty"))
	moq = flt(params.get("min_order_qty"))

	if packing > 0:
		qty = math.ceil(qty / packing) * packing
	if moq > 0 and qty < moq:
		qty = moq
		if packing > 0:
			qty = math.ceil(qty / packing) * packing

	return flt(qty, 6)


@frappe.request_cache
def get_class_threshold(item_code: str) -> float:
	"""MOQ class threshold for this item's class, from the settings child table."""
	item_class = None
	for fieldname in ("custom_item_classification", "custom_abc_class", "mp_item_class"):
		if frappe.db.has_column("Item", fieldname):
			item_class = frappe.db.get_value("Item", item_code, fieldname)
			if item_class:
				break

	if not item_class:
		return 0.0

	try:
		rows = frappe.get_cached_doc("Manufacturing Control Setting").get("class_thresholds") or []
	except Exception:
		return 0.0

	for row in rows:
		if (row.item_class or "").strip().upper() == str(item_class).strip().upper():
			return flt(row.threshold)

	return 0.0


def required_by_date(delivery_date, lead_time_days: int) -> str:
	"""Order-by date: delivery date - lead time - planning buffer, never in the past."""
	buffer_days = cint(setting("planning_buffer_days", 0))
	date = add_days(getdate(delivery_date), -(cint(lead_time_days) + buffer_days))
	today = getdate(nowdate())
	return str(max(getdate(date), today))


def earliest_possible_receipt(lead_time_days: int) -> str:
	return str(add_days(getdate(nowdate()), cint(lead_time_days)))
