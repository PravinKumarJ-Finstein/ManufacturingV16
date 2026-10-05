# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Work Order rules: source, planned-qty tracking and the Pick List buffer."""

import frappe
from frappe import _
from frappe.utils import cint, flt

from manufacturing_plus.planning.settings import is_enabled
from manufacturing_plus.shopfloor.buffer import get_buffer_qty


def validate_work_order(doc, method=None):
	"""A Work Order may only come from a Production Plan when the rule is on."""
	if not is_enabled("wo_only_from_production_plan"):
		return

	if doc.get("production_plan"):
		return

	if doc.flags.get("ignore_mp_wo_source") or frappe.flags.get("ignore_mp_wo_source"):
		return

	frappe.throw(
		_(
			"A Work Order can only be created from a Production Plan.<br>"
			"Turn off <b>Work Order Only From Production Plan</b> in Manufacturing Control Setting to allow it."
		),
		title=_("Production Plan Required"),
	)


def apply_pick_list_buffer(doc, method=None):
	"""before_submit: add the slab buffer to every required item, once for this Work Order."""
	if not is_enabled("enable_pick_list_buffer") or not doc.get("required_items"):
		return

	total_buffer = 0.0
	for row in doc.required_items:
		buffer_qty = get_buffer_qty(row.item_code, flt(row.required_qty), 1)
		if buffer_qty > 0:
			row.required_qty = flt(row.required_qty) + buffer_qty
			total_buffer += buffer_qty

	if total_buffer:
		doc.mp_buffer_qty = total_buffer


def track_planned_qty(doc, method=None):
	"""Production Plan submit / cancel: keep the Sales Order line's planned qty in step."""
	if not is_enabled("track_so_planned_qty"):
		return

	# the field is ours, and a Production Plan must never fail to submit because it is absent
	if not frappe.db.has_column("Sales Order Item", "mp_planned_qty"):
		frappe.log_error(
			title="Planned qty not tracked",
			message="Sales Order Item.mp_planned_qty is missing. Run bench migrate to create it.",
		)
		return

	planned: dict[str, float] = {}
	for row in doc.get("po_items") or []:
		if row.get("sales_order_item"):
			sign = 1 if doc.docstatus == 1 else -1
			planned[row.sales_order_item] = planned.get(row.sales_order_item, 0.0) + sign * flt(
				row.planned_qty
			)

	for so_item, qty in planned.items():
		current = flt(frappe.db.get_value("Sales Order Item", so_item, "mp_planned_qty"))
		frappe.db.set_value(
			"Sales Order Item", so_item, "mp_planned_qty", max(current + qty, 0.0), update_modified=False
		)
