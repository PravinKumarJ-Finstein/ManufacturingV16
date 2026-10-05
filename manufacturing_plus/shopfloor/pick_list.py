# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Pick List: earliest-expiry batches, and the Stock Entry that follows submit."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, nowtime

from manufacturing_plus.planning.settings import is_enabled

PURPOSE_TO_TYPE = {
	"Material Transfer for Manufacture": "Material Transfer for Manufacture",
	"Material Transfer": "Material Transfer",
	"Delivery": "Material Issue",
}


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

	try:
		name = build_stock_entry(doc)
	except Exception:
		frappe.log_error(
			title=f"Auto Stock Entry failed for Pick List {doc.name}", message=frappe.get_traceback()
		)
		frappe.msgprint(
			_(
				"The Stock Entry could not be created automatically. Use Create Stock Entry on this Pick List."
			),
			indicator="orange",
			title=_("Stock Entry Not Created"),
		)
		return

	if name:
		frappe.msgprint(
			_("Stock Entry {0} created and submitted from this Pick List.").format(frappe.bold(name)),
			indicator="green",
			alert=True,
		)


@frappe.whitelist()
def make_stock_entry(pick_list: str) -> str | None:
	"""Create the transfer by hand, for a Pick List whose automatic one did not run."""
	frappe.has_permission("Stock Entry", "create", throw=True)

	doc = frappe.get_doc("Pick List", pick_list)
	if doc.docstatus != 1:
		frappe.throw(_("Pick List {0} is not submitted.").format(frappe.bold(doc.name)))

	name = build_stock_entry(doc)
	if not name:
		frappe.throw(_("Everything on this Pick List has already been transferred."))

	return name


def build_stock_entry(doc) -> str | None:
	"""Map the Pick List onto a Stock Entry, then insert **and submit** it.

	Core's own ``create_stock_entry`` only maps: it returns an unsaved dictionary for the
	client to open as a draft. Nothing reaches the database unless somebody saves it, which
	is why a submitted Pick List used to leave no transfer behind at all.

	Three things have to be put right on the mapped document before it will go in:

	* ``work_order`` on the Stock Entry — without it core's
	  ``update_transferred_qty_for_required_items`` never updates the Work Order, so the
	  material shows as still outstanding after the transfer.
	* ``stock_entry_type`` — a Work Order transfer must be *Material Transfer for
	  Manufacture*, or the same update skips the entry.
	* the serial and batch bundle — every voucher needs its own. The mapped rows still point
	  at the Pick List's bundle, so the reference is cleared and the batch number left in
	  place for core to build a fresh bundle on submit.
	"""
	from erpnext.stock.doctype.pick_list.pick_list import create_stock_entry

	existing = frappe.db.get_value("Stock Entry", {"pick_list": doc.name, "docstatus": ["<", 2]}, "name")
	if existing:
		return existing

	built = create_stock_entry(doc.as_dict())
	if not built:
		# core returns nothing when every picked row is already transferred
		return None

	entry = frappe.get_doc(built) if isinstance(built, dict) else built
	entry.pick_list = doc.name

	if doc.get("work_order") and not entry.get("work_order"):
		entry.work_order = doc.work_order

	entry.posting_date = entry.posting_date or nowdate()
	entry.posting_time = entry.posting_time or nowtime()

	if not entry.stock_entry_type:
		entry.stock_entry_type = PURPOSE_TO_TYPE.get(
			doc.purpose, "Material Transfer for Manufacture" if doc.get("work_order") else "Material Transfer"
		)

	for row in entry.get("items") or []:
		if row.get("serial_and_batch_bundle"):
			# that bundle belongs to the Pick List; this voucher gets one of its own on submit
			row.serial_and_batch_bundle = None
		if row.get("batch_no") or row.get("serial_no"):
			row.use_serial_batch_fields = 1

	entry.insert()
	entry.submit()

	return entry.name
