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
	"""Auto Purchase Run on_trash: keep the purchase documents, drop the planning ones."""
	removed = clean_up_run(doc.name)

	lines = []
	if removed["unlinked"]:
		lines.append(
			_("{0} purchase document(s) kept, with the link to this run cleared").format(removed["unlinked"])
		)
	if removed["demands"]:
		lines.append(_("{0} demand row(s) removed").format(removed["demands"]))
	if removed["exceptions"]:
		lines.append(_("{0} exception(s) removed").format(removed["exceptions"]))

	if lines:
		frappe.msgprint(
			_("Cleaned up after {0}:").format(frappe.bold(doc.name)) + "<br>" + "<br>".join(lines),
			indicator="orange",
			alert=True,
		)


def clean_up_run(run: str) -> dict:
	removed = {"unlinked": 0, "demands": 0, "exceptions": 0}

	# the plan points back at the run; that link would block the delete
	for name in frappe.get_all(
		"Master Production Schedule", filters={"mp_auto_purchase_run": run}, pluck="name"
	):
		frappe.db.set_value(
			"Master Production Schedule", name, "mp_auto_purchase_run", None, update_modified=False
		)
		removed["unlinked"] += 1

	for doctype in ("Material Request", "Purchase Order"):
		for name in frappe.get_all(doctype, filters={"mp_auto_purchase_run": run}, pluck="name"):
			frappe.db.set_value(doctype, name, "mp_auto_purchase_run", None, update_modified=False)
			removed["unlinked"] += 1

	for row in frappe.get_all(
		"Sales Order Material Demand",
		filters={"run": run},
		fields=["name", "material_request", "purchase_order"],
	):
		if row.material_request or row.purchase_order:
			frappe.db.set_value("Sales Order Material Demand", row.name, "run", None, update_modified=False)
			removed["unlinked"] += 1
		else:
			frappe.delete_doc("Sales Order Material Demand", row.name, force=True, ignore_permissions=True)
			removed["demands"] += 1

	for name in frappe.get_all("Auto Purchase Exception", filters={"run": run}, pluck="name"):
		frappe.delete_doc("Auto Purchase Exception", name, force=True, ignore_permissions=True)
		removed["exceptions"] += 1

	return removed


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

	return {
		"master_production_schedules": frappe.get_all(
			"Master Production Schedule", filters={"mp_auto_purchase_run": run}, pluck="name"
		),
		"material_requests": material_requests,
		"purchase_orders": purchase_orders,
		"submitted_purchase_orders": [p.name for p in purchase_orders if p.docstatus == 1],
		"demand_rows": frappe.db.count("Sales Order Material Demand", {"run": run}),
		"demand_rows_kept": frappe.db.count(
			"Sales Order Material Demand",
			{"run": run, "purchase_order": ["is", "set"]},
		),
		"exceptions": frappe.db.count("Auto Purchase Exception", {"run": run}),
	}
