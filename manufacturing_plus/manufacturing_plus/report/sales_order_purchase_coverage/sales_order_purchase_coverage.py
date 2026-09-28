# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Which Purchase Order covers which Sales Order line."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"label": _("Sales Order"),
			"fieldname": "sales_order",
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 150,
		},
		{
			"label": _("FG Item"),
			"fieldname": "fg_item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 130,
		},
		{"label": _("Delivery Date"), "fieldname": "delivery_date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Raw Material"),
			"fieldname": "item_code",
			"fieldtype": "Link",
			"options": "Item",
			"width": 130,
		},
		{"label": _("Required"), "fieldname": "required_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Available"), "fieldname": "available_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Short"), "fieldname": "short_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Ordered"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 90},
		{"label": _("Received"), "fieldname": "received_qty", "fieldtype": "Float", "width": 90},
		{
			"label": _("Material Request"),
			"fieldname": "material_request",
			"fieldtype": "Link",
			"options": "Material Request",
			"width": 150,
		},
		{
			"label": _("Purchase Order"),
			"fieldname": "purchase_order",
			"fieldtype": "Link",
			"options": "Purchase Order",
			"width": 150,
		},
		{"label": _("Required By"), "fieldname": "required_by_date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Expected Receipt"),
			"fieldname": "expected_receipt_date",
			"fieldtype": "Date",
			"width": 120,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
	]


def get_data(filters):
	conditions = {}
	for field in ("company", "sales_order", "item_code", "status"):
		if filters.get(field):
			conditions[field] = filters.get(field)

	if filters.get("from_date") and filters.get("to_date"):
		conditions["delivery_date"] = ["between", [filters.from_date, filters.to_date]]

	return frappe.get_all(
		"Sales Order Material Demand",
		filters=conditions,
		fields=[
			"sales_order",
			"fg_item_code",
			"delivery_date",
			"item_code",
			"required_qty",
			"available_qty",
			"short_qty",
			"ordered_qty",
			"received_qty",
			"material_request",
			"purchase_order",
			"required_by_date",
			"expected_receipt_date",
			"status",
		],
		order_by="sales_order asc, item_code asc",
	)
