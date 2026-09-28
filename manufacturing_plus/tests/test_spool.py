# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Spool tracking: batch rows, balance from the documents, scan and excess gate."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from manufacturing_plus.shopfloor import spool
from manufacturing_plus.tests.fixtures import RM_LONG, RM_SHORT, seed

SPOOL_A = "_MP-REEL-A"
SPOOL_B = "_MP-REEL-B"


class TestSpool(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.data = seed()
		cls.batch = _ensure_batch_with_spools()

	def setUp(self):
		frappe.db.set_single_value("Manufacturing Control Setting", "enable_spool_tracking", 1)
		frappe.clear_cache()

	def test_a_spool_is_a_row_on_its_batch(self):
		row = spool.get_spool_row(SPOOL_A)
		self.assertIsNotNone(row)
		self.assertEqual(row.batch_no, self.batch)
		self.assertEqual(row.item_code, RM_LONG)
		self.assertEqual(flt(row.spool_qty), 5000.0)
		self.assertFalse(frappe.db.exists("DocType", "Spool"), "the Spool master must be gone")

	def test_balance_is_the_full_qty_when_nothing_moved(self):
		self.assertEqual(spool.get_balance(SPOOL_A), 5000.0)

	def test_sync_writes_the_totals_back_onto_the_batch_row(self):
		spool.sync_batch_row(SPOOL_A)
		row = frappe.db.get_value(
			"Spool Details",
			{"spool_id": SPOOL_A},
			["consumed_for_manufacturing", "return_remaining_spool_qty", "status"],
			as_dict=True,
		)
		self.assertEqual(flt(row.consumed_for_manufacturing), 0.0)
		self.assertEqual(flt(row.return_remaining_spool_qty), 5000.0)
		self.assertEqual(row.status, "Active")

	def test_scanning_an_unknown_spool_is_refused(self):
		self.assertRaises(frappe.ValidationError, spool.resolve_scan, pick_list="x", scanned_value="_MP-NOPE")

	def test_scanning_is_refused_when_the_feature_is_off(self):
		frappe.db.set_single_value("Manufacturing Control Setting", "enable_spool_tracking", 0)
		frappe.clear_cache()
		self.assertRaises(frappe.ValidationError, spool.resolve_scan, pick_list="x", scanned_value=SPOOL_A)

	def test_excess_issue_needs_a_note(self):
		doc = frappe._dict(
			name="_MP-PL-TEST",
			locations=[frappe._dict(item_code=RM_LONG, stock_qty=100, qty=100, idx=1, name="row1")],
		)
		too_much = [frappe._dict(idx=1, item_code=RM_LONG, consumed_qty=150, spool_id=SPOOL_A)]
		self.assertRaises(frappe.ValidationError, spool._validate_excess, doc, too_much)

		within = [frappe._dict(idx=1, item_code=RM_LONG, consumed_qty=100, spool_id=SPOOL_A)]
		spool._validate_excess(doc, within)

	def test_spool_item_detection(self):
		self.assertTrue(spool.is_spool_item(RM_LONG))
		self.assertFalse(spool.is_spool_item(RM_SHORT))


def _ensure_batch_with_spools() -> str:
	frappe.db.set_value("Item", RM_LONG, "has_batch_no", 1)
	frappe.db.set_value("Item", RM_LONG, "create_new_batch", 1)

	name = frappe.db.get_value("Batch", {"item": RM_LONG, "batch_id": "_MP-BATCH-1"}, "name")
	batch = (
		frappe.get_doc("Batch", name)
		if name
		else frappe.get_doc({"doctype": "Batch", "batch_id": "_MP-BATCH-1", "item": RM_LONG})
	)

	batch.set("custom_spool_details", [])
	for spool_id, qty in ((SPOOL_A, 5000), (SPOOL_B, 1000)):
		batch.append("custom_spool_details", {"spool_id": spool_id, "spool_qty": qty, "status": "Active"})

	batch.flags.ignore_permissions = True
	batch.save(ignore_permissions=True)
	frappe.db.commit()
	return batch.name
