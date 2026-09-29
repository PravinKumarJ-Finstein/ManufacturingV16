# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Tidy up after a Master Production Schedule is deleted.

Planning records belong to the plan and go with it: the stock it reserved, the demand rows
it produced and the exceptions raised against it. Purchase documents do not — a Material
Request or Purchase Order can be submitted and may already be a commitment to a supplier,
so those only lose their link back to the plan.
"""

import frappe
from frappe import _


def on_mps_trash(doc, method=None):
	"""Master Production Schedule on_trash."""
	removed = clean_up(doc.name)

	lines = []
	if removed["reservations"]:
		lines.append(_("{0} stock reservation(s) released").format(removed["reservations"]))
	if removed["demands"]:
		lines.append(_("{0} demand row(s) removed").format(removed["demands"]))
	if removed["exceptions"]:
		lines.append(_("{0} exception(s) removed").format(removed["exceptions"]))
	if removed["runs"]:
		lines.append(_("{0} auto purchase run(s) removed").format(removed["runs"]))
	if removed["unlinked"]:
		lines.append(
			_("{0} purchase document(s) kept, with the link to this plan cleared").format(removed["unlinked"])
		)

	if lines:
		frappe.msgprint(
			_("Cleaned up after {0}:").format(frappe.bold(doc.name)) + "<br>" + "<br>".join(lines),
			indicator="orange",
			alert=True,
		)


def clean_up(mps: str) -> dict:
	removed = {"reservations": 0, "demands": 0, "exceptions": 0, "runs": 0, "unlinked": 0}

	# 1. purchase documents keep their data, lose the reference
	for doctype in ("Material Request", "Purchase Order"):
		for name in frappe.get_all(doctype, filters={"mp_master_production_schedule": mps}, pluck="name"):
			frappe.db.set_value(doctype, name, "mp_master_production_schedule", None, update_modified=False)
			removed["unlinked"] += 1

	# 2. stock this plan held is free again
	for name in frappe.get_all(
		"MPS Stock Reservation", filters={"master_production_schedule": mps}, pluck="name"
	):
		frappe.delete_doc("MPS Stock Reservation", name, force=True, ignore_permissions=True)
		removed["reservations"] += 1

	# 3. demand rows: keep the ones that led to a purchase, drop the rest
	for row in frappe.get_all(
		"Sales Order Material Demand",
		filters={"master_production_schedule": mps},
		fields=["name", "material_request", "purchase_order"],
	):
		if row.material_request or row.purchase_order:
			frappe.db.set_value(
				"Sales Order Material Demand",
				row.name,
				"master_production_schedule",
				None,
				update_modified=False,
			)
			removed["unlinked"] += 1
		else:
			frappe.delete_doc("Sales Order Material Demand", row.name, force=True, ignore_permissions=True)
			removed["demands"] += 1

	# 4. exceptions raised against this plan
	for name in frappe.get_all(
		"Auto Purchase Exception", filters={"master_production_schedule": mps}, pluck="name"
	):
		frappe.delete_doc("Auto Purchase Exception", name, force=True, ignore_permissions=True)
		removed["exceptions"] += 1

	# 5. a run with nothing left to show for it goes too; otherwise it just loses the link
	for name in frappe.get_all(
		"Auto Purchase Run", filters={"master_production_schedule": mps}, pluck="name"
	):
		frappe.db.set_value(
			"Auto Purchase Run", name, "master_production_schedule", None, update_modified=False
		)

		still_has = (
			frappe.db.count("Material Request", {"mp_auto_purchase_run": name})
			or frappe.db.count("Purchase Order", {"mp_auto_purchase_run": name})
			or frappe.db.count("Sales Order Material Demand", {"run": name})
		)
		if still_has:
			removed["unlinked"] += 1
			continue

		frappe.delete_doc("Auto Purchase Run", name, force=True, ignore_permissions=True)
		removed["runs"] += 1

	return removed


def on_run_trash(doc, method=None):
	"""Auto Purchase Run on_trash: the run takes everything it produced with it.

	A submitted Purchase Order is a commitment to a supplier, so it is the one thing that
	cannot go: while one exists, the run cannot be deleted at all. Draft and cancelled
	Purchase Orders are deleted with the run, as are the Material Requests, the demand rows,
	the stock it reserved and the exceptions it raised. The plan itself stays, and only
	loses the link.
	"""
	block_delete_if_ordered(doc.name)
	removed = clean_up_run(doc.name)

	lines = []
	if removed["purchase_orders"]:
		lines.append(_("{0} Purchase Order(s) deleted").format(removed["purchase_orders"]))
	if removed["material_requests"]:
		lines.append(_("{0} Material Request(s) deleted").format(removed["material_requests"]))
	if removed["demands"]:
		lines.append(_("{0} demand row(s) deleted").format(removed["demands"]))
	if removed["reservations"]:
		lines.append(_("{0} stock reservation(s) released and deleted").format(removed["reservations"]))
	if removed["exceptions"]:
		lines.append(_("{0} exception(s) deleted").format(removed["exceptions"]))
	if removed["unlinked"]:
		lines.append(_("{0} plan(s) kept, with the link to this run cleared").format(removed["unlinked"]))

	if lines:
		frappe.msgprint(
			_("Cleaned up after {0}:").format(frappe.bold(doc.name)) + "<br>" + "<br>".join(lines),
			indicator="orange",
			alert=True,
		)


def submitted_purchase_orders(run: str) -> list[str]:
	"""Purchase Orders of this run that are already with the supplier."""
	return frappe.get_all(
		"Purchase Order", filters={"mp_auto_purchase_run": run, "docstatus": 1}, pluck="name"
	)


def block_delete_if_ordered(run: str) -> None:
	ordered = submitted_purchase_orders(run)
	if not ordered:
		return

	frappe.throw(
		_("{0} cannot be deleted: it has submitted Purchase Order(s) {1}.").format(
			frappe.bold(run), ", ".join(frappe.bold(name) for name in ordered)
		)
		+ "<br><br>"
		+ _("Cancel those Purchase Orders first, then delete this run."),
		title=_("Purchase Order already placed"),
	)


def reserved_by_run(run: str) -> list[str]:
	"""Reservations this run placed: those of its Sales Order, and those of its plan(s)."""
	plans = frappe.get_all("Master Production Schedule", filters={"mp_auto_purchase_run": run}, pluck="name")
	sales_order = frappe.db.get_value("Auto Purchase Run", run, "sales_order")

	names = set()
	if sales_order:
		names.update(
			frappe.get_all("MPS Stock Reservation", filters={"sales_order": sales_order}, pluck="name")
		)
	if plans:
		names.update(
			frappe.get_all(
				"MPS Stock Reservation", filters={"master_production_schedule": ["in", plans]}, pluck="name"
			)
		)

	return sorted(names)


def clean_up_run(run: str) -> dict:
	removed = {
		"unlinked": 0,
		"demands": 0,
		"exceptions": 0,
		"reservations": 0,
		"material_requests": 0,
		"purchase_orders": 0,
	}

	# read first: clearing the plan link below would hide the plan's own reservations
	reservations = reserved_by_run(run)

	# the plan points back at the run; the plan stays, the link does not
	for name in frappe.get_all(
		"Master Production Schedule", filters={"mp_auto_purchase_run": run}, pluck="name"
	):
		frappe.db.set_value(
			"Master Production Schedule", name, "mp_auto_purchase_run", None, update_modified=False
		)
		removed["unlinked"] += 1

	# deleted in link order: what points at a document goes before the document itself
	for name in frappe.get_all("Auto Purchase Exception", filters={"run": run}, pluck="name"):
		frappe.delete_doc("Auto Purchase Exception", name, force=True, ignore_permissions=True)
		removed["exceptions"] += 1

	for name in frappe.get_all("Sales Order Material Demand", filters={"run": run}, pluck="name"):
		frappe.delete_doc("Sales Order Material Demand", name, force=True, ignore_permissions=True)
		removed["demands"] += 1

	# the stock this run held goes back: the hold only ever existed because of the run
	for name in reservations:
		frappe.delete_doc("MPS Stock Reservation", name, force=True, ignore_permissions=True)
		removed["reservations"] += 1

	for doctype, key in (("Purchase Order", "purchase_orders"), ("Material Request", "material_requests")):
		for name in frappe.get_all(doctype, filters={"mp_auto_purchase_run": run}, pluck="name"):
			_cancel_and_delete(doctype, name)
			removed[key] += 1

	return removed


def _cancel_and_delete(doctype: str, name: str) -> None:
	"""A submitted document has to be cancelled before it can go.

	Purchase Orders never reach here submitted — block_delete_if_ordered stops the delete
	first. A submitted Material Request can, and is cancelled on the way out.
	"""
	doc = frappe.get_doc(doctype, name)
	if doc.docstatus == 1:
		doc.flags.ignore_permissions = True
		doc.cancel()

	frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)


@frappe.whitelist()
def get_run_impact(run: str) -> dict:
	"""What deleting this run would touch. Read-only: shown before anything happens."""
	frappe.has_permission("Auto Purchase Run", "delete", throw=True)

	material_requests = frappe.get_all(
		"Material Request", filters={"mp_auto_purchase_run": run}, fields=["name", "docstatus"]
	)
	purchase_orders = frappe.get_all(
		"Purchase Order", filters={"mp_auto_purchase_run": run}, fields=["name", "docstatus", "grand_total"]
	)
	blocked_by = [p.name for p in purchase_orders if p.docstatus == 1]

	return {
		"master_production_schedules": frappe.get_all(
			"Master Production Schedule", filters={"mp_auto_purchase_run": run}, pluck="name"
		),
		"material_requests": material_requests,
		"submitted_material_requests": [m.name for m in material_requests if m.docstatus == 1],
		"purchase_orders": purchase_orders,
		"submitted_purchase_orders": blocked_by,
		"can_delete": not blocked_by,
		"demand_rows": frappe.db.count("Sales Order Material Demand", {"run": run}),
		"reservations": len(reserved_by_run(run)),
		"exceptions": frappe.db.count("Auto Purchase Exception", {"run": run}),
	}
