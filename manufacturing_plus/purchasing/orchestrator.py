# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""On Sales Order submit: MPS -> reservation -> shortage -> Material Request -> Purchase Order."""

import frappe
from frappe import _
from frappe.utils import (
	add_days,
	cint,
	flt,
	get_first_day,
	get_last_day,
	getdate,
	now_datetime,
	nowdate,
)

from manufacturing_plus.planning.expected_delivery import get_default_bom
from manufacturing_plus.planning.lead_time import get_item_lead_days, get_rm_shortage
from manufacturing_plus.planning.settings import is_enabled, setting
from manufacturing_plus.purchasing import reservation, sourcing

TOLERANCE = 1e-6


def demand_key(sales_order_item: str, item_code: str) -> str:
	return f"{sales_order_item}::{item_code}"


@frappe.whitelist()
def rerun(run_name: str) -> str:
	"""Pick up where a failed or partly finished run stopped, on the same run document.

	No second run is opened: this one is updated. Nothing is done twice either — the MPS is
	reused, demand rows already ordered are left alone, an item that still has a live
	Material Request line is skipped, and the stock this MPS reserved is not reserved again.
	"""
	run = frappe.get_doc("Auto Purchase Run", run_name)
	if not run.sales_order:
		frappe.throw(_("This run has no Sales Order to repeat."))

	if frappe.db.get_value("Sales Order", run.sales_order, "docstatus") != 1:
		frappe.throw(_("Sales Order {0} is not submitted.").format(run.sales_order))

	so = frappe.get_doc("Sales Order", run.sales_order)
	# written straight to the database: _execute reloads the document further down
	run.db_set("attempts", cint(run.attempts) + 1, update_modified=False)
	_execute(run, so)
	return run.name


@frappe.whitelist()
def run_for_sales_order(sales_order: str, trigger: str = "SO Submit") -> str | None:
	"""First run for a Sales Order: open the log, then do the work."""
	if not is_enabled("enable_auto_purchase"):
		return None

	so = frappe.get_doc("Sales Order", sales_order)
	existing = frappe.db.get_value("Auto Purchase Run", {"sales_order": so.name}, "name")
	if existing:
		# a repeat of the same order updates the run it already has
		return rerun(existing)

	run = frappe.get_doc(
		{
			"doctype": "Auto Purchase Run",
			"company": so.company,
			"trigger": trigger,
			"sales_order": so.name,
			"status": "Queued",
			"attempts": 1,
		}
	).insert(ignore_permissions=True)

	_execute(run, so)
	return run.name


def _execute(run, so) -> None:
	"""The work itself, against an existing run document."""
	run.db_set(
		{"status": "In Progress", "started_on": now_datetime(), "error_log": None},
		update_modified=False,
	)

	notes = []

	try:
		mps = run.master_production_schedule
		if mps and not frappe.db.exists("Master Production Schedule", mps):
			# the plan was deleted after the run: make a fresh one below
			mps = None

		if not mps and is_enabled("create_mps_on_so_submit"):
			mps = create_mps(so)
			if not mps:
				notes.append(_no_mps_reason(so))

		if mps:
			run.db_set("master_production_schedule", mps, update_modified=False)
			frappe.db.set_value(
				"Master Production Schedule", mps, "mp_auto_purchase_run", run.name, update_modified=False
			)

		demands = build_demand(so, run.name, mps)
		short = [d for d in demands if flt(d.get("short_qty")) > TOLERANCE]
		material_requests, exceptions = [], 0

		if short and is_enabled("create_material_request"):
			material_requests, exceptions = create_material_requests(so, short, run.name, mps)

		if material_requests and is_enabled("create_purchase_order"):
			create_purchase_orders(material_requests, run)

		_close_resolved_exceptions(so.name)
		_refresh_totals(run, so, exceptions)

		if notes:
			run.db_set("error_log", "\n".join(notes), update_modified=False)
	except Exception:
		run.reload()
		run.status = "Failed"
		run.ended_on = now_datetime()
		run.last_run_on = now_datetime()
		run.error_log = frappe.get_traceback()
		run.save(ignore_permissions=True)
		frappe.log_error(title=f"Auto Purchase failed for {so.name}", message=frappe.get_traceback())


