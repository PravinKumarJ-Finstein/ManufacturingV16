# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Which DocType belongs to which feature switch.

A switched-off feature must not merely stop running in the background: its documents
must not be creatable either, whether from the desk or the API.
"""

import frappe
from frappe import _

from manufacturing_plus.planning.settings import is_enabled

# doctype -> (settings fieldname, label shown in the message)
FEATURE_DOCTYPES = {
	"Yield Entry": ("enable_yield_entry", "Yield Entry"),
	"Job Setup Checklist": ("require_job_setup_verification", "Job Setup Verification"),
	"Job Setup Verification": ("require_job_setup_verification", "Job Setup Verification"),
	"Pick List Configuration": ("enable_pick_list_buffer", "Pick List Buffer"),
	"MP Item Package": ("enable_pick_list_buffer", "Pick List Buffer"),
	"Excess Issue Note": ("enable_spool_tracking", "Spool Tracking"),
	"Stores Return": ("enable_spool_tracking", "Spool Tracking"),
	"Combo Parts": ("enable_combo_split", "Combo Parts Split"),
	"Can Build Log": ("enable_can_build", "Can Build"),
	"Sales Order Material Demand": ("enable_auto_purchase", "Auto Purchase"),
	"MPS Stock Reservation": ("reserve_stock_on_mps", "MPS Stock Reservation"),
	"Auto Purchase Run": ("enable_auto_purchase", "Auto Purchase"),
	"Auto Purchase Exception": ("enable_auto_purchase", "Auto Purchase"),
}

BOOT_KEYS = (
	"can_select",
	"can_create",
	"can_write",
	"can_read",
	"can_submit",
	"can_cancel",
	"can_delete",
	"can_get_report",
	"all_read",
	"can_search",
	"in_create",
	"can_export",
	"can_import",
	"can_print",
	"can_email",
)


def is_doctype_enabled(doctype: str) -> bool:
	setting = FEATURE_DOCTYPES.get(doctype)
	return True if not setting else bool(is_enabled(setting[0]))


def disabled_doctypes() -> list[str]:
	return [doctype for doctype in FEATURE_DOCTYPES if not is_doctype_enabled(doctype)]


def has_permission(doc, ptype=None, user=None):
	"""A switched-off feature is closed completely: no read, so no list and no form."""
	doctype = doc.doctype if hasattr(doc, "doctype") else doc
	return is_doctype_enabled(doctype)


PERM_TYPES = (
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"print",
	"email",
	"share",
)


def apply_permissions() -> list[str]:
	"""Switch the role permissions of every feature doctype on or off.

	The `has_permission` hook only fires when a document is passed, so on its own it
	cannot stop a list from opening. Taking the read permission away does, and it is
	also what keeps the doctype out of the search bar for good.

	Switching back on restores exactly what the doctype's own permission rows say — it
	never grants more than that.
	"""
	from frappe.permissions import update_permission_property

	changed = []
	for doctype in FEATURE_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue

		enabled = is_doctype_enabled(doctype)
		rows = frappe.get_all(
			"DocPerm",
			filters={"parent": doctype, "permlevel": 0},
			fields=["role", *PERM_TYPES],
		)

		for row in rows:
			for ptype in PERM_TYPES:
				value = int(row.get(ptype) or 0) if enabled else 0
				try:
					update_permission_property(doctype, row.role, 0, ptype, value, validate=False)
				except Exception:
					frappe.log_error(
						title=f"Could not set {ptype} on {doctype} for {row.role}",
						message=frappe.get_traceback(),
					)
		changed.append(doctype)

	frappe.clear_cache()
	return changed


CLIENT_SWITCHES = ("custom_wo_pick_list",)


def hide_disabled_doctypes(bootinfo):
	"""extend_bootinfo: keep switched-off doctypes out of the search bar and the desk.

	The same pass hands the client the few switches its scripts need, so a form does not
	have to fetch the setting before it can decide which buttons to show.
	"""
	bootinfo["manufacturing_plus"] = {name: 1 if is_enabled(name) else 0 for name in CLIENT_SWITCHES}

	hidden = set(disabled_doctypes())
	if not hidden or not bootinfo.get("user"):
		return

	for key in BOOT_KEYS:
		values = bootinfo.user.get(key)
		if isinstance(values, list):
			bootinfo.user[key] = [d for d in values if d not in hidden]


def guard(doctype: str) -> None:
	"""Called from a controller: stop the document dead when its feature is off."""
	setting = FEATURE_DOCTYPES.get(doctype)
	if not setting or is_enabled(setting[0]):
		return

	frappe.throw(
		_("{0} is switched off in Manufacturing Control Setting.").format(frappe.bold(setting[1])),
		title=_("Feature Disabled"),
	)
