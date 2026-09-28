# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Nightly clean-up of Work Orders nobody acted on."""

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from manufacturing_plus.planning.settings import is_enabled, setting

MAX_PER_RUN = 500


def run_cleanup(dry_run: bool = False) -> dict:
	"""Delete stale drafts and cancel stale Not Started Work Orders."""
	result = {"deleted": 0, "cancelled": 0, "blocked": 0, "enabled": False}
	if not is_enabled("auto_cleanup_stale_wo"):
		return result

	result["enabled"] = True
	cutoff = add_to_date(now_datetime(), hours=-(cint(setting("stale_wo_age_hours", 72)) or 72))

	for name in frappe.get_all(
		"Work Order",
		filters={"docstatus": 0, "creation": ["<=", cutoff]},
		pluck="name",
		limit=MAX_PER_RUN,
		order_by="creation asc",
	):
		if dry_run:
			result["deleted"] += 1
			continue
		try:
			frappe.delete_doc("Work Order", name, ignore_permissions=True)
			frappe.db.commit()
			result["deleted"] += 1
		except Exception:
			frappe.db.rollback()
			result["blocked"] += 1

	for name in frappe.get_all(
		"Work Order",
		filters={"docstatus": 1, "status": "Not Started", "creation": ["<=", cutoff]},
		pluck="name",
		limit=MAX_PER_RUN,
		order_by="creation asc",
	):
		if blocker := get_cancel_blocker(name):
			result["blocked"] += 1
			frappe.logger("manufacturing_plus").info(f"Work Order {name} kept: {blocker}")
			continue

		if dry_run:
			result["cancelled"] += 1
			continue
		try:
			frappe.get_doc("Work Order", name).cancel()
			frappe.db.commit()
			result["cancelled"] += 1
		except Exception:
			frappe.db.rollback()
			result["blocked"] += 1

	return result


def get_cancel_blocker(work_order: str) -> str | None:
	"""Anything downstream means the shop floor has already picked this Work Order up."""
	if frappe.db.exists("Stock Entry", {"work_order": work_order, "docstatus": 1}):
		return "a submitted Stock Entry exists"

	if frappe.db.exists("Pick List", {"work_order": work_order, "docstatus": 1}):
		return "a submitted Pick List exists"

	if frappe.db.exists(
		"Job Card",
		{
			"work_order": work_order,
			"status": ["in", ("Work In Progress", "Material Transferred", "Completed")],
		},
	):
		return "a Job Card has already started"

	return None
