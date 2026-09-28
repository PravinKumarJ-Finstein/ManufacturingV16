// Copyright (c) 2026, Finstein and contributors
frappe.ui.form.on("Job Setup Verification", {
	get_checklist(frm) {
		if (!frm.doc.operation || !frm.doc.company) {
			frappe.msgprint(__("Set Company and Operation first."));
			return;
		}
		frm.call("load_checklist").then(() => frm.refresh_field("checklist_detail"));
	},
	operation(frm) {
		if (frm.doc.operation && frm.doc.company && !(frm.doc.checklist_detail || []).length) {
			frm.call("load_checklist").then(() => frm.refresh_field("checklist_detail"));
		}
	},
});
