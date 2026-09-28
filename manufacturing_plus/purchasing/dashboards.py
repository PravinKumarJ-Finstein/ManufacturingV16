# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Connections shown on core doctypes this app feeds."""

from frappe import _

OUR_GROUPS = [
	{"label": _("Auto Purchase"), "items": ["Auto Purchase Run"]},
]


def master_production_schedule(data=None):
	"""Show the Auto Purchase Run this MPS belongs to, beside whatever core shows."""
	data = data or {}
	data.setdefault("fieldname", "master_production_schedule")
	data.setdefault("transactions", [])
	data.setdefault("non_standard_fieldnames", {})

	existing = {group.get("label") for group in data["transactions"]}
	for group in OUR_GROUPS:
		if group["label"] not in existing:
			data["transactions"].append(group)

	return data
