# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Job Card gates: a submitted Pick List, and the setup verification."""

import frappe
from frappe import _

from manufacturing_plus.planning.settings import is_enabled

STARTED_STATUSES = ("Work In Progress", "Material Transferred", "Completed")


def validate_job_card(doc, method=None):
	if doc.get("status") not in STARTED_STATUSES or not doc.get("work_order"):
		return

	if is_enabled("job_card_requires_pick_list"):
		_require_pick_list(doc)

	if is_enabled("require_job_setup_verification"):
		_require_setup_verification(doc)


def _require_pick_list(doc) -> None:
	if frappe.db.exists("Pick List", {"work_order": doc.work_order, "docstatus": 1}):
		return

	frappe.throw(
		_("Cannot start this Job Card. Submit a Pick List for Work Order {0} first.").format(
			frappe.bold(doc.work_order)
		),
		title=_("Pick List Required"),
	)


def _require_setup_verification(doc) -> None:
	filters = {"work_order": doc.work_order, "docstatus": 1}
	if doc.get("operation"):
		filters["operation"] = doc.operation

	if frappe.db.exists("Job Setup Verification", filters):
		return

	frappe.throw(
		_(
			"Cannot start this Job Card. A submitted Job Setup Verification is needed for "
			"Work Order {0}, operation {1}."
		).format(frappe.bold(doc.work_order), frappe.bold(doc.operation or "")),
		title=_("Setup Verification Required"),
	)


def update_work_order_status(doc, method=None):
	"""Work Order follows the shop floor: any started Job Card means In Process."""
	if not is_enabled("sync_wo_status_from_job_card"):
		return

	if not doc.get("work_order"):
		return

	work_order = frappe.db.get_value("Work Order", doc.work_order, ["status", "docstatus"], as_dict=True)
	if not work_order or work_order.docstatus != 1 or work_order.status in ("Completed", "Stopped", "Closed"):
		return

	if doc.get("status") in STARTED_STATUSES and work_order.status == "Not Started":
		frappe.db.set_value("Work Order", doc.work_order, "status", "In Process", update_modified=False)
