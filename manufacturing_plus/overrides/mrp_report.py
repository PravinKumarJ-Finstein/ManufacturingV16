# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Keep the core MRP report inside the plan you asked for.

The core report does not stop at the plan: `add_non_planned_orders` pulls in **every other**
open Sales Order for the same items in the same date window and lists it as an "Ad-hoc" row.
That is right when one plan is meant to hold the whole period, and wrong here — this app
gives every Sales Order its own plan, so those other orders are already planned elsewhere
and their demand would be counted twice.

With **MRP Report: Only Orders In The Plan** on (the default) and an MPS selected, the
report shows the plan's own rows and nothing else. Switch it off to get core behaviour back.
"""

import frappe
from frappe.utils import cint

from manufacturing_plus.planning.settings import setting


def apply(*args, **kwargs) -> None:
	"""Run from before_request / before_job, so every worker gets it. Idempotent."""
	try:
		from erpnext.manufacturing.report.material_requirements_planning_report import (
			material_requirements_planning_report as core,
		)
	except ImportError:
		return

	report = core.MaterialRequirementsPlanningReport
	if getattr(report.add_non_planned_orders, "_mp_patched", False):
		return

	original = report.add_non_planned_orders

	def add_non_planned_orders(self, items):
		if self.filters.get("mps") and cint(setting("mrp_only_planned_orders", 1)):
			return None

		return original(self, items)

	add_non_planned_orders._mp_patched = True
	add_non_planned_orders._mp_original = original
	report.add_non_planned_orders = add_non_planned_orders


def revert() -> None:
	"""Undo the patch — for tests, and to check core behaviour without restarting."""
	from erpnext.manufacturing.report.material_requirements_planning_report import (
		material_requirements_planning_report as core,
	)

	report = core.MaterialRequirementsPlanningReport
	original = getattr(report.add_non_planned_orders, "_mp_original", None)
	if original:
		report.add_non_planned_orders = original


def is_applied() -> bool:
	from erpnext.manufacturing.report.material_requirements_planning_report import (
		material_requirements_planning_report as core,
	)

	return bool(getattr(core.MaterialRequirementsPlanningReport.add_non_planned_orders, "_mp_patched", False))
