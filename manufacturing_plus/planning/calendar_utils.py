# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Holiday handling for the promised date."""

import frappe
from frappe.utils import add_days, getdate

from manufacturing_plus.planning.settings import is_enabled, setting

MAX_ROLL_DAYS = 60


@frappe.request_cache
def get_holiday_set(holiday_list: str | None) -> frozenset:
	if not holiday_list:
		return frozenset()

	rows = frappe.get_all(
		"Holiday", filters={"parent": holiday_list}, fields=["holiday_date"], pluck="holiday_date"
	)
	return frozenset(getdate(d) for d in rows)


def get_holiday_list(company: str | None = None) -> str | None:
	holiday_list = setting("holiday_list")
	if holiday_list:
		return holiday_list

	if company:
		return frappe.db.get_value("Company", company, "default_holiday_list")

	return (
		frappe.db.get_single_value("Global Defaults", "default_holiday_list")
		if frappe.db.exists("DocType", "Global Defaults")
		else None
	)


def roll_forward(date, company: str | None = None):
	"""Move the date past holidays. Returns the date unchanged when the feature is off."""
	date = getdate(date)
	if not is_enabled("skip_holidays"):
		return date

	holidays = get_holiday_set(get_holiday_list(company))
	if not holidays:
		return date

	for _ in range(MAX_ROLL_DAYS):
		if date not in holidays:
			return date
		date = getdate(add_days(date, 1))

	return date
