# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Pick List: earliest-expiry batches, and the Stock Entry that follows submit."""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from manufacturing_plus.planning.settings import is_enabled


def validate_pick_list(doc, method=None):
	"""Block expired batches, and warn when a batch-tracked row has no batch."""
	if not is_enabled("block_expired_batches"):
		return

	for row in doc.get("locations") or []:
		if not row.get("batch_no"):
			continue

		expiry = frappe.db.get_value("Batch", row.batch_no, "expiry_date")
		if expiry and getdate(expiry) <= getdate():
			frappe.throw(
				_("Row #{0}: batch {1} of item {2} expired on {3}.").format(
					row.idx, frappe.bold(row.batch_no), frappe.bold(row.item_code), expiry
				),
				title=_("Expired Batch"),
			)


def warn_on_duplicate(doc, method=None):
	"""A second Pick List for the same Work Order is usually a mistake."""
	if not is_enabled("warn_duplicate_pick_list"):
		return

	if not doc.get("work_order") or not doc.is_new():
		return

	existing = frappe.get_all(
		"Pick List",
		filters={"work_order": doc.work_order, "docstatus": ["<", 2], "name": ["!=", doc.name or ""]},
		pluck="name",
	)
	if existing:
		frappe.msgprint(
			_("Pick List {0} already exists for Work Order {1}.").format(
				frappe.bold(", ".join(existing)), frappe.bold(doc.work_order)
			),
			indicator="orange",
			alert=True,
		)


def create_stock_entry_on_submit(doc, method=None):
	"""Material Transfer for Manufacture, straight after the Pick List is submitted."""
	if not is_enabled("auto_stock_entry_on_pick_list") or not doc.get("work_order"):
		return

	if doc.purpose != "Material Transfer for Manufacture":
		return

	if frappe.db.exists("Stock Entry", {"pick_list": doc.name, "docstatus": ["<", 2]}):
		return

	from erpnext.stock.doctype.pick_list.pick_list import create_stock_entry

	try:
		entry = create_stock_entry(doc.as_dict())
	except Exception:
		frappe.log_error(
			title=f"Auto Stock Entry failed for Pick List {doc.name}", message=frappe.get_traceback()
		)
		frappe.msgprint(
			_("The Stock Entry could not be created automatically. Please create it from the Pick List."),
			indicator="orange",
			alert=True,
		)
		return

	name = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", None)
	if name:
		frappe.msgprint(
			_("Stock Entry {0} created from this Pick List.").format(frappe.bold(name)),
			indicator="green",
			alert=True,
		)
