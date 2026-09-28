# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from manufacturing_plus.planning.features import guard


class YieldEntry(Document):
	def validate(self):
		guard(self.doctype)
		self.set_work_order_qty()
		self.validate_quantities()
		self.set_totals()

	def set_work_order_qty(self):
		if self.work_order:
			self.work_order_qty = flt(frappe.db.get_value("Work Order", self.work_order, "qty"))

	def validate_quantities(self):
		if flt(self.accepted_qty) > flt(self.inspected_qty):
			frappe.throw(_("Accepted Qty cannot be more than Inspected Qty."))

		if flt(self.inspected_qty) > flt(self.accepted_qty) and not self.rejections:
			frappe.throw(
				_("Please list the rejections for the {0} rejected unit(s).").format(
					flt(self.inspected_qty) - flt(self.accepted_qty)
				)
			)

		already = flt(
			frappe.db.sql(
				"""
				select sum(inspected_qty) from `tabYield Entry`
				where work_order = %(work_order)s and operation = %(operation)s
				  and docstatus = 1 and name != %(name)s
				""",
				{"work_order": self.work_order, "operation": self.operation, "name": self.name or ""},
			)[0][0]
		)
		if self.work_order_qty and already + flt(self.inspected_qty) > flt(self.work_order_qty):
			frappe.throw(
				_(
					"Inspected Qty would total {0}, which is more than the Work Order qty {1} for this operation."
				).format(already + flt(self.inspected_qty), self.work_order_qty)
			)

	def set_totals(self):
		self.rejected_qty = flt(self.inspected_qty) - flt(self.accepted_qty)
		self.yield_percent = (
			(flt(self.accepted_qty) / flt(self.inspected_qty)) * 100 if flt(self.inspected_qty) else 0
		)
		self.total_defects = sum(int(row.number_of_defects or 0) for row in self.rejections)
