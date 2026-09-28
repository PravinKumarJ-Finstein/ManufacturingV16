# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Scheduled clean-up jobs."""

import frappe
from frappe.utils import add_days, cint, nowdate

from manufacturing_plus.planning.settings import setting
from manufacturing_plus.purchasing import reservation


def release_expired_reservations():
	released = reservation.release_expired()
	if released:
		frappe.logger("manufacturing_plus").info(f"Released {released} expired MPS reservations")


def delete_stale_draft_pos():
	"""Remove auto-created draft POs nobody acted on."""
	days = cint(setting("delete_stale_draft_po_days", 0))
	if not days:
		return

	cutoff = add_days(nowdate(), -days)
	names = frappe.get_all(
		"Purchase Order",
		filters={"docstatus": 0, "mp_auto_purchased": 1, "creation": ["<", cutoff]},
		pluck="name",
	)

	for name in names:
		try:
			frappe.delete_doc("Purchase Order", name, ignore_permissions=True, delete_permanently=False)
		except Exception:
			frappe.log_error(title=f"Could not delete stale auto PO {name}", message=frappe.get_traceback())
