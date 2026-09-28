# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Purchase lead time per item, and the raw-material days for a BOM."""

import frappe
from frappe.utils import cint, flt

from manufacturing_plus.planning.settings import setting
from manufacturing_plus.planning.stock import get_free_qty

TOLERANCE = 1e-6


@frappe.request_cache
def get_item_lead_days(item_code: str, company: str | None = None) -> int:
	"""Item Lead Time (purchase + buffer) -> Item Default -> Item -> settings default."""
	row = frappe.db.get_value("Item Lead Time", item_code, ["purchase_time", "buffer_time"], as_dict=True)
	if row:
		days = cint(row.purchase_time) + cint(row.buffer_time)
		if days > 0:
			return days

	# Item Default carries a lead time in some custom setups, but not in stock v16 —
	# only read it when the column is really there.
	if company and frappe.db.has_column("Item Default", "lead_time_days"):
		days = frappe.db.get_value(
			"Item Default", {"parent": item_code, "company": company}, "lead_time_days"
		)
		if cint(days) > 0:
			return cint(days)

	days = frappe.db.get_value("Item", item_code, "lead_time_days")
	if cint(days) > 0:
		return cint(days)

	return cint(setting("fallback_lead_days", 0))


@frappe.request_cache
def get_exploded_items(bom_no: str) -> list[dict]:
	if not bom_no:
		return []

	return frappe.get_all(
		"BOM Explosion Item",
		filters={"parent": bom_no, "is_sub_assembly_item": 0},
		fields=["item_code", "qty_consumed_per_unit", "stock_uom"],
	)


def get_components(bom_no: str, stock_qty: float) -> list[dict]:
	return [
		{
			"item_code": row.item_code,
			"required_qty": flt(row.qty_consumed_per_unit) * flt(stock_qty),
			"stock_uom": row.stock_uom,
		}
		for row in get_exploded_items(bom_no)
		if flt(row.qty_consumed_per_unit) > 0
	]


def get_rm_shortage(
	bom_no: str,
	stock_qty: float,
	company: str | None = None,
	warehouse: str | None = None,
	delivery_date=None,
	exclude_sales_order: str | None = None,
) -> dict:
	"""-> {components, short, lead_days, driver_item}. Only short components drive the lead time."""
	components = get_components(bom_no, stock_qty)
	if not components:
		return {"components": [], "short": [], "lead_days": 0, "driver_item": None}

	items = [c["item_code"] for c in components]
	free = get_free_qty(items, company, warehouse, delivery_date, exclude_sales_order)

	short, lead_days, driver = [], 0, None
	for component in components:
		# Free stock can come back negative when earlier orders have already over-committed
		# it. That deficit belongs to those orders, and their own demand rows carry it, so
		# it is clamped here: this order is only ever short of what it needs itself.
		available = max(flt(free.get(component["item_code"], 0)), 0.0)
		component["available_qty"] = available
		component["short_qty"] = max(flt(component["required_qty"]) - available, 0.0)

		if component["short_qty"] > TOLERANCE:
			component["lead_time_days"] = get_item_lead_days(component["item_code"], company)
			short.append(component)
			if component["lead_time_days"] > lead_days:
				lead_days = component["lead_time_days"]
				driver = component["item_code"]

	return {"components": components, "short": short, "lead_days": lead_days, "driver_item": driver}
