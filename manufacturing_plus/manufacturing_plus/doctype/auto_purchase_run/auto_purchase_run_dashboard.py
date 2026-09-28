# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt

from frappe import _


def get_data():
	return {
		"fieldname": "run",
		"non_standard_fieldnames": {
			"Material Request": "mp_auto_purchase_run",
			"Purchase Order": "mp_auto_purchase_run",
			"Master Production Schedule": "mp_auto_purchase_run",
		},
		"transactions": [
			{"label": _("Planning"), "items": ["Master Production Schedule", "Sales Order Material Demand"]},
			{"label": _("Purchasing"), "items": ["Material Request", "Purchase Order"]},
			{"label": _("Problems"), "items": ["Auto Purchase Exception"]},
		],
	}
