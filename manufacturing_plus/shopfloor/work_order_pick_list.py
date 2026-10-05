# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Create a Pick List from a Work Order, for what the stock can actually cover.

Core maps every outstanding Work Order Item straight onto a Pick List at its full
remaining qty, in whatever warehouse the row happens to name. When the stock is not there
the Pick List cannot be transferred, and nothing on screen tells you which component is
holding the order up.

This is the flow the Kaynes app uses instead:

* **Free stock is what no one else is waiting for** — on hand, less what other open Work
  Orders still owe on the same component. Nothing is promised twice.
* **The order's real capacity is its tightest component.** Each component is picked up to
  the lower of what it still needs and what is free, so a short component never stops the
  rest of the order being picked.
* **A partial pick is a normal outcome.** What cannot be picked now is left outstanding for
  a later Pick List, and the reason is reported per component.
* **Batch items are allocated earliest expiry first**, through the core allocator, so
  batches already picked on another draft Pick List are left alone.
* **One draft at a time.** A Work Order that already has a draft Pick List cannot start a
  second one, otherwise the same stock is picked twice over.
* The Pick List is saved as a **draft** with ``pick_manually`` set, so core does not
  recalculate the locations this flow worked out.

The first Pick List for an order carries the full Work Order qty in ``for_qty``, which is
the manufacturing intent; later ones carry 0, because core adds ``for_qty`` up across Pick
Lists and would otherwise refuse them as over-production.
"""

import math

import frappe
from frappe import _
from frappe.utils import cint, flt

from manufacturing_plus.planning.settings import is_enabled, setting
from manufacturing_plus.planning.stock import get_excluded_warehouses

CLOSED_WO_STATUS = ("Completed", "Stopped", "Closed")


@frappe.whitelist()
def get_draft_pick_list(work_order: str) -> dict:
	"""The draft Pick List this order already has, if any."""
	frappe.has_permission("Work Order", "read", throw=True)

	name = frappe.db.get_value("Pick List", {"work_order": work_order, "docstatus": 0}, "name")
	return {"pick_list": name}


@frappe.whitelist()
def get_pick_list_preview(work_order: str, for_qty: float | None = None) -> dict:
	"""What could be picked right now, and what is in the way. Reads only."""
	frappe.has_permission("Work Order", "read", throw=True)

	wo = frappe.get_doc("Work Order", work_order)
	plan = build_plan(wo, for_qty)

	return {
		"work_order": wo.name,
		"production_item": wo.production_item,
		"qty": flt(wo.qty),
		"produced_qty": flt(wo.produced_qty),
		"requested_qty": plan["requested_qty"],
		"component_capacity": plan["component_capacity"],
		"rows": plan["rows"],
		"draft_pick_list": get_draft_pick_list(work_order)["pick_list"],
	}


@frappe.whitelist()
def create_pick_list(work_order: str, for_qty: float | None = None) -> dict:
	"""Create the draft Pick List for the pickable part of the order."""
	frappe.has_permission("Pick List", "create", throw=True)

	wo = frappe.get_doc("Work Order", work_order)
	if wo.docstatus != 1:
		frappe.throw(_("Work Order {0} is not submitted.").format(frappe.bold(wo.name)))

	existing = get_draft_pick_list(work_order)["pick_list"]
	if existing:
		frappe.throw(
			_("Work Order {0} already has a draft Pick List: {1}.").format(
				frappe.bold(wo.name), frappe.bold(existing)
			)
			+ "<br><br>"
			+ _("Submit or delete it before picking again."),
			title=_("Draft Pick List Open"),
		)

	plan = build_plan(wo, for_qty)
	if not plan["rows"]:
		return {"ok": False, "reason": _("Nothing is outstanding on this Work Order."), "issues": []}

	pick_list = frappe.new_doc("Pick List")
	pick_list.company = wo.company
	pick_list.purpose = "Material Transfer for Manufacture"
	pick_list.work_order = wo.name
	pick_list.pick_manually = 1
	pick_list.for_qty = first_pick_list_qty(wo)

	issues, warnings = [], []
	for row in plan["rows"]:
		added = add_locations(pick_list, wo, row, warnings)
		if not added:
			issues.append(row["reason"] or _("{0}: no free stock.").format(row["item_code"]))

	if not pick_list.get("locations"):
		return {
			"ok": False,
			"reason": _("No component has free stock, so there is nothing to pick yet."),
			"issues": issues,
		}

	pick_list.insert()

	return {
		"ok": True,
		"pick_list": pick_list.name,
		"issues": issues,
		"warnings": warnings,
		"picked_items": len({row.item_code for row in pick_list.locations}),
	}


def build_plan(wo, for_qty=None) -> dict:
	"""Per outstanding component: on hand, held by others, free, and what can be picked."""
	components = outstanding_components(wo)
	requested_qty = flt(for_qty) if for_qty else flt(wo.qty)

	if not components:
		return {"rows": [], "requested_qty": requested_qty, "component_capacity": 0.0}

	item_codes = sorted({row["item_code"] for row in components})
	warehouses = eligible_warehouses(wo.company)
	on_hand = warehouse_stock(item_codes, warehouses)
	held = reserved_by_other_orders(item_codes, wo.name)
	expired = expired_stock(item_codes, warehouses)

	rows = []
	for component in components:
		item_code = component["item_code"]
		by_warehouse = on_hand.get(item_code) or {}
		total_on_hand = sum(by_warehouse.values())
		held_qty = flt(held.get(item_code))
		free_qty = max(total_on_hand - held_qty, 0.0)
		pickable = min(component["outstanding_qty"], free_qty)

		per_unit = component["per_unit"]
		capacity = math.floor(free_qty / per_unit) if per_unit > 0 else requested_qty

		component.update(
			{
				"on_hand_qty": total_on_hand,
				"held_by_others_qty": held_qty,
				"free_qty": free_qty,
				"pickable_qty": pickable,
				"expired_qty": flt(expired.get(item_code)),
				"fg_capacity": min(requested_qty, flt(capacity)),
				"by_warehouse": by_warehouse,
				"reason": shortfall_reason(component, total_on_hand, held_qty, free_qty, wo.name),
			}
		)
		rows.append(component)

	capacity = min((row["fg_capacity"] for row in rows), default=0.0)
	return {"rows": rows, "requested_qty": requested_qty, "component_capacity": flt(capacity)}


def outstanding_components(wo) -> list[dict]:
	components = []
	for row in wo.required_items:
		outstanding = flt(row.required_qty) - flt(row.transferred_qty)
		if outstanding <= 0:
			continue

		components.append(
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"required_qty": flt(row.required_qty),
				"transferred_qty": flt(row.transferred_qty),
				"outstanding_qty": outstanding,
				"per_unit": flt(row.required_qty) / flt(wo.qty) if flt(wo.qty) else 0.0,
				"source_warehouse": (row.source_warehouse or "").strip(),
				"operation": row.operation,
				"stock_uom": row.stock_uom,
			}
		)

	return components


def eligible_warehouses(company: str) -> list[str]:
	"""Company warehouses a pick may draw on, minus the ones the settings exclude."""
	filters = {"company": company, "is_group": 0, "disabled": 0}
	if frappe.db.has_column("Warehouse", "is_rejected_warehouse"):
		filters["is_rejected_warehouse"] = 0

	excluded = set(get_excluded_warehouses())
	return [
		name for name in frappe.get_all("Warehouse", filters=filters, pluck="name") if name not in excluded
	]


def warehouse_stock(item_codes: list[str], warehouses: list[str]) -> dict:
	"""{item_code: {warehouse: actual qty}} — on hand, before anything is held back."""
	if not warehouses:
		return {}

	rows = frappe.db.sql(
		"""
		select item_code, warehouse, sum(ifnull(actual_qty, 0)) as qty
		from `tabBin`
		where item_code in %(items)s and warehouse in %(warehouses)s
		group by item_code, warehouse
		having qty > 0
		""",
		{"items": item_codes, "warehouses": warehouses},
		as_dict=True,
	)

	stock: dict[str, dict] = {}
	for row in rows:
		stock.setdefault(row.item_code, {})[row.warehouse] = flt(row.qty)

	return stock


def reserved_by_other_orders(item_codes: list[str], work_order: str) -> dict:
	"""What other open Work Orders still owe on these components.

	A submitted Work Order that has not had its material transferred is a standing claim on
	the stock. Counting it keeps two orders from being promised the same component.
	"""
	if not cint(setting("pick_list_respect_other_orders", 1)):
		return {}

	rows = frappe.db.sql(
		"""
		select woi.item_code, sum(woi.required_qty - ifnull(woi.transferred_qty, 0)) as qty
		from `tabWork Order Item` woi
		inner join `tabWork Order` wo on wo.name = woi.parent
		where woi.item_code in %(items)s
		  and wo.docstatus = 1
		  and wo.name != %(work_order)s
		  and wo.status not in %(closed)s
		  and woi.required_qty > ifnull(woi.transferred_qty, 0)
		group by woi.item_code
		""",
		{"items": item_codes, "work_order": work_order, "closed": CLOSED_WO_STATUS},
		as_dict=True,
	)
	return {row.item_code: flt(row.qty) for row in rows}


def expired_stock(item_codes: list[str], warehouses: list[str]) -> dict:
	"""Qty sitting in batches that are past their expiry date — stock you cannot use."""
	if not warehouses:
		return {}

	rows = frappe.db.sql(
		"""
		select sle.item_code, sum(entry.qty) as qty
		from `tabStock Ledger Entry` sle
		inner join `tabSerial and Batch Entry` entry on entry.parent = sle.serial_and_batch_bundle
		inner join `tabBatch` batch on batch.name = entry.batch_no
		where sle.item_code in %(items)s and sle.warehouse in %(warehouses)s
		  and sle.is_cancelled = 0
		  and batch.expiry_date is not null and batch.expiry_date < curdate()
		group by sle.item_code
		having qty > 0
		""",
		{"items": item_codes, "warehouses": warehouses},
		as_dict=True,
	)
	return {row.item_code: flt(row.qty) for row in rows}


def shortfall_reason(component, on_hand, held, free, work_order) -> str | None:
	"""Plain words for why a component cannot be picked in full."""
	if component["outstanding_qty"] <= free:
		return None

	if on_hand <= 0:
		return _("{0}: no stock in any warehouse.").format(component["item_code"])

	if free <= 0 and held > 0:
		others = other_order_names(component["item_code"], work_order)
		return _("{0}: all {1} on hand is owed to other Work Orders ({2}).").format(
			component["item_code"], on_hand, ", ".join(others) or _("other orders")
		)

	return _("{0}: needs {1}, only {2} free of {3} on hand.").format(
		component["item_code"], component["outstanding_qty"], free, on_hand
	)


def other_order_names(item_code: str, work_order: str, limit: int = 5) -> list[str]:
	rows = frappe.db.sql(
		"""
		select distinct wo.name
		from `tabWork Order Item` woi
		inner join `tabWork Order` wo on wo.name = woi.parent
		where woi.item_code = %(item_code)s and wo.docstatus = 1 and wo.name != %(work_order)s
		  and wo.status not in %(closed)s and woi.required_qty > ifnull(woi.transferred_qty, 0)
		order by wo.name
		limit %(limit)s
		""",
		{
			"item_code": item_code,
			"work_order": work_order,
			"closed": CLOSED_WO_STATUS,
			"limit": limit,
		},
	)
	return [row[0] for row in rows]


def first_pick_list_qty(wo) -> float:
	"""The first Pick List carries the whole order; later ones carry nothing.

	Core adds for_qty up over a Work Order's Pick Lists and refuses the total above the
	order qty, so a second Pick List with a qty of its own would be rejected as
	over-production even when it only picks what the first one could not.
	"""
	already = frappe.db.count("Pick List", {"work_order": wo.name, "docstatus": ["<", 2]})
	return flt(wo.qty) if not already else 0.0


def add_locations(pick_list, wo, component, warnings: list) -> float:
	"""Fill the component from its warehouses, nearest source first. Returns the qty added."""
	remaining = component["pickable_qty"]
	if remaining <= 0:
		return 0.0

	added = 0.0
	for warehouse, available in warehouse_order(component, wo):
		if remaining <= 0:
			break

		take = min(remaining, available)
		if take <= 0:
			continue

		added += append_location(pick_list, wo, component, warehouse, take, warnings)
		remaining -= take

	return added


def warehouse_order(component, wo) -> list[tuple]:
	"""The row's own warehouse first, then the order's, then the fullest of the rest."""
	by_warehouse = dict(component["by_warehouse"])
	ordered, seen = [], set()

	for preferred in (component["source_warehouse"], (wo.source_warehouse or "").strip()):
		if preferred and preferred in by_warehouse and preferred not in seen:
			ordered.append((preferred, by_warehouse[preferred]))
			seen.add(preferred)

	# a row that names its own warehouse is picked from there and nowhere else
	if component["source_warehouse"]:
		return ordered

	rest = [(name, qty) for name, qty in by_warehouse.items() if name not in seen]
	rest.sort(key=lambda row: row[1], reverse=True)
	return ordered + rest


def append_location(pick_list, wo, component, warehouse: str, qty: float, warnings: list) -> float:
	"""One row per batch for a batch item, otherwise a single row."""
	values = {
		"item_code": component["item_code"],
		"item_name": component["item_name"],
		"warehouse": warehouse,
		"uom": component["stock_uom"],
		"stock_uom": component["stock_uom"],
		"conversion_factor": 1,
	}

	for batch_no, batch_qty in batch_allocation(component["item_code"], warehouse, qty, warnings):
		row = dict(values, qty=flt(batch_qty), stock_qty=flt(batch_qty))
		if batch_no:
			row.update({"batch_no": batch_no, "use_serial_batch_fields": 1})
		pick_list.append("locations", row)

	return qty


def batch_allocation(item_code: str, warehouse: str, qty: float, warnings: list) -> list[tuple]:
	"""Earliest expiry first, through the core allocator. [(batch_no | None, qty)]."""
	if not frappe.get_cached_value("Item", item_code, "has_batch_no"):
		return [(None, qty)]

	if not is_enabled("pick_list_fefo_batches"):
		return [(None, qty)]

	from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import get_auto_batch_nos

	batches = get_auto_batch_nos(
		frappe._dict(
			{
				"item_code": item_code,
				"warehouse": warehouse,
				"qty": qty,
				"based_on": "Expiry",
				"is_pick_list": 1,
			}
		)
	)

	allocation = [
		(row.get("batch_no"), flt(row.get("qty"))) for row in batches or [] if flt(row.get("qty")) > 0
	]
	allocated = sum(row[1] for row in allocation)

	if allocated < qty:
		# the rest has no batch the allocator will give us: the picker chooses it by hand
		allocation.append((None, qty - allocated))
		warnings.append(
			_(
				"{0}: {1} in {2} has no batch available — choose one on the Pick List before submitting."
			).format(item_code, qty - allocated, warehouse)
		)

	return allocation