def _refresh_totals(run, so, exceptions: int) -> None:
	"""Counts always describe everything this run has produced, over all attempts."""
	run.reload()
	run.demand_rows = frappe.db.count("Sales Order Material Demand", {"run": run.name})
	run.mr_created = frappe.db.count("Material Request", {"mp_auto_purchase_run": run.name})
	run.po_count = frappe.db.count("Purchase Order", {"mp_auto_purchase_run": run.name})
	run.exception_count = frappe.db.count("Auto Purchase Exception", {"run": run.name, "status": "Open"})
	run.material_requests = ", ".join(
		frappe.get_all("Material Request", filters={"mp_auto_purchase_run": run.name}, pluck="name")
	)
	run.status = "Completed" if not run.exception_count else "Partially Completed"
	run.ended_on = now_datetime()
	run.last_run_on = now_datetime()
	run.save(ignore_permissions=True)


def create_mps(so) -> str | None:
	"""The plan for this Sales Order.

	Per Sales Order (default): every submitted order gets **its own new plan**. An order is
	never added to a plan that already exists for another order.

	Per Period: one shared plan per company and period, which every order of that period
	joins. That is what the core MRP report expects — it only leaves out the orders listed
	in the plan you filter on, so anything missing comes back as an "Ad-hoc" row and the
	same demand is counted twice. Use it only if you read that report.
	"""
	if setting("mps_mode", "Per Sales Order") == "Per Period":
		return _mps_for_period(so)

	return _mps_for_sales_order(so)


def _mps_for_sales_order(so) -> str | None:
	"""A plan of this order's own. Only a plan already made for **this** order is reused."""
	existing = frappe.db.get_value(
		"Master Production Schedule", {"mp_sales_order": so.name, "docstatus": ["<", 2]}, "name"
	)
	if existing:
		return existing

	delivery_dates = [getdate(i.delivery_date) for i in so.items if i.delivery_date]
	mps = frappe.new_doc("Master Production Schedule")
	mps.company = so.company
	mps.posting_date = nowdate()
	mps.from_date = min(getdate(so.transaction_date), getdate(nowdate()))
	mps.to_date = max(delivery_dates) if delivery_dates else add_days(getdate(nowdate()), 30)
	mps.mp_sales_order = so.name
	mps.mp_auto_created = 1
	mps.parent_warehouse = root_warehouse(so.company)

	_add_sales_order(mps, so)
	if not mps.get("items"):
		return None

	mps.flags.ignore_permissions = True
	# left as a draft on purpose: submit queues make_mrp, which v16.34.2 does not have
	mps.insert(ignore_permissions=True)
	return mps.name


def _no_mps_reason(so) -> str:
	"""Why no plan came out of this order — so a missing MPS is never silent."""
	if not is_enabled("create_mps_on_so_submit"):
		return _("No plan was made: Create MPS On SO Submit is off.")

	without_bom = [item.item_code for item in so.items if not get_default_bom(item.item_code)]
	if len(without_bom) == len(so.items):
		return _(
			"No plan was made: none of this order's items has a default BOM ({0}). "
			"A plan can only hold items that are manufactured."
		).format(", ".join(sorted(set(without_bom))))

	return _("No plan was made for this order.")


@frappe.request_cache
def root_warehouse(company: str) -> str | None:
	"""The company's top warehouse, e.g. "All Warehouses - KTD"."""
	return frappe.db.get_value(
		"Warehouse",
		{"company": company, "is_group": 1, "parent_warehouse": ["in", ("", None)]},
		"name",
	)


def period_bounds(date=None) -> tuple:
	"""(start, end, key) of the plan period this date falls in."""
	date = getdate(date or nowdate())
	if setting("mps_period", "Monthly") == "Weekly":
		start = add_days(date, -date.weekday())
		end = add_days(start, 6)
		return start, end, f"{start:%Y-W%V}"

	start = get_first_day(date)
	return start, get_last_day(date), f"{start:%Y-%m}"


def _mps_for_period(so) -> str | None:
	"""One plan per company and period, refreshed with every open Sales Order."""
	start, end, key = period_bounds(so.transaction_date)

	name = frappe.db.get_value(
		"Master Production Schedule",
		{"company": so.company, "mp_period_key": key, "docstatus": ["<", 2]},
		"name",
	)
	mps = (
		frappe.get_doc("Master Production Schedule", name)
		if name
		else frappe.new_doc("Master Production Schedule")
	)

	if not name:
		mps.company = so.company
		mps.posting_date = nowdate()
		mps.from_date = start
		mps.mp_period_key = key
		mps.mp_auto_created = 1
		mps.parent_warehouse = root_warehouse(so.company)

	for order in _open_sales_orders(so):
		_add_sales_order(mps, order)

	if not mps.get("items"):
		return None

	latest = max(getdate(row.delivery_date) for row in mps.items if row.delivery_date)
	horizon = add_days(getdate(start), cint(setting("plan_ahead_days", 365)) or 365)
	mps.to_date = min(max(getdate(end), latest), horizon)

	mps.flags.ignore_permissions = True
	mps.save(ignore_permissions=True)
	return mps.name


