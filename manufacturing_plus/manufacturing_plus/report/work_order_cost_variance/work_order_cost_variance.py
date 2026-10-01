# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""What a Work Order was supposed to cost, against what it really cost.

The BOM holds one standard figure — so much material, so many minutes per operation. This
report puts that standard next to what actually happened: material issued against the Work
Order, time booked on its Job Cards, and the gap between the two, in money, in minutes and
as a percentage.

Where each figure comes from
----------------------------
Standard material   BOM.raw_material_cost / BOM.quantity, scaled to the costed qty.
                    Falls back to the Work Order's own required items (required_qty x rate)
                    when the BOM carries no cost.
Standard operation  Work Order.planned_operating_cost (hour rate x BOM time), scaled.
Standard time       Work Order Operation.time_in_mins, which core already scales to the
                    ordered qty, scaled again to the costed qty.
Actual material     Stock Entry Detail.amount of the lines issued against this Work Order
                    (purpose Manufacture or Material Consumption for Manufacture). Falls
                    back to consumed_qty x rate on the Work Order's required items.
Actual operation    Job Card time x hour rate, with Work Order.actual_operating_cost as the
                    fallback when no Job Card carries an hour rate.
Actual time         Job Card.total_time_in_mins, falling back to the operations' own
                    actual_operation_time.

The costed qty is the produced qty by default, so standard and actual describe the same
output. A Work Order that has produced nothing is costed on its ordered qty instead,
otherwise the standard would read zero and the whole actual cost would look like a
variance. The qty used is shown in its own column.
"""

import frappe
from frappe import _
from frappe.utils import flt

CONSUMPTION_PURPOSES = ("Manufacture", "Material Consumption for Manufacture")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	work_orders = get_work_orders(filters)
	if not work_orders:
		return get_columns(), []

	names = [row.name for row in work_orders]
	boms = get_bom_costs({row.bom_no for row in work_orders if row.bom_no})
	operations = get_operation_totals(names)
	job_cards = get_job_card_totals(names)
	consumed = get_consumed_material_cost(names)
	required = get_required_item_costs(names)
	currency = frappe.get_cached_value("Company", filters.company, "default_currency")

	rows = []
	for wo in work_orders:
		row = build_row(wo, filters, boms, operations, job_cards, consumed, required)
		row["currency"] = currency
		rows.append(row)

	if filters.get("only_variances"):
		rows = [r for r in rows if flt(r["total_variance"]) or flt(r["time_variance_mins"])]

	return get_columns(), rows


def get_work_orders(filters) -> list:
	conditions = ["wo.docstatus = 1", "wo.company = %(company)s"]
	values = {"company": filters.company}

	for field in ("work_order", "production_item", "bom_no", "sales_order", "status"):
		if not filters.get(field):
			continue
		column = "wo.name" if field == "work_order" else f"wo.{field}"
		conditions.append(f"{column} = %({field})s")
		values[field] = filters.get(field)

	if filters.get("from_date") and filters.get("to_date"):
		values.update({"from_date": filters.from_date, "to_date": filters.to_date})
		window = "date(wo.actual_end_date) between %(from_date)s and %(to_date)s"
		if filters.get("include_in_process"):
			# a Work Order still running has no completion date yet, so the window cannot judge it
			window = f"({window} or wo.actual_end_date is null)"
		conditions.append(window)
	elif not filters.get("include_in_process"):
		conditions.append("wo.actual_end_date is not null")

	return frappe.db.sql(
		f"""
		select wo.name, wo.status, wo.production_item, wo.item_name, wo.bom_no, wo.qty,
		       wo.produced_qty, wo.process_loss_qty, wo.stock_uom, wo.sales_order, wo.project,
		       wo.planned_operating_cost, wo.actual_operating_cost, wo.additional_operating_cost,
		       wo.corrective_operation_cost, wo.actual_start_date, wo.actual_end_date, wo.lead_time
		from `tabWork Order` wo
		where {" and ".join(conditions)}
		order by wo.actual_end_date desc, wo.name desc
		""",
		values,
		as_dict=True,
	)


def get_bom_costs(bom_nos: set) -> dict:
	if not bom_nos:
		return {}

	rows = frappe.get_all(
		"BOM",
		filters={"name": ["in", list(bom_nos)]},
		fields=["name", "quantity", "raw_material_cost", "operating_cost", "total_cost"],
	)
	return {row.name: row for row in rows}


def get_operation_totals(names: list) -> dict:
	"""Standard and actual minutes, and their costs, from the Work Order's own operations."""
	rows = frappe.db.sql(
		"""
		select parent,
		       sum(ifnull(time_in_mins, 0)) as standard_mins,
		       sum(ifnull(actual_operation_time, 0)) as actual_mins,
		       sum(ifnull(planned_operating_cost, 0)) as standard_cost,
		       sum(ifnull(actual_operating_cost, 0)) as actual_cost
		from `tabWork Order Operation`
		where parent in %(names)s
		group by parent
		""",
		{"names": names},
		as_dict=True,
	)
	return {row.parent: row for row in rows}


