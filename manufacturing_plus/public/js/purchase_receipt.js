// Copyright (c) 2026, Finstein and contributors
frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;

		frappe.call({
			method: "manufacturing_plus.shopfloor.combo.has_combo_items",
			args: { purchase_receipt: frm.doc.name },
			callback(r) {
				if (!r.message) return;
				frm.add_custom_button(__("Split Combo"), () => {
					frappe.confirm(
						__("Split the combo item(s) on this Purchase Receipt into their child items?"),
						() => {
							frappe.call({
								method: "manufacturing_plus.shopfloor.combo.split_combo_items",
								args: { purchase_receipt: frm.doc.name },
								freeze: true,
								freeze_message: __("Splitting..."),
								callback(res) {
									if (res.message) {
										frappe.msgprint({
											title: __("Combo Split Complete"),
											message: __("Created Repack Stock Entry(s): {0}", [res.message.join(", ")]),
											indicator: "green",
										});
									}
								},
							});
						}
					);
				});
			},
		});
	},
});
