# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from manufacturing_plus.planning.features import guard


class ExcessIssueNote(Document):
	def validate(self):
		guard(self.doctype)
		if self.pick_list and not self.work_order:
			self.work_order = frappe.db.get_value("Pick List", self.pick_list, "work_order")

		if flt(self.excess_qty) <= 0:
			frappe.throw(_("Excess Qty must be more than zero."))
