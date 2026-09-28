# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""How many finished goods can be built from the stock on hand today."""

import frappe
from frappe.utils import flt, now_datetime

from manufacturing_plus.planning.settings import is_enabled
from manufacturing_plus.planning.stock import get_bin_qty


def calculate(company: str) -> list[dict]:
	"""Greedy allocation: highest-value order first, limited by the scarcest component."""
	rows = frappe.db.sql(
		"""
		select soi.item_code, i.default_bom as bom_no,
		       sum(soi.stock_qty - ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1)) as pending_qty,
		       sum(soi.base_amount) as value
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		inner join `tabItem` i on i.name = soi.item_code and ifnull(i.default_bom, '') != ''
		where so.docstatus = 1 and so.company = %(company)s
		  and so.status not in ('Closed', 'Completed', 'Stopped')
		  and soi.qty > ifnull(soi.delivered_qty, 0)
		group by soi.item_code, i.default_bom
		order by value desc
		""",
		{"company": company},
		as_dict=True,
	)
	if not rows:
		return []

	components: dict[str, list] = {}
	for row in rows:
		components[row.item_code] = frappe.get_all(
			"BOM Explosion Item",
			filters={"parent": row.bom_no, "is_sub_assembly_item": 0},
			fields=["item_code", "qty_consumed_per_unit"],
		)

	all_items = {c.item_code for rows_ in components.values() for c in rows_}
	available = get_bin_qty(list(all_items), company)
	result = []

	for row in rows:
		buildable, limiting = flt(row.pending_qty), None
		for component in components[row.item_code]:
			per_unit = flt(component.qty_consumed_per_unit)
			if per_unit <= 0:
				continue
			possible = flt(available.get(component.item_code, 0)) / per_unit
			if possible < buildable:
				buildable, limiting = possible, component.item_code

		buildable = max(int(buildable), 0)
		for component in components[row.item_code]:
			available[component.item_code] = flt(available.get(component.item_code, 0)) - (
				buildable * flt(component.qty_consumed_per_unit)
			)

		result.append(
			{
				"item_code": row.item_code,
				"buildable_qty": buildable,
				"pending_qty": flt(row.pending_qty),
				"limiting_item": limiting,
			}
		)

	return result


def run_daily_can_build():
	"""Scheduled: refresh the Can Build Log for every company."""
	if not is_enabled("enable_can_build"):
		return

	stamp = now_datetime()
	for company in frappe.get_all("Company", filters={"is_group": 0}, pluck="name"):
		try:
			rows = calculate(company)
		except Exception:
			frappe.log_error(title=f"Can Build failed for {company}", message=frappe.get_traceback())
			continue

		frappe.db.delete("Can Build Log", {"company": company})
		for row in rows:
			frappe.get_doc(dict(doctype="Can Build Log", company=company, calculated_on=stamp, **row)).insert(
				ignore_permissions=True
			)

		frappe.db.commit()