def _open_sales_orders(so) -> list:
	"""The order being submitted, and — only if asked — every other open one.

	Sweeping in the rest is what keeps the core MRP report free of "Ad-hoc" rows, but it
	makes a plan appear full of orders nobody just submitted, so it is off by default.
	"""
	if not is_enabled("plan_includes_open_orders"):
		return [so]

	names = frappe.get_all(
		"Sales Order",
		filters={
			"docstatus": 1,
			"company": so.company,
			"status": ["not in", ("Closed", "Completed", "Stopped")],
		},
		pluck="name",
	)
	ordered = [so.name] + [name for name in names if name != so.name]
	return [so if name == so.name else frappe.get_doc("Sales Order", name) for name in ordered]


def _add_sales_order(mps, so) -> None:
	"""Put the order in the plan's Sales Orders table and its lines in the items table."""
	if not any(row.sales_order == so.name for row in mps.get("sales_orders") or []):
		mps.append(
			"sales_orders",
			{
				"sales_order": so.name,
				"sales_order_date": so.transaction_date,
				"customer": so.customer,
				"grand_total": so.grand_total,
			},
		)

	for item in so.items:
		bom_no = get_default_bom(item.item_code)
		if not bom_no:
			continue

		planned_qty = flt(item.stock_qty) or flt(item.qty)
		existing = next(
			(
				row
				for row in mps.get("items") or []
				if row.item_code == item.item_code
				and getdate(row.delivery_date) == getdate(item.delivery_date)
			),
			None,
		)
		if existing:
			existing.planned_qty = max(flt(existing.planned_qty), planned_qty)
			continue

		mps.append(
			"items",
			{
				"item_code": item.item_code,
				"item_name": item.item_name,
				"warehouse": item.warehouse,
				"delivery_date": item.delivery_date,
				"planned_qty": planned_qty,
				"bom_no": bom_no,
				"uom": item.stock_uom or item.uom,
			},
		)

	_sync_select_items(mps)


def _sync_select_items(mps) -> None:
	"""Select Items mirrors the items actually planned, so Get Actual Demand has a list."""
	planned = {row.item_code for row in mps.get("items") or [] if row.item_code}
	chosen = {row.item_code for row in mps.get("select_items") or [] if row.item_code}

	for item_code in sorted(planned - chosen):
		mps.append("select_items", {"item_code": item_code})


def build_demand(so, run_name: str, mps: str | None) -> list[dict]:
	"""Per Sales Order line: explode the BOM, compare with free stock, store the demand rows."""
	demands, reserve_rows = [], []

	for item in so.items:
		bom_no = get_default_bom(item.item_code)
		if not bom_no:
			continue

		stock_qty = flt(item.stock_qty) or flt(item.qty)
		shortage = get_rm_shortage(bom_no, stock_qty, so.company, item.warehouse, None, so.name)

		for component in shortage["components"]:
			key = demand_key(item.name, component["item_code"])
			short_qty = flt(component.get("short_qty"))
			lead_days = cint(component.get("lead_time_days")) or get_item_lead_days(
				component["item_code"], so.company
			)

			values = {
				"doctype": "Sales Order Material Demand",
				"demand_key": key,
				"company": so.company,
				"sales_order": so.name,
				"sales_order_item": item.name,
				"fg_item_code": item.item_code,
				"bom_no": bom_no,
				"delivery_date": item.delivery_date,
				"item_code": component["item_code"],
				"required_qty": flt(component["required_qty"]),
				"available_qty": flt(component.get("available_qty")),
				"short_qty": short_qty,
				"lead_time_days": lead_days,
				"required_by_date": sourcing.required_by_date(item.delivery_date, lead_days)
				if item.delivery_date
				else nowdate(),
				"status": "Short" if short_qty > TOLERANCE else "In Stock",
				"run": run_name,
				"master_production_schedule": mps,
			}

			existing = frappe.db.get_value("Sales Order Material Demand", {"demand_key": key}, "name")
			if existing:
				doc = frappe.get_doc("Sales Order Material Demand", existing)
				if doc.status in ("Ordered", "Partially Ordered", "Received"):
					continue
				doc.update({k: v for k, v in values.items() if k != "doctype"})
				doc.save(ignore_permissions=True)
			else:
				doc = frappe.get_doc(values).insert(ignore_permissions=True)

			demands.append(doc.as_dict())

			taken = min(flt(component["required_qty"]), flt(component.get("available_qty")))
			if taken > TOLERANCE:
				reserve_rows.append(
					{
						"item_code": component["item_code"],
						"warehouse": item.warehouse,
						"qty": taken,
						"sales_order_item": item.name,
					}
				)

	if mps and reserve_rows:
		reservation.reserve_for_mps(mps, so.company, reserve_rows, so.name)

	return demands