def get_job_card_totals(names: list) -> dict:
	"""What the shop floor actually booked: minutes, and those minutes priced at the hour rate."""
	rows = frappe.db.sql(
		"""
		select work_order,
		       sum(ifnull(total_time_in_mins, 0)) as actual_mins,
		       sum(ifnull(total_time_in_mins, 0) / 60.0 * ifnull(hour_rate, 0)) as actual_cost,
		       count(name) as job_cards
		from `tabJob Card`
		where docstatus = 1 and work_order in %(names)s
		group by work_order
		""",
		{"names": names},
		as_dict=True,
	)
	return {row.work_order: row for row in rows}


def get_consumed_material_cost(names: list) -> dict:
	"""Value of the material issued against the Work Order.

	Only the issue lines count: a line with a source warehouse and no target warehouse. The
	finished goods and scrap lines of the same Stock Entry are receipts, not consumption.
	"""
	rows = frappe.db.sql(
		"""
		select se.work_order,
		       sum(ifnull(sed.amount, 0)) as actual_cost,
		       count(distinct sed.item_code) as items
		from `tabStock Entry Detail` sed
		inner join `tabStock Entry` se on se.name = sed.parent
		where se.docstatus = 1 and se.work_order in %(names)s
		  and se.purpose in %(purposes)s
		  and ifnull(sed.s_warehouse, '') != '' and ifnull(sed.t_warehouse, '') = ''
		group by se.work_order
		""",
		{"names": names, "purposes": CONSUMPTION_PURPOSES},
		as_dict=True,
	)
	return {row.work_order: row for row in rows}


def get_required_item_costs(names: list) -> dict:
	"""The Work Order's own material plan, used when the BOM or the Stock Entries fall short."""
	rows = frappe.db.sql(
		"""
		select parent,
		       sum(ifnull(required_qty, 0) * ifnull(rate, 0)) as standard_cost,
		       sum(ifnull(consumed_qty, 0) * ifnull(rate, 0)) as actual_cost
		from `tabWork Order Item`
		where parent in %(names)s
		group by parent
		""",
		{"names": names},
		as_dict=True,
	)
	return {row.parent: row for row in rows}


def build_row(wo, filters, boms, operations, job_cards, consumed, required) -> dict:
	ordered_qty = flt(wo.qty)
	produced_qty = flt(wo.produced_qty)

	costed_qty = ordered_qty
	if filters.get("cost_basis", "Produced Qty") == "Produced Qty" and produced_qty > 0:
		costed_qty = produced_qty

	# everything the Work Order stores is for the ordered qty, so scale it to what we cost on
	scale = (costed_qty / ordered_qty) if ordered_qty else 1.0

	operation = operations.get(wo.name) or frappe._dict()
	job_card = job_cards.get(wo.name) or frappe._dict()
	plan = required.get(wo.name) or frappe._dict()
	bom = boms.get(wo.bom_no) or frappe._dict()

	standard_material = flt(plan.standard_cost) * scale
	if flt(bom.quantity) and flt(bom.raw_material_cost):
		standard_material = flt(bom.raw_material_cost) / flt(bom.quantity) * costed_qty

	standard_operation = flt(wo.planned_operating_cost) * scale
	if not standard_operation:
		standard_operation = flt(operation.standard_cost) * scale

	standard_mins = flt(operation.standard_mins) * scale

	actual_material = flt(consumed.get(wo.name, {}).get("actual_cost")) if consumed.get(wo.name) else 0.0
	if not actual_material:
		actual_material = flt(plan.actual_cost)

	actual_operation = flt(job_card.actual_cost)
	if not actual_operation:
		actual_operation = flt(wo.actual_operating_cost) or flt(operation.actual_cost)
	actual_operation += flt(wo.additional_operating_cost) + flt(wo.corrective_operation_cost)

	actual_mins = flt(job_card.actual_mins) or flt(operation.actual_mins)

	standard_total = standard_material + standard_operation
	actual_total = actual_material + actual_operation

	standard_unit = standard_total / costed_qty if costed_qty else 0.0
	actual_unit = actual_total / costed_qty if costed_qty else 0.0

	return {
		"work_order": wo.name,
		"status": wo.status,
		"completion_date": wo.actual_end_date,
		"production_item": wo.production_item,
		"item_name": wo.item_name,
		"bom_no": wo.bom_no,
		"sales_order": wo.sales_order,
		"qty": ordered_qty,
		"produced_qty": produced_qty,
		"process_loss_qty": flt(wo.process_loss_qty),
		"costed_qty": costed_qty,
		"standard_mins": standard_mins,
		"actual_mins": actual_mins,
		"time_variance_mins": actual_mins - standard_mins,
		"time_variance_percent": percent(actual_mins - standard_mins, standard_mins),
		"job_cards": flt(job_card.job_cards),
		"standard_material_cost": standard_material,
		"actual_material_cost": actual_material,
		"material_variance": actual_material - standard_material,
		"material_variance_percent": percent(actual_material - standard_material, standard_material),
		"standard_operation_cost": standard_operation,
		"actual_operation_cost": actual_operation,
		"operation_variance": actual_operation - standard_operation,
		"operation_variance_percent": percent(actual_operation - standard_operation, standard_operation),
		"standard_total_cost": standard_total,
		"actual_total_cost": actual_total,
		"total_variance": actual_total - standard_total,
		"variance_percent": percent(actual_total - standard_total, standard_total),
		"standard_cost_per_unit": standard_unit,
		"actual_cost_per_unit": actual_unit,
		"cost_per_unit_variance": actual_unit - standard_unit,
		"cost_per_unit_variance_percent": percent(actual_unit - standard_unit, standard_unit),
	}


