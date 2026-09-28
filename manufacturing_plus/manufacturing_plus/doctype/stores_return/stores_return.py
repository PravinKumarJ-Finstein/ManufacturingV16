# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from manufacturing_plus.planning.features import guard


class StoresReturn(Document):
	def validate(self):
		guard(self.doctype)
		if self.pick_list and not self.work_order:
			self.work_order = frappe.db.get_value("Pick List", self.pick_list, "work_order")

		for row in self.items:
			if flt(row.return_qty) <= 0:
				frappe.throw(_("Row #{0}: Return Qty must be more than zero.").format(row.idx))

	def on_submit(self):
		from manufacturing_plus.shopfloor.spool import apply_stores_return

		apply_stores_return(self)

	def on_cancel(self):
		from manufacturing_plus.shopfloor.spool import sync_batch_row

		if self.stock_entry:
			entry = frappe.get_doc("Stock Entry", self.stock_entry)
			if entry.docstatus == 1:
				entry.cancel()

		for row in self.items:
			if row.spool_id:
				sync_batch_row(row.spool_id)

	@frappe.whitelist()
	def load_outstanding_spools(self):
		from manufacturing_plus.shopfloor.spool import get_returnable_spools

		self.set("items", [])
		for row in get_returnable_spools(self.pick_list):
			self.append("items", row)

		return self.items
