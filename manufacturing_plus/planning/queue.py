# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Backlog already committed on the workstations this item needs."""

import frappe
from frappe.utils import cint, flt

from manufacturing_plus.planning.capacity import get_bom_operations, hours_per_day, operation_hours
from manufacturing_plus.planning.settings import setting


@frappe.request_cache
def get_open_so_lines(company: str | None, exclude_sales_order: str | None, include_drafts: int = 0) -> tuple:
	"""Submitted, still pending Sales Order lines with a default BOM."""
	values = {}
	docstatus = (
		"so.docstatus in (0, 1)" if cint(setting("include_drafts_in_queue", 0)) else "so.docstatus = 1"
	)
	conditions = [
		docstatus,
		"so.status not in ('Closed', 'Completed', 'Stopped')",
		"soi.qty > ifnull(soi.delivered_qty, 0)",
		"ifnull(i.default_bom, '') != ''",
	]
	if company:
		conditions.append("so.company = %(company)s")
		values["company"] = company
	if exclude_sales_order:
		conditions.append("so.name != %(exclude_so)s")
		values["exclude_so"] = exclude_sales_order

	rows = frappe.db.sql(
		f"""
		select soi.item_code, i.default_bom as bom_no, soi.delivery_date,
		       (soi.stock_qty - ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1)) as pending_qty
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		inner join `tabItem` i on i.name = soi.item_code
		where {" and ".join(conditions)}
		order by soi.delivery_date asc
		""",
		values,
		as_dict=True,
	)
	return tuple(frappe._dict(r) for r in rows)


def get_queue_days(
	bom_no: str, item_code: str, company: str | None = None, exclude_sales_order: str | None = None
) -> dict:
	"""Days of work already promised on the same workstations, ahead of this line."""
	empty = {"days": 0.0, "workstations": [], "orders": 0}
	if not cint(setting("consider_committed_orders", 1)) or not bom_no:
		return empty

	operations = get_bom_operations(bom_no)
	my_workstations = {op.workstation for op in operations if op.workstation}
	if not my_workstations:
		return empty

	scope_is_item = setting("queue_scope", "Workstation") == "Item"
	backlog: dict[str, float] = {}
	orders = 0

	for line in get_open_so_lines(company, exclude_sales_order, cint(setting("include_drafts_in_queue", 0))):
		if scope_is_item and line.item_code != item_code:
			continue

		line_ops = get_bom_operations(line.bom_no)
		if not any(op.workstation in my_workstations for op in line_ops):
			continue

		orders += 1
		bom_qty = flt(frappe.db.get_value("BOM", line.bom_no, "quantity")) or 1.0
		for op in line_ops:
			if op.workstation not in my_workstations:
				continue

			hours, source = operation_hours(op, flt(line.pending_qty), bom_qty)
			if not source:
				continue

			backlog[op.workstation] = backlog.get(op.workstation, 0.0) + hours / (
				hours_per_day(op.workstation) or 1
			)

	if not backlog:
		return empty

	return {
		"days": flt(sum(backlog.values()), 3),
		"workstations": [{"workstation": k, "days": flt(v, 3)} for k, v in sorted(backlog.items())],
		"orders": orders,
	}