def create_material_requests(
	so, short: list[dict], run_name: str, mps: str | None = None
) -> tuple[list[str], int]:
	"""One draft Material Request (Purchase) with a line per short (SO line + item)."""
	excluded_groups = _excluded_item_groups()
	lines, exceptions = [], 0

	for demand in short:
		item_code = demand["item_code"]
		if _already_requested(demand["demand_key"]):
			continue

		if excluded_groups and frappe.db.get_value("Item", item_code, "item_group") in excluded_groups:
			continue

		params = sourcing.get_purchase_params(item_code, so.company)
		supplier = sourcing.get_supplier(item_code, so.company)
		qty = sourcing.round_qty(demand["short_qty"], params)
		threshold = sourcing.get_class_threshold(item_code)

		if (
			threshold
			and params["min_order_qty"]
			and flt(demand["short_qty"]) < flt(params["min_order_qty"]) * threshold
		):
			_raise_exception(
				run_name,
				so,
				demand,
				"Below MOQ Threshold",
				_("Short qty {0} is below MOQ {1} x threshold {2}").format(
					demand["short_qty"], params["min_order_qty"], threshold
				),
			)
			exceptions += 1
			continue

		if not supplier:
			_raise_exception(run_name, so, demand, "No Supplier", _("No default supplier for this item"))
			exceptions += 1
			continue

		rate = sourcing.get_rate(item_code, supplier, so.company)
		if rate is None:
			_raise_exception(run_name, so, demand, "No Price", _("No buying Item Price for this supplier"))
			exceptions += 1
			continue

		lines.append(
			{
				"demand": demand,
				"item_code": item_code,
				"qty": qty,
				"rate": rate,
				"supplier": supplier,
				"schedule_date": demand.get("required_by_date") or nowdate(),
				"warehouse": frappe.db.get_value(
					"Item Default", {"parent": item_code, "company": so.company}, "default_warehouse"
				),
			}
		)

	if not lines:
		return [], exceptions

	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Purchase"
	mr.company = so.company
	mr.transaction_date = nowdate()
	mr.schedule_date = min(getdate(line["schedule_date"]) for line in lines)
	mr.mp_auto_purchase_run = run_name
	mr.mp_master_production_schedule = mps

	for line in lines:
		demand = line["demand"]
		mr.append(
			"items",
			{
				"item_code": line["item_code"],
				"qty": line["qty"],
				"schedule_date": line["schedule_date"],
				"warehouse": line["warehouse"],
				"rate": line["rate"],
				"mp_so_reference": so.name,
				"mp_so_line": demand["sales_order_item"],
				"mp_fg_item_code": demand.get("fg_item_code"),
				"mp_demand_key": demand["demand_key"],
			},
		)

	mr.flags.ignore_permissions = True
	mr.insert(ignore_permissions=True)
	mr.submit()

	for row, line in zip(mr.items, lines, strict=False):
		frappe.db.set_value(
			"Sales Order Material Demand",
			{"demand_key": line["demand"]["demand_key"]},
			{"material_request": mr.name, "material_request_item": row.name},
			update_modified=False,
		)

	return [mr.name], exceptions


