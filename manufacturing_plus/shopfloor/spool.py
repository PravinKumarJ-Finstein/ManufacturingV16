# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Spool / reel tracking.

A spool is a row on its Batch (`Spool Details`), the same shape the Kaynes v15 app uses.
There is no spool master: the balance is worked out from the documents that moved it —
submitted Pick Lists consume, submitted Stores Returns give back — and the totals are
written back onto the batch row afterwards.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, nowdate

from manufacturing_plus.planning.settings import is_enabled

TOLERANCE = 1e-6
SPOOL_FIELD = "custom_spool_details"


def get_spool_row(spool_id: str) -> frappe._dict | None:
	"""The batch row that holds this spool."""
	rows = frappe.db.sql(
		"""
		select sd.name, sd.parent as batch_no, sd.spool_id, sd.spool_qty, sd.status,
		       b.item as item_code
		from `tabSpool Details` sd
		inner join `tabBatch` b on b.name = sd.parent
		where sd.spool_id = %s
		limit 1
		""",
		spool_id,
		as_dict=True,
	)
	return rows[0] if rows else None


def get_balance(spool_id: str, spool_qty: float | None = None) -> float:
	"""Issued qty less what came back, worked out from the documents."""
	if spool_qty is None:
		row = get_spool_row(spool_id)
		if not row:
			return 0.0
		spool_qty = row.spool_qty

	consumed = flt(
		frappe.db.sql(
			"""
			select sum(d.consumed_qty)
			from `tabPick List Spool Detail` d
			inner join `tabPick List` p on p.name = d.parent
			where p.docstatus = 1 and d.spool_id = %s
			""",
			spool_id,
		)[0][0]
	)
	returned = flt(
		frappe.db.sql(
			"""
			select sum(i.return_qty)
			from `tabStores Return Item` i
			inner join `tabStores Return` r on r.name = i.parent
			where r.docstatus = 1 and i.spool_id = %s
			""",
			spool_id,
		)[0][0]
	)

	return max(flt(spool_qty) - consumed + returned, 0.0)


def sync_batch_row(spool_id: str) -> None:
	"""Write the consumed / returned totals back onto the batch row."""
	row = get_spool_row(spool_id)
	if not row:
		return

	consumed = flt(
		frappe.db.sql(
			"""
			select sum(d.consumed_qty)
			from `tabPick List Spool Detail` d
			inner join `tabPick List` p on p.name = d.parent
			where p.docstatus = 1 and d.spool_id = %s
			""",
			spool_id,
		)[0][0]
	)
	returned = flt(
		frappe.db.sql(
			"""
			select sum(i.return_qty)
			from `tabStores Return Item` i
			inner join `tabStores Return` r on r.name = i.parent
			where r.docstatus = 1 and i.spool_id = %s
			""",
			spool_id,
		)[0][0]
	)
	balance = max(flt(row.spool_qty) - consumed + returned, 0.0)

	if balance <= TOLERANCE:
		status = "Consumed"
	elif returned > TOLERANCE:
		status = "Returned"
	elif consumed > TOLERANCE:
		status = "In Use"
	else:
		status = "Active"

	frappe.db.set_value(
		"Spool Details",
		row.name,
		{
			"consumed_for_manufacturing": consumed,
			"return_remaining_spool_qty": balance,
			"status": status,
		},
		update_modified=False,
	)


def is_spool_item(item_code: str) -> bool:
	"""True when any batch of this item carries spool rows."""
	return bool(
		frappe.db.sql(
			"""
			select sd.name from `tabSpool Details` sd
			inner join `tabBatch` b on b.name = sd.parent
			where b.item = %s limit 1
			""",
			item_code,
		)
	)


@frappe.whitelist()
def resolve_scan(pick_list: str, scanned_value: str) -> dict:
	"""Match a scanned spool ID to a Pick List row and allocate its balance."""
	if not is_enabled("enable_spool_tracking"):
		frappe.throw(_("Spool tracking is switched off in Manufacturing Control Setting."))

	spool_id = (scanned_value or "").strip()
	if not spool_id:
		frappe.throw(_("Nothing was scanned."))

	spool = get_spool_row(spool_id)
	if not spool:
		frappe.throw(_("No spool found with ID {0}.").format(frappe.bold(spool_id)))

	balance = get_balance(spool_id, spool.spool_qty)
	if balance <= TOLERANCE:
		frappe.throw(_("Spool {0} has no balance left.").format(frappe.bold(spool_id)))

	doc = frappe.get_doc("Pick List", pick_list)
	row = next((r for r in doc.locations if r.item_code == spool.item_code), None)
	if not row:
		frappe.throw(
			_("Spool {0} is item {1}, which is not on this Pick List.").format(
				frappe.bold(spool_id), frappe.bold(spool.item_code)
			)
		)

	if row.batch_no and spool.batch_no != row.batch_no:
		frappe.throw(
			_("Spool {0} belongs to batch {1}, but row #{2} needs batch {3}.").format(
				frappe.bold(spool_id), spool.batch_no, row.idx, row.batch_no
			)
		)

	if any(d.spool_id == spool_id for d in doc.get("mp_spool_details") or []):
		frappe.throw(_("Spool {0} has already been scanned on this Pick List.").format(frappe.bold(spool_id)))

	outstanding = _outstanding_qty(doc, row)
	consumed = min(balance, outstanding) if outstanding > TOLERANCE else balance

	doc.append(
		"mp_spool_details",
		{
			"row_no": row.idx,
			"is_scanned": 1,
			"spool_id": spool_id,
			"spool_qty": spool.spool_qty,
			"consumed_qty": consumed,
			"item_code": spool.item_code,
			"batch_no": spool.batch_no,
			"scanned_on": now_datetime(),
			"pick_list_item": row.name,
		},
	)
	doc.save(ignore_permissions=True)

	return {
		"spool_id": spool_id,
		"item_code": spool.item_code,
		"consumed_qty": consumed,
		"outstanding_qty": max(outstanding - consumed, 0.0),
		"message": _("Scanned {0}: {1} allocated to row #{2}.").format(spool_id, consumed, row.idx),
	}


