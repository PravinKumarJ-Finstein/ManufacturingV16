// Copyright (c) 2026, Finstein and contributors
frappe.ui.form.on("Pick List", {
	mp_scan_spool(frm) {
		const value = (frm.doc.mp_scan_spool || "").trim();
		if (!value) return;

		frappe.call({
			method: "manufacturing_plus.shopfloor.spool.resolve_scan",
			args: { pick_list: frm.doc.name, scanned_value: value },
			callback(r) {
				frm.set_value("mp_scan_spool", "");
				if (!r.message) return;
				frappe.show_alert({ message: r.message.message, indicator: "green" });
				frm.reload_doc();
			},
			error() {
				frm.set_value("mp_scan_spool", "");
			},
		});
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1 && (frm.doc.mp_spool_details || []).length) {
			frm.add_custom_button(__("Stores Return"), () => {
				frappe.new_doc("Stores Return", {
					company: frm.doc.company,
					pick_list: frm.doc.name,
					work_order: frm.doc.work_order,
					from_warehouse: frm.doc.parent_warehouse,
				});
			});
			frm.add_custom_button(__("Excess Issue Note"), () => {
				frappe.new_doc("Excess Issue Note", {
					company: frm.doc.company,
					pick_list: frm.doc.name,
					work_order: frm.doc.work_order,
				});
			});
		}
	},
});
