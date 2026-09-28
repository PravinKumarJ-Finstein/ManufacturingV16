# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Production days, worked out from the BOM operations.

Throughput lives in one place only: BOM Operation. `time_in_mins` is per BOM quantity,
`batch_size` turns it into time per batch, and `fixed_time` makes it independent of qty.
"""

import math

import frappe
from frappe.utils import cint, flt

from manufacturing_plus.planning.settings import setting

DEFAULT_HOURS_PER_DAY = 8.0


@frappe.request_cache
def get_bom_operations(bom_no: str) -> list[dict]:
	if not bom_no:
		return []

	return frappe.get_all(
		"BOM Operation",
		filters={"parent": bom_no, "parenttype": "BOM"},
		fields=[
			"idx",
			"operation",
			"workstation",
			"workstation_type",
			"time_in_mins",
			"fixed_time",
			"batch_size",
		],
		order_by="idx asc",
	)


@frappe.request_cache
def get_workstation_hours(workstation: str | None) -> float:
	"""Working hours a day for this machine, from its Working Hours table."""
	if not workstation:
		return 0.0

	return flt(frappe.db.get_value("Workstation", workstation, "total_working_hours"))


def hours_per_day(workstation: str | None = None) -> float:
	if cint(setting("use_workstation_working_hours", 1)):
		hours = get_workstation_hours(workstation)
		if hours > 0:
			return hours

	return flt(setting("working_hours_per_day", DEFAULT_HOURS_PER_DAY)) or DEFAULT_HOURS_PER_DAY


def operation_hours(op: dict, stock_qty: float, bom_qty: float) -> tuple[float, str]:
	"""-> (hours, where the number came from)."""
	if op.get("fixed_time") and flt(op.get("time_in_mins")):
		return flt(op["time_in_mins"]) / 60.0, "bom_fixed_time"

	if flt(op.get("batch_size")) > 0 and flt(op.get("time_in_mins")):
		batches = math.ceil(flt(stock_qty) / flt(op["batch_size"]))
		return batches * flt(op["time_in_mins"]) / 60.0, "bom_batch_size"

	if flt(op.get("time_in_mins")):
		return (flt(op["time_in_mins"]) / (bom_qty or 1)) * flt(stock_qty) / 60.0, "bom_time_in_mins"

	return 0.0, ""


def get_production_days(bom_no: str, stock_qty: float, item_code: str | None = None) -> dict:
	"""Every operation on the BOM, converted to days and added up."""
	result = {"days": 0.0, "operations": [], "status": "Computed", "source": ""}

	operations = get_bom_operations(bom_no)
	if not operations:
		result["days"] = flt(setting("fallback_production_days", 0))
		result["status"] = "Partial Data" if not result["days"] else "Computed"
		return result

	bom_qty = flt(frappe.db.get_value("BOM", bom_no, "quantity")) or 1.0
	sources = set()

	for op in operations:
		hours, source = operation_hours(op, stock_qty, bom_qty)
		if not source:
			result["status"] = "Partial Data"

		hpd = hours_per_day(op.get("workstation"))
		days = hours / hpd if hpd else 0.0
		result["days"] += days
		if source:
			sources.add(source)

		result["operations"].append(
			{
				"operation": op.get("operation"),
				"workstation": op.get("workstation"),
				"time_in_mins": flt(op.get("time_in_mins")),
				"batch_size": flt(op.get("batch_size")),
				"source": source or "missing",
				"hours": flt(hours, 3),
				"hours_per_day": hpd,
				"days": flt(days, 3),
			}
		)

	result["days"] = flt(result["days"], 3)
	result["source"] = ", ".join(sorted(sources))
	return result
