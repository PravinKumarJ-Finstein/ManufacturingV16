# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Split a received kit item into its child items through a value-neutral Repack."""

import frappe
from frappe import _
from frappe.utils import flt, nowdate, nowtime

from manufacturing_plus.planning.settings import is_enabled


@frappe.whitelist()
def has_combo_items(purchase_receipt: str) -> bool:
	items = frappe.get_all("Purchase Receipt Item", filters={"parent": purchase_receipt}, pluck="item_code")
	if not items:
		return False

	return bool(frappe.db.exists("Combo Parts", {"parent_item_code": ["in", items], "is_active": 1}))


@frappe.whitelist()
def split_combo_items(purchase_receipt: str) -> list[str]:
	"""One Repack Stock Entry per combo line: the kit goes out, its children come in."""
	if not is_enabled("enable_combo_split"):
		frappe.throw(_("Combo Parts Split is switched off in Manufacturing Control Setting."))

	pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
	if pr.docstatus != 1:
		frappe.throw(_("Split Combo is only allowed on a submitted Purchase Receipt."))

	created = []
	for row in pr.items:
		combo = frappe.db.get_value(
			"Combo Parts", {"parent_item_code": row.item_code, "is_active": 1}, "name"
		)
		if not combo:
			continue

		if _already_split(pr.name, row.item_code):
			frappe.throw(
				_("Combo item {0} on this Purchase Receipt has already been split.").format(
					frappe.bold(row.item_code)
				)
			)

		created.append(_make_repack(pr, row, frappe.get_doc("Combo Parts", combo)))

	if not created:
		frappe.throw(_("No active Combo Parts mapping found for any item on this Purchase Receipt."))

	return created


def _already_split(purchase_receipt: str, item_code: str) -> bool:
	return bool(
		frappe.db.sql(
			"""
			select se.name from `tabStock Entry` se
			inner join `tabStock Entry Detail` sed on sed.parent = se.name
			where se.docstatus = 1 and se.stock_entry_type = 'Repack'
			  and se.mp_source_purchase_receipt = %s and sed.item_code = %s
			  and ifnull(sed.s_warehouse, '') != ''
			limit 1
			""",
			(purchase_receipt, item_code),
		)
	)


def _make_repack(pr, pr_item, combo) -> str:
	combo_qty = flt(pr_item.stock_qty) or flt(pr_item.qty)
	if combo_qty <= 0:
		frappe.throw(_("Combo item {0} has no received quantity.").format(frappe.bold(pr_item.item_code)))

	parent_value = combo_qty * flt(pr_item.valuation_rate)
	children = [
		{"item_code": row.item_code, "qty": combo_qty * flt(row.qty), "share": flt(row.allocation_percent)}
		for row in combo.combo_part_detail
	]

	total_share = sum(child["share"] for child in children)
	if combo.allocation_method == "Equal" or not total_share:
		for child in children:
			child["share"] = 100.0 / len(children)
		total_share = 100.0

	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Repack"
	entry.purpose = "Repack"
	entry.company = pr.company
	entry.posting_date = nowdate()
	entry.posting_time = nowtime()
	entry.set_posting_time = 1
	entry.mp_source_purchase_receipt = pr.name
	entry.mp_combo_parts = combo.name

	entry.append(
		"items",
		{
			"item_code": pr_item.item_code,
			"qty": combo_qty,
			"s_warehouse": pr_item.warehouse,
			"uom": frappe.db.get_value("Item", pr_item.item_code, "stock_uom"),
		},
	)

	for child in children:
		amount = parent_value * (child["share"] / total_share)
		entry.append(
			"items",
			{
				"item_code": child["item_code"],
				"qty": child["qty"],
				"t_warehouse": pr_item.warehouse,
				"basic_rate": amount / child["qty"] if child["qty"] else 0,
				"allow_zero_valuation_rate": 1,
			},
		)

	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()
	return entry.name
