# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Switching a feature off must stop it — in the background and at the document."""

import frappe
from frappe.tests.utils import FrappeTestCase

from manufacturing_plus.planning.features import FEATURE_DOCTYPES, has_permission
from manufacturing_plus.planning.settings import is_enabled
from manufacturing_plus.tests.fixtures import ASSEMBLY, seed


class TestFeatureSwitches(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()

	def tearDown(self):
		for field in (
			"enable_yield_entry",
			"enable_pick_list_buffer",
			"enable_spool_tracking",
			"enable_combo_split",
			"require_job_setup_verification",
		):
			frappe.db.set_single_value("Manufacturing Control Setting", field, 1)
		frappe.clear_cache()

	def _set(self, field, value):
		frappe.db.set_single_value("Manufacturing Control Setting", field, value)
		frappe.clear_cache()

	def test_every_switch_is_read_somewhere(self):
		"""No setting may be decoration: each one has to reach the code."""
		for doctype, (field, _label) in FEATURE_DOCTYPES.items():
			self.assertTrue(
				frappe.get_meta("Manufacturing Control Setting").get_field(field),
				f"{doctype} points at a setting that does not exist: {field}",
			)

	def test_saving_the_setting_takes_effect_at_once(self):
		self._set("enable_yield_entry", 0)
		self.assertFalse(is_enabled("enable_yield_entry"))
		self._set("enable_yield_entry", 1)
		self.assertTrue(is_enabled("enable_yield_entry"))

	def test_a_disabled_feature_refuses_new_documents(self):
		self._set("enable_yield_entry", 0)
		entry = frappe.get_doc(
			{
				"doctype": "Yield Entry",
				"company": self.data["company"],
				"work_order": _any_work_order(self.data),
				"operation": ASSEMBLY,
				"entry_date": "2026-09-24",
				"inspected_qty": 10,
				"accepted_qty": 10,
			}
		)
		self.assertRaises(frappe.ValidationError, entry.insert)

	def test_a_disabled_feature_is_closed_completely(self):
		self._set("enable_combo_split", 0)
		# no read either: the list and the form must not open
		self.assertFalse(has_permission(frappe.new_doc("Combo Parts"), "read"))
		self.assertFalse(has_permission(frappe.new_doc("Combo Parts"), "create"))

		self._set("enable_combo_split", 1)
		self.assertTrue(has_permission(frappe.new_doc("Combo Parts"), "read"))

	def test_a_disabled_doctype_is_kept_out_of_the_search_bar(self):
		from manufacturing_plus.planning.features import hide_disabled_doctypes

		self._set("enable_yield_entry", 0)
		bootinfo = frappe._dict(
			user=frappe._dict(
				can_read=["Yield Entry", "Item"],
				can_search=["Yield Entry", "Item"],
				can_create=["Yield Entry", "Item"],
				all_read=["Yield Entry", "Item"],
			)
		)
		hide_disabled_doctypes(bootinfo)
		for key in ("can_read", "can_search", "can_create", "all_read"):
			self.assertNotIn("Yield Entry", bootinfo.user[key], f"still listed in {key}")
			self.assertIn("Item", bootinfo.user[key])

	def test_an_enabled_doctype_stays_in_the_search_bar(self):
		from manufacturing_plus.planning.features import hide_disabled_doctypes

		self._set("enable_yield_entry", 1)
		bootinfo = frappe._dict(user=frappe._dict(can_search=["Yield Entry"]))
		hide_disabled_doctypes(bootinfo)
		self.assertIn("Yield Entry", bootinfo.user.can_search)

	def test_buffer_masters_follow_their_switch(self):
		self._set("enable_pick_list_buffer", 0)
		self.assertFalse(has_permission(frappe.new_doc("Pick List Configuration"), "create"))
		self.assertFalse(has_permission(frappe.new_doc("MP Item Package"), "create"))

	def test_spool_documents_follow_their_switch(self):
		self._set("enable_spool_tracking", 0)
		self.assertFalse(has_permission(frappe.new_doc("Stores Return"), "create"))
		self.assertFalse(has_permission(frappe.new_doc("Excess Issue Note"), "create"))


class TestFeatureVisibility(FrappeTestCase):
	"""A switched-off doctype must be closed for a real user, not just for the hook."""

	USER = "_mp_feature_tester@example.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed()
		if not frappe.db.exists("User", cls.USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": cls.USER,
					"first_name": "MP Feature Tester",
					"send_welcome_email": 0,
				}
			)
			user.append("roles", {"role": "Manufacturing Manager"})
			user.insert(ignore_permissions=True)
		frappe.db.commit()

	def tearDown(self):
		self._toggle(1)

	def _toggle(self, value):
		setting = frappe.get_single("Manufacturing Control Setting")
		setting.enable_yield_entry = value
		setting.flags.ignore_permissions = True
		setting.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.clear_cache()

	def test_the_list_is_closed_while_the_feature_is_off(self):
		self._toggle(0)
		self.assertFalse(frappe.has_permission("Yield Entry", "read", user=self.USER))
		self.assertFalse(frappe.has_permission("Yield Entry", "create", user=self.USER))

		self._toggle(1)
		self.assertTrue(frappe.has_permission("Yield Entry", "read", user=self.USER))
		self.assertTrue(frappe.has_permission("Yield Entry", "create", user=self.USER))

	def test_switching_back_on_grants_no_more_than_the_doctype_says(self):
		self._toggle(0)
		self._toggle(1)

		for row in frappe.get_all(
			"DocPerm", filters={"parent": "Yield Entry", "permlevel": 0}, fields=["role", "delete"]
		):
			restored = frappe.db.get_value(
				"Custom DocPerm", {"parent": "Yield Entry", "role": row.role, "permlevel": 0}, "delete"
			)
			self.assertEqual(
				int(restored or 0),
				int(row.get("delete") or 0),
				f"{row.role} ended up with a different delete permission than the doctype defines",
			)


def _any_work_order(data) -> str:
	name = frappe.db.get_value("Work Order", {"docstatus": ["<", 2]}, "name")
	if name:
		return name

	frappe.db.set_single_value("Manufacturing Control Setting", "wo_only_from_production_plan", 0)
	frappe.clear_cache()
	bom = frappe.db.get_value("BOM", {"docstatus": 1}, "name")
	item = frappe.db.get_value("BOM", bom, "item")
	work_order = frappe.get_doc(
		{
			"doctype": "Work Order",
			"company": data["company"],
			"production_item": item,
			"bom_no": bom,
			"qty": 10,
			"fg_warehouse": data["warehouse"],
			"wip_warehouse": data["warehouse"],
			"source_warehouse": data["warehouse"],
		}
	).insert(ignore_permissions=True)
	return work_order.name
