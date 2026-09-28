# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class ManufacturingControlSetting(Document):
	def on_update(self):
		from manufacturing_plus.planning.features import apply_permissions

		# every switch is read through a cached document, so the cache has to go
		# the moment someone changes one, or the old value keeps being used.
		frappe.clear_cache()
		frappe.clear_document_cache("Manufacturing Control Setting", "Manufacturing Control Setting")

		# a switched-off feature must disappear: no list, no form, not in the search bar
		apply_permissions()
