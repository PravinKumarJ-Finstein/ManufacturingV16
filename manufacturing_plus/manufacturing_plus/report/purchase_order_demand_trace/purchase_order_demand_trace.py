# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Which Sales Order lines a Purchase Order line serves."""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"label": _("Purchase Order"),
			"fieldname": "purchase_order",
			"fieldtype": "Link",
			"options": "Purchase Order",
			"width": 150,
		},
		{"label": _("Status"), "fieldname": "po_status", "fieldtype": "Data", "width": 90},
		{
			"label": _("Supplier"),
			"fieldname": "supplier",
			"fieldtype": "Link",
			"options": "Supplier",
			"width": 150,
		},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 130},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{"label": _("Rate"), "fieldname": "rate", "fieldtype": "Currency", "width": 90},
		{"label": _("Schedule Date"), "fieldname": "schedule_date", "fieldtype": "Date", "width": 110},
		{
			"label": _("Material Request"),
			"fieldname": "material_request",
			"fieldtype": "Link",
			"options": "Material Request",
			"width": 150,
		},
		{
			"label": _("Demand Sales Order"),
			"fieldname": "mp_so_reference",
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
	]


def get_data(filters):
	values = {}
	conditions = ["ifnull(poi.mp_demand_key, '') != ''"]

	if filters.get("purchase_order"):
		conditions.append("po.name = %(purchase_order)s")
		values["purchase_order"] = filters.purchase_order
	if filters.get("supplier"):
		conditions.append("po.supplier = %(supplier)s")
		values["supplier"] = filters.supplier
	if filters.get("company"):
		conditions.append("po.company = %(company)s")
		values["company"] = filters.company
	if filters.get("sales_order"):
		conditions.append("poi.mp_so_reference = %(sales_order)s")
		values["sales_order"] = filters.sales_order

	rows = frappe.db.sql(
		f"""
		select po.name as purchase_order, po.supplier, po.docstatus,
		       poi.item_code, poi.qty, poi.rate, poi.schedule_date, poi.material_request,
		       poi.mp_so_reference, poi.mp_demand_key
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where {" and ".join(conditions)}
		order by po.name asc, poi.idx asc
		""",
		values,
		as_dict=True,
	)

	status_label = {0: "Draft", 1: "Submitted", 2: "Cancelled"}
	for row in rows:
		row["po_status"] = status_label.get(row.docstatus, "")
		row["fg_item_code"] = frappe.db.get_value(
			"Sales Order Material Demand", {"demand_key": row.mp_demand_key}, "fg_item_code"
		)

	return rows
