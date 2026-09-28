# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from manufacturing_plus.planning.features import guard


class ComboParts(Document):
	def validate(self):
		guard(self.doctype)