def percent(difference: float, base: float) -> float:
	return flt(difference) / flt(base) * 100.0 if flt(base) else 0.0


def get_columns() -> list:
	return [
		{
			"label": _("Work Order"),
			"fieldname": "work_order",
			"fieldtype": "Link",
			"options": "Work Order",
			"width": 150,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{
			"label": _("Completion Date"),
			"fieldname": "completion_date",
			"fieldtype": "Datetime",
			"width": 150,
		},
		{
			"label": _("Finished Product"),
			"fieldname": "production_item",
			"fieldtype": "Link",
			"options": "Item",
			"width": 150,
		},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 150},
		{"label": _("BOM"), "fieldname": "bom_no", "fieldtype": "Link", "options": "BOM", "width": 160},
		{
			"label": _("Sales Order"),
			"fieldname": "sales_order",
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 140,
		},
		{"label": _("Ordered Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 100},
		{"label": _("Produced Qty"), "fieldname": "produced_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Process Loss"), "fieldname": "process_loss_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Costed On Qty"), "fieldname": "costed_qty", "fieldtype": "Float", "width": 115},
		{
			"label": _("Standard Time (Mins)"),
			"fieldname": "standard_mins",
			"fieldtype": "Float",
			"width": 150,
		},
		{"label": _("Actual Time (Mins)"), "fieldname": "actual_mins", "fieldtype": "Float", "width": 140},
		{
			"label": _("Time Variance (Mins)"),
			"fieldname": "time_variance_mins",
			"fieldtype": "Float",
			"width": 150,
		},
		{
			"label": _("Time Variance %"),
			"fieldname": "time_variance_percent",
			"fieldtype": "Percent",
			"width": 130,
		},
		{"label": _("Job Cards"), "fieldname": "job_cards", "fieldtype": "Int", "width": 95},
		{
			"label": _("Standard Material Cost"),
			"fieldname": "standard_material_cost",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 170,
		},
		{
			"label": _("Actual Material Cost"),
			"fieldname": "actual_material_cost",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
		{
			"label": _("Material Variance"),
			"fieldname": "material_variance",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{
			"label": _("Material Variance %"),
			"fieldname": "material_variance_percent",
			"fieldtype": "Percent",
			"width": 150,
		},
		{
			"label": _("Standard Operation Cost"),
			"fieldname": "standard_operation_cost",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 180,
		},
		{
			"label": _("Actual Operation Cost"),
			"fieldname": "actual_operation_cost",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 170,
		},
		{
			"label": _("Operation Variance"),
			"fieldname": "operation_variance",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 155,
		},
		{
			"label": _("Operation Variance %"),
			"fieldname": "operation_variance_percent",
			"fieldtype": "Percent",
			"width": 160,
		},
		{
			"label": _("Standard Manufacturing Cost"),
			"fieldname": "standard_total_cost",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 200,
		},
		{
			"label": _("Actual Manufacturing Cost"),
			"fieldname": "actual_total_cost",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 190,
		},
		{
			"label": _("Total Cost Variance"),
			"fieldname": "total_variance",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
		{"label": _("Variance %"), "fieldname": "variance_percent", "fieldtype": "Percent", "width": 110},
		{
			"label": _("Standard Cost / Unit"),
			"fieldname": "standard_cost_per_unit",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
		{
			"label": _("Actual Cost / Unit"),
			"fieldname": "actual_cost_per_unit",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{
			"label": _("Cost / Unit Variance"),
			"fieldname": "cost_per_unit_variance",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
		{
			"label": _("Cost / Unit Variance %"),
			"fieldname": "cost_per_unit_variance_percent",
			"fieldtype": "Percent",
			"width": 165,
		},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Data", "width": 90, "hidden": 1},
	]