def _outstanding_qty(doc, row) -> float:
	allocated = sum(
		flt(d.consumed_qty) for d in doc.get("mp_spool_details") or [] if d.pick_list_item == row.name
	)
	return flt(row.stock_qty or row.qty) - allocated


def validate_spool_allocation(doc, method=None):
	"""before_submit: every spool must exist and have the balance, and excess needs a note."""
	if not is_enabled("enable_spool_tracking"):
		return

	details = doc.get("mp_spool_details") or []
	if not details:
		return

	for detail in details:
		spool = get_spool_row(detail.spool_id)
		if not spool:
			frappe.throw(_("Row #{0}: spool {1} does not exist.").format(detail.idx, detail.spool_id))

		balance = get_balance(detail.spool_id, spool.spool_qty)
		if flt(detail.consumed_qty) - balance > TOLERANCE:
			frappe.throw(
				_("Row #{0}: spool {1} only has {2} left, but {3} is being issued.").format(
					detail.idx, detail.spool_id, balance, detail.consumed_qty
				)
			)

	_validate_excess(doc, details)


def _validate_excess(doc, details) -> None:
	"""Issuing more than the Pick List needs requires a submitted Excess Issue Note."""
	issued: dict[str, float] = {}
	for detail in details:
		issued[detail.item_code] = issued.get(detail.item_code, 0.0) + flt(detail.consumed_qty)

	required: dict[str, float] = {}
	for row in doc.locations:
		required[row.item_code] = required.get(row.item_code, 0.0) + flt(row.stock_qty or row.qty)

	for item_code, qty in issued.items():
		excess = qty - required.get(item_code, 0.0)
		if excess <= TOLERANCE:
			continue

		covered = flt(
			frappe.db.sql(
				"""
				select sum(excess_qty) from `tabExcess Issue Note`
				where docstatus = 1 and pick_list = %s and item_code = %s
				""",
				(doc.name, item_code),
			)[0][0]
		)
		if covered + TOLERANCE < excess:
			frappe.throw(
				_(
					"Item {0}: {1} more than needed is being issued. Submit an Excess Issue Note for "
					"at least {2} first."
				).format(frappe.bold(item_code), excess, excess - covered),
				title=_("Excess Issue Note Required"),
			)


def consume_spools(doc, method=None):
	"""on_submit: refresh the batch rows this Pick List touched."""
	_resync(doc)


def release_spools(doc, method=None):
	"""on_cancel: the consumption no longer counts, so refresh the same rows."""
	_resync(doc)


def _resync(doc) -> None:
	if not is_enabled("enable_spool_tracking"):
		return

	for spool_id in {d.spool_id for d in doc.get("mp_spool_details") or [] if d.spool_id}:
		sync_batch_row(spool_id)


def apply_stores_return(stores_return, method=None):
	"""Stores Return submit: stock back to the store, then refresh the batch rows."""
	entry = frappe.new_doc("Stock Entry")
	entry.stock_entry_type = "Material Transfer"
	entry.purpose = "Material Transfer"
	entry.company = stores_return.company
	entry.posting_date = nowdate()

	for row in stores_return.items:
		entry.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": flt(row.return_qty),
				"s_warehouse": stores_return.from_warehouse,
				"t_warehouse": stores_return.to_warehouse,
				"batch_no": row.batch_no,
			},
		)

	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()

	stores_return.db_set("stock_entry", entry.name, update_modified=False)

	for row in stores_return.items:
		if row.spool_id:
			sync_batch_row(row.spool_id)


@frappe.whitelist()
def get_returnable_spools(pick_list: str) -> list[dict]:
	"""What this Pick List still holds on the shop floor, per spool."""
	doc = frappe.get_doc("Pick List", pick_list)
	rows = []

	for detail in doc.get("mp_spool_details") or []:
		returned = flt(
			frappe.db.sql(
				"""
				select sum(i.return_qty)
				from `tabStores Return Item` i
				inner join `tabStores Return` r on r.name = i.parent
				where r.docstatus = 1 and r.pick_list = %s and i.spool_id = %s
				""",
				(pick_list, detail.spool_id),
			)[0][0]
		)
		outstanding = flt(detail.consumed_qty) - returned
		if outstanding > TOLERANCE:
			rows.append(
				{
					"spool_id": detail.spool_id,
					"item_code": detail.item_code,
					"batch_no": detail.batch_no,
					"return_qty": outstanding,
				}
			)

	return rows
