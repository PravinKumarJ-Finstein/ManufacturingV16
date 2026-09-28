# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Sales Order hooks: fill the Expected Delivery Date on every line."""

import json

import frappe
from frappe import _
from frappe.utils import cint, getdate

from manufacturing_plus.planning.expected_delivery import get_expected_delivery_date
from manufacturing_plus.planning.settings import is_enabled, setting


def set_expected_delivery_dates(doc, method=None):
	"""before_validate: must run before core validate_delivery_date()."""
	if not is_enabled("enable_expected_delivery_date"):
		return

	if cint(len(doc.get("items") or [])) > cint(setting("max_lines_for_sync_compute", 100)):
		for row in doc.items:
			row.mp_calc_status = "Skipped"
		return

	write_rule = setting("delivery_date_write_rule", "Only If Empty")
	latest = None

	for row in doc.items:
		result = get_expected_delivery_date(
			item_code=row.item_code,
			qty=row.qty,
			transaction_date=doc.transaction_date,
			warehouse=row.warehouse,
			company=doc.company,
			uom=row.uom,
			conversion_factor=row.conversion_factor,
			sales_order=doc.name,
		)

		row.mp_expected_delivery_date = result["expected_delivery_date"]
		row.mp_rm_lead_days = result["rm_lead_days"]
		row.mp_queue_days = result["queue_days"]
		row.mp_production_days = result["production_days"]
		row.mp_buffer_days = result["buffer_days"]
		row.mp_bom_used = result["bom_no"]
		row.mp_calc_status = result["status"]
		row.mp_calc_breakdown = json.dumps(result["breakdown"], default=str)

		expected = result["expected_delivery_date"]
		if expected:
			if write_rule == "Always" and not doc.get("mp_manual_delivery_date"):
				row.delivery_date = expected
			elif write_rule == "Only If Empty" and not row.delivery_date:
				row.delivery_date = expected
			elif row.delivery_date and getdate(row.delivery_date) < getdate(expected):
				frappe.msgprint(
					_("Row #{0}: {1} can be delivered by {2}, which is later than the date entered.").format(
						row.idx, frappe.bold(row.item_code), frappe.bold(expected)
					),
					indicator="orange",
					alert=True,
				)

			if not latest or getdate(expected) > getdate(latest):
				latest = expected

	doc.mp_max_expected_delivery_date = latest
	if latest and not doc.delivery_date and write_rule != "Never":
		doc.delivery_date = latest

	_explain_missing_dates(doc)


REASONS = {
	"No BOM": _("no BOM and no lead time on the item"),
	"Partial Data": _("no capacity and no operation time"),
	"Failed": _("the calculation failed - see the Error Log"),
	"Skipped": _("the date engine is switched off, or this order has too many lines"),
}


def _explain_missing_dates(doc) -> None:
	"""Core throws a bare 'Please enter Delivery Date'. Say which rows and why first."""
	blanks = [row for row in doc.items if not row.delivery_date and not row.mp_expected_delivery_date]
	if not blanks:
		return

	lines = [
		_("Row #{0} {1}: {2}").format(
			row.idx, row.item_code, REASONS.get(row.mp_calc_status, _("no date could be worked out"))
		)
		for row in blanks
	]
	frappe.msgprint(
		_(
			"No delivery date could be worked out for these rows. Enter one, or press "
			"<b>Get Expected Delivery Date</b> after fixing the master data:"
		)
		+ "<br>"
		+ "<br>".join(lines),
		title=_("Delivery Date Needed"),
		indicator="orange",
	)


def recompute_after_submit(doc, method=None):
	"""before_update_after_submit: keep the promise in step with Update Items."""
	set_expected_delivery_dates(doc, method)
