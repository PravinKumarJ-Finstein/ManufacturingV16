// Copyright (c) 2026, Finstein and contributors
frappe.ui.form.on("Stores Return", {
	pick_list(frm) {
		if (!frm.doc.pick_list) return;
		frm.call("load_outstanding_spools").then(() => frm.refresh_field("items"));
	},
});
