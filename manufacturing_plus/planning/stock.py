# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Free stock: on hand, less reservations, less what earlier open orders and other MPS hold."""

import frappe
from frappe.utils import cint, flt

from manufacturing_plus.planning.settings import get_settings, setting


@frappe.request_cache
def get_excluded_warehouses() -> tuple:
	try:
		rows = get_settings().get("excluded_warehouses") or []
	except Exception:
		return tuple()
	return tuple(r.warehouse for r in rows if r.warehouse)


def _warehouse_filter(company: str | None, warehouse: str | None) -> tuple[str, dict]:
	scope = setting("stock_scope", "Company Warehouses")
	conditions = ["w.is_group = 0", "ifnull(w.disabled, 0) = 0"]
	values: dict = {}

	if scope == "Sales Order Item Warehouse" and warehouse:
		lft, rgt = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"]) or (None, None)
		if lft is not None:
			conditions.append("w.lft >= %(lft)s and w.rgt <= %(rgt)s")
			values.update({"lft": lft, "rgt": rgt})
	elif scope == "Company Warehouses" and company:
		conditions.append("w.company = %(company)s")
		values["company"] = company

	excluded = get_excluded_warehouses()
	if excluded:
		conditions.append("w.name not in %(excluded)s")
		values["excluded"] = list(excluded)

	return " and ".join(conditions), values


def get_bin_qty(items: list[str], company: str | None = None, warehouse: str | None = None) -> dict:
	"""{item_code: on-hand qty less Bin reservations}."""
	if not items:
		return {}

	condition, values = _warehouse_filter(company, warehouse)
	values["items"] = items
	reserved = (
		"- ifnull(b.reserved_qty, 0) - ifnull(b.reserved_qty_for_production, 0)"
		" - ifnull(b.reserved_qty_for_sub_contract, 0)"
		if cint(setting("subtract_reserved_qty", 1))
		else ""
	)

	rows = frappe.db.sql(
		f"""
		select b.item_code, sum(ifnull(b.actual_qty, 0) {reserved}) as qty
		from `tabBin` b
		inner join `tabWarehouse` w on w.name = b.warehouse
		where b.item_code in %(items)s and {condition}
		group by b.item_code
		""",
		values,
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


def get_mps_reserved_qty(
	items: list[str], company: str | None = None, exclude_sales_order: str | None = None
) -> dict:
	"""Qty held by **other** orders' plans.

	A reservation this same Sales Order made is its own hold, not a competitor's: counting
	it would make the order look short of stock it is already holding for itself.
	"""
	if not items or not cint(setting("reserve_stock_on_mps", 1)):
		return {}

	values = {"items": items}
	condition = ""
	if company:
		condition = "and company = %(company)s"
		values["company"] = company

	if exclude_sales_order:
		condition += " and ifnull(sales_order, '') != %(exclude_so)s"
		values["exclude_so"] = exclude_sales_order

	rows = frappe.db.sql(
		f"""
		select item_code, sum(reserved_qty) as qty
		from `tabMPS Stock Reservation`
		where status = 'Active' and item_code in %(items)s {condition}
		group by item_code
		""",
		values,
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


def get_committed_qty(
	items: list[str], company: str | None = None, before_date=None, exclude_sales_order: str | None = None
) -> dict:
	"""Qty of these raw materials already needed by earlier open Sales Order lines."""
	if not items or not cint(setting("net_off_earlier_orders", 1)):
		return {}

	values = {"items": items}
	conditions = [
		"so.docstatus = 1",
		"so.status not in ('Closed', 'Completed', 'Stopped')",
		"soi.qty > ifnull(soi.delivered_qty, 0)",
	]
	if company:
		conditions.append("so.company = %(company)s")
		values["company"] = company
	if before_date:
		conditions.append("soi.delivery_date <= %(before_date)s")
		values["before_date"] = before_date
	if exclude_sales_order:
		conditions.append("so.name != %(exclude_so)s")
		values["exclude_so"] = exclude_sales_order

	# An order whose MPS already reserved its stock is counted by the reservation ledger;
	# counting it here as well would deduct the same quantity twice.
	conditions.append(
		"""so.name not in (
			select distinct r.sales_order from `tabMPS Stock Reservation` r
			where r.status = 'Active' and ifnull(r.sales_order, '') != ''
		)"""
	)

	rows = frappe.db.sql(
		f"""
		select bei.item_code,
		       sum(bei.qty_consumed_per_unit * (soi.stock_qty - ifnull(soi.delivered_qty, 0) * ifnull(soi.conversion_factor, 1))) as qty
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		inner join `tabItem` i on i.name = soi.item_code and ifnull(i.default_bom, '') != ''
		inner join `tabBOM Explosion Item` bei on bei.parent = i.default_bom
		     and ifnull(bei.is_sub_assembly_item, 0) = 0
		where bei.item_code in %(items)s and {" and ".join(conditions)}
		group by bei.item_code
		""",
		values,
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


def get_free_qty(
	items: list[str],
	company: str | None = None,
	warehouse: str | None = None,
	before_date=None,
	exclude_sales_order: str | None = None,
) -> dict:
	"""On hand - Bin reservations - MPS reservations - earlier committed demand."""
	on_hand = get_bin_qty(items, company, warehouse)
	mps_reserved = get_mps_reserved_qty(items, company, exclude_sales_order)
	committed = get_committed_qty(items, company, before_date, exclude_sales_order)

	return {
		item: flt(on_hand.get(item, 0)) - flt(mps_reserved.get(item, 0)) - flt(committed.get(item, 0))
		for item in items
	}
