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
		add_stock_entry_button(frm);

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

// The transfer is created automatically on submit; this is the retry when that failed.
function add_stock_entry_button(frm) {
	if (frm.doc.docstatus !== 1 || !frm.doc.work_order) return;
	if (frm.doc.purpose !== "Material Transfer for Manufacture") return;

	frappe.db
		.get_value("Stock Entry", { pick_list: frm.doc.name, docstatus: ["<", 2] }, "name")
		.then((r) => {
			if (r.message && r.message.name) {
				frm.add_custom_button(__("Stock Entry {0}", [r.message.name]), () =>
					frappe.set_route("Form", "Stock Entry", r.message.name)
				);
				return;
			}

			frm.add_custom_button(
				__("Create Stock Entry"),
				() => {
					frappe.call({
						method: "manufacturing_plus.shopfloor.pick_list.make_stock_entry",
						args: { pick_list: frm.doc.name },
						freeze: true,
						freeze_message: __("Transferring material..."),
						callback(res) {
							if (!res.message) return;
							frappe.show_alert({
								message: __("Stock Entry {0} created.", [res.message]),
								indicator: "green",
							});
							frappe.set_route("Form", "Stock Entry", res.message);
						},
					});
				},
				__("Create")
			).addClass("btn-primary");
		});
}
