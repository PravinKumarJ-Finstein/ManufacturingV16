# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from manufacturing_plus.planning.features import guard


class JobSetupVerification(Document):
	def validate(self):
		guard(self.doctype)
		self.verified_by = frappe.session.user
		if not self.checklist_detail:
			frappe.throw(_("Load the checklist for this operation before saving."))

	def before_submit(self):
		missing = [row.idx for row in self.checklist_detail if not (row.observed_value or row.remarks)]
		if missing:
			frappe.throw(
				_("Enter the observed value or a remark for row(s): {0}").format(
					", ".join(str(i) for i in missing)
				)
			)

	@frappe.whitelist()
	def load_checklist(self):
		"""Copy the checklist rows of the approved Job Setup Checklist for this operation."""
		checklist = frappe.db.get_value(
			"Job Setup Checklist",
			{"operation": self.operation, "company": self.company, "disabled": 0},
			"name",
		)
		if not checklist:
			frappe.throw(
				_("No Job Setup Checklist found for operation {0} in {1}.").format(
					frappe.bold(self.operation), frappe.bold(self.company)
				)
			)

		self.set("checklist_detail", [])
		for row in frappe.get_doc("Job Setup Checklist", checklist).checklist_detail:
			self.append(
				"checklist_detail",
				{
					"parameter": row.parameter,
					"parameter_type": row.parameter_type,
					"check_method": row.check_method,
					"acceptance_criteria": row.acceptance_criteria,
				},
			)

		return self.checklist_detail
