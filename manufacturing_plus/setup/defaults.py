# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""First-run defaults for Manufacturing Control Setting.

A Single only gets its field defaults once the document has been saved, so a fresh
install would read 0 for every check box. This writes them once and never again.
"""

import frappe

SETTINGS_DOCTYPE = "Manufacturing Control Setting"
DEFAULT_CLASS_THRESHOLDS = [("A", 0.9), ("B", 0.8), ("C", 0.7)]


def ensure_settings():
	if frappe.db.exists("Singles", {"doctype": SETTINGS_DOCTYPE, "field": "enable_expected_delivery_date"}):
		return

	doc = frappe.get_single(SETTINGS_DOCTYPE)
	for field in doc.meta.fields:
		if field.default not in (None, "") and not doc.get(field.fieldname):
			doc.set(field.fieldname, field.default)

	if not doc.get("class_thresholds"):
		for item_class, threshold in DEFAULT_CLASS_THRESHOLDS:
			doc.append("class_thresholds", {"item_class": item_class, "threshold": threshold})

	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	frappe.clear_cache()