def create_purchase_orders(material_requests: list[str], run) -> list[str]:
	"""One draft Purchase Order per supplier, built from the Material Request lines."""
	created = []

	for mr_name in material_requests:
		mr = frappe.get_doc("Material Request", mr_name)
		by_supplier: dict[str, list] = {}

		for row in mr.items:
			supplier = sourcing.get_supplier(row.item_code, mr.company)
			if supplier:
				by_supplier.setdefault(supplier, []).append(row)

		for supplier, rows in by_supplier.items():
			po = frappe.new_doc("Purchase Order")
			po.supplier = supplier
			po.company = mr.company
			po.transaction_date = nowdate()
			po.schedule_date = min(getdate(r.schedule_date) for r in rows)
			po.mp_auto_purchase_run = run.name
			po.mp_master_production_schedule = mr.get("mp_master_production_schedule")
			po.mp_auto_purchased = 1

			for row in rows:
				lead_days = cint(
					frappe.db.get_value(
						"Sales Order Material Demand", {"demand_key": row.mp_demand_key}, "lead_time_days"
					)
				)
				schedule_date = max(
					getdate(row.schedule_date), getdate(sourcing.earliest_possible_receipt(lead_days))
				)
				po.append(
					"items",
					{
						"item_code": row.item_code,
						"qty": row.qty,
						"rate": row.rate,
						"schedule_date": schedule_date,
						"warehouse": row.warehouse,
						"material_request": mr.name,
						"material_request_item": row.name,
						"mp_so_reference": row.mp_so_reference,
						"mp_so_line": row.mp_so_line,
						"mp_demand_key": row.mp_demand_key,
					},
				)

			po.flags.ignore_permissions = True
			po.insert(ignore_permissions=True)

			limit = flt(setting("auto_submit_limit_amount", 0))
			if is_enabled("auto_submit_purchase_order") and (not limit or flt(po.grand_total) <= limit):
				po.submit()

			created.append(po.name)
			frappe.get_doc(
				{
					"doctype": "MP Auto Purchase Run PO",
					"parent": run.name,
					"parenttype": "Auto Purchase Run",
					"parentfield": "purchase_orders",
					"purchase_order": po.name,
					"supplier": supplier,
					"amount": po.grand_total,
					"po_status": "Submitted" if po.docstatus == 1 else "Draft",
				}
			).insert(ignore_permissions=True)

			for row in po.items:
				frappe.db.set_value(
					"Sales Order Material Demand",
					{"demand_key": row.mp_demand_key},
					{
						"purchase_order": po.name,
						"purchase_order_item": row.name,
						"ordered_qty": row.qty,
						"expected_receipt_date": row.schedule_date,
						"status": "Ordered",
					},
					update_modified=False,
				)

	return created


def _close_resolved_exceptions(sales_order: str) -> None:
	"""An exception whose demand row has since been ordered is no longer open."""
	rows = frappe.get_all(
		"Auto Purchase Exception",
		filters={"sales_order": sales_order, "status": "Open"},
		fields=["name", "sales_order_item", "item_code"],
	)
	for row in rows:
		status = frappe.db.get_value(
			"Sales Order Material Demand",
			{"sales_order_item": row.sales_order_item, "item_code": row.item_code},
			"status",
		)
		if status in ("Ordered", "Partially Ordered", "Received", "In Stock"):
			frappe.db.set_value(
				"Auto Purchase Exception", row.name, "status", "Resolved", update_modified=False
			)


def _already_requested(key: str) -> bool:
	name = frappe.db.get_value("Material Request Item", {"mp_demand_key": key}, "parent")
	if not name:
		return False

	return cint(frappe.db.get_value("Material Request", name, "docstatus")) < 2


def _excluded_item_groups() -> set:
	try:
		rows = frappe.get_cached_doc("Manufacturing Control Setting").get("excluded_item_groups") or []
	except Exception:
		return set()
	return {r.item_group for r in rows if r.item_group}


def _raise_exception(run_name: str, so, demand: dict, exception_type: str, reason: str) -> None:
	frappe.get_doc(
		{
			"doctype": "Auto Purchase Exception",
			"run": run_name,
			"master_production_schedule": frappe.db.get_value(
				"Auto Purchase Run", run_name, "master_production_schedule"
			),
			"company": so.company,
			"item_code": demand["item_code"],
			"sales_order": so.name,
			"sales_order_item": demand["sales_order_item"],
			"required_qty": demand["short_qty"],
			"exception_type": exception_type,
			"reason": reason,
			"status": "Open",
		}
	).insert(ignore_permissions=True)

	frappe.db.set_value(
		"Sales Order Material Demand",
		{"demand_key": demand["demand_key"]},
		{"status": "Exception"},
		update_modified=False,
	)
