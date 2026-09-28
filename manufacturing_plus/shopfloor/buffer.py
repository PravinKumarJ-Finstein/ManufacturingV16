# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Pick List buffer: extra qty issued per package slab, charged once per Work Order."""

import frappe
from frappe.utils import cint, flt

from manufacturing_plus.planning.settings import is_enabled


@frappe.request_cache
def get_item_package(item_code: str) -> str | None:
	return frappe.db.get_value("Item", item_code, "mp_package")


@frappe.request_cache
def get_slabs(package: str) -> tuple:
	if not package:
		return tuple()

	rows = frappe.db.sql(
		"""
		select d.from_quantity, d.to_quantity, d.extra_quantity
		from `tabPick List Configuration Detail` d
		inner join `tabPick List Configuration` c on c.name = d.parent
		where c.package = %s and ifnull(c.disabled, 0) = 0
		order by d.idx
		""",
		package,
	)
	return tuple(rows)


def get_buffer_qty(item_code: str, qty_per_work_order: float, work_orders: int = 1) -> float:
	"""Extra qty for this component: the first matching slab, once per Work Order."""
	if not is_enabled("enable_pick_list_buffer") or flt(qty_per_work_order) <= 0:
		return 0.0

	slabs = get_slabs(get_item_package(item_code))
	if not slabs:
		return 0.0

	for from_qty, to_qty, extra_qty in slabs:
		if flt(from_qty) <= flt(qty_per_work_order) <= flt(to_qty):
			return flt(extra_qty) * max(cint(work_orders), 1)

	return 0.0
