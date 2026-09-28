# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Yield per Work Order and operation, worst first."""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"label": _("Work Order"),
			"fieldname": "work_order",
			"fieldtype": "Link",
			"options": "Work Order",
			"width": 150,
		},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{
			"label": _("Operation"),
			"fieldname": "operation",
			"fieldtype": "Link",
			"options": "Operation",
			"width": 130,
		},
		{"label": _("Inspected"), "fieldname": "inspected_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Accepted"), "fieldname": "accepted_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Rejected"), "fieldname": "rejected_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Yield %"), "fieldname": "yield_percent", "fieldtype": "Percent", "width": 90},
		{"label": _("Defects"), "fieldname": "total_defects", "fieldtype": "Int", "width": 80},
	]


def get_data(filters):
	conditions = {"docstatus": 1}
	for field in ("company", "work_order", "operation", "item_code"):
		if filters.get(field):
			conditions[field] = filters.get(field)

	if filters.get("from_date") and filters.get("to_date"):
		conditions["entry_date"] = ["between", [filters.from_date, filters.to_date]]

	rows = frappe.get_all(
		"Yield Entry",
		filters=conditions,
		fields=[
			"work_order",
			"item_code",
			"operation",
			"inspected_qty",
			"accepted_qty",
			"rejected_qty",
			"yield_percent",
			"total_defects",
		],
	)
	return sorted(rows, key=lambda r: flt(r.yield_percent))
