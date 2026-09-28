# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""What still has to be bought, per raw material.

Built from this app's own demand rows, so each Sales Order line is counted once. The core
MRP report cannot do that here: with one MPS per Sales Order it adds every *other* open
order as "Ad-hoc", and those orders already have MPS documents of their own.
"""

import frappe
from frappe import _
from frappe.utils import flt

OPEN_STATUSES = ("Short", "Exception", "Partially Ordered")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	rows = get_rows(filters)

	if filters.get("group_by_item"):
		rows = summarise(rows)
		return item_columns(), rows

	return line_columns(), rows


def get_rows(filters) -> list[dict]:
	conditions = {}
	for field in ("company", "sales_order", "item_code", "master_production_schedule"):
		if filters.get(field):
			conditions[field] = filters.get(field)

	if filters.get("status"):
		conditions["status"] = filters.get("status")
	elif not filters.get("include_covered"):
		conditions["status"] = ["in", OPEN_STATUSES]
	else:
		conditions["status"] = ["!=", "Superseded"]

	if filters.get("from_date") and filters.get("to_date"):
		conditions["delivery_date"] = ["between", [filters.from_date, filters.to_date]]

	return frappe.get_all(
		"Sales Order Material Demand",
		filters=conditions,
		fields=[
			"item_code",
			"required_qty",
			"available_qty",
			"short_qty",
			"ordered_qty",
			"received_qty",
			"lead_time_days",
			"required_by_date",
			"delivery_date",
			"status",
			"sales_order",
			"sales_order_item",
			"fg_item_code",
			"material_request",
			"purchase_order",
			"master_production_schedule",
		],
		order_by="required_by_date asc, item_code asc",
	)


def summarise(rows: list[dict]) -> list[dict]:
	totals: dict[str, dict] = {}

	for row in rows:
		summary = totals.setdefault(
			row.item_code,
			{
				"item_code": row.item_code,
				"required_qty": 0.0,
				"available_qty": 0.0,
				"short_qty": 0.0,
				"ordered_qty": 0.0,
				"received_qty": 0.0,
				"lead_time_days": 0,
				"required_by_date": row.required_by_date,
				"sales_orders": set(),
				"open_rows": 0,
			},
		)
		for field in ("required_qty", "short_qty", "ordered_qty", "received_qty"):
			summary[field] += flt(row.get(field))

		# stock is the same pool for every line, so take it once, not summed
		summary["available_qty"] = max(summary["available_qty"], flt(row.available_qty))
		summary["lead_time_days"] = max(summary["lead_time_days"], row.lead_time_days or 0)
		if row.required_by_date and (
			not summary["required_by_date"] or row.required_by_date < summary["required_by_date"]
		):
			summary["required_by_date"] = row.required_by_date
		summary["sales_orders"].add(row.sales_order)
		if row.status in OPEN_STATUSES:
			summary["open_rows"] += 1

	output = []
	for summary in totals.values():
		summary["sales_order_count"] = len(summary.pop("sales_orders"))
		summary["to_buy_qty"] = max(flt(summary["short_qty"]) - flt(summary["ordered_qty"]), 0.0)
		output.append(summary)

	return sorted(output, key=lambda r: (r["required_by_date"] or "", r["item_code"]))


def item_columns():
	return [
		{
			"label": _("Raw Material"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 160,
		},
		{"label": _("Required"), "fieldname": "required_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Available"), "fieldname": "available_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Short"), "fieldname": "short_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Ordered"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Still To Buy"), "fieldname": "to_buy_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Received"), "fieldname": "received_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Lead Days"), "fieldname": "lead_time_days", "fieldtype": "Int", "width": 90},
		{"label": _("Order By"), "fieldname": "required_by_date", "fieldtype": "Date", "width": 100},
		{"label": _("Sales Orders"), "fieldname": "sales_order_count", "fieldtype": "Int", "width": 110},
		{"label": _("Open Lines"), "fieldname": "open_rows", "fieldtype": "Int", "width": 100},
	]


def line_columns():
	return [
		{
			"label": _("Raw Material"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 150,
		},
		{
			"label": _("FG Item"),
			"fieldname": "fg_item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 130,
		},
		{
			"label": _("Sales Order"),
			"fieldname": "sales_order",
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 150,
		},
		{
			"label": _("MPS"),
			"fieldname": "master_production_schedule",
			"fieldtype": "Link",
			"options": "Master Production Schedule",
			"width": 140,
		},
		{"label": _("Required"), "fieldname": "required_qty", "fieldtype": "Float", "width": 95},
		{"label": _("Available"), "fieldname": "available_qty", "fieldtype": "Float", "width": 95},
		{"label": _("Short"), "fieldname": "short_qty", "fieldtype": "Float", "width": 95},
		{"label": _("Ordered"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 95},
		{"label": _("Lead Days"), "fieldname": "lead_time_days", "fieldtype": "Int", "width": 90},
		{"label": _("Order By"), "fieldname": "required_by_date", "fieldtype": "Date", "width": 100},
		{"label": _("Delivery Date"), "fieldname": "delivery_date", "fieldtype": "Date", "width": 110},
		{
			"label": _("Material Request"),
			"fieldname": "material_request",
			"fieldtype": "Link",
			"options": "Material Request",
			"width": 140,
		},
		{
			"label": _("Purchase Order"),
			"fieldname": "purchase_order",
			"fieldtype": "Link",
			"options": "Purchase Order",
			"width": 140,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
	]
