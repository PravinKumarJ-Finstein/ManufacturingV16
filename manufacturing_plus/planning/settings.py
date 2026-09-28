# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Single place to read Manufacturing Control Setting."""

import frappe

SETTINGS_DOCTYPE = "Manufacturing Control Setting"


@frappe.request_cache
def get_settings():
	return frappe.get_cached_doc(SETTINGS_DOCTYPE)


def is_enabled(fieldname: str) -> bool:
	"""True only when the feature flag is on. Never raises."""
	try:
		return bool(get_settings().get(fieldname))
	except Exception:
		return False


def setting(fieldname: str, default=None):
	try:
		value = get_settings().get(fieldname)
	except Exception:
		return default
	return default if value in (None, "") else value
