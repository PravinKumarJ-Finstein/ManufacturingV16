// Copyright (c) 2026, Finstein and contributors
frappe.ui.form.on("Auto Purchase Run", {
	refresh(frm) {
		add_rerun_button(frm);
		guard_delete(frm);
	},
});

function add_rerun_button(frm) {
	if (!frm.doc.sales_order) return;
	if (!["Failed", "Partially Completed", "Completed"].includes(frm.doc.status)) return;

	const label = frm.doc.status === "Completed" ? __("Run Again") : __("Re-run");
	const button = frm.add_custom_button(label, () => {
		frappe.confirm(
			__("Order whatever is still outstanding for {0}? Nothing already ordered is repeated.", [
				frm.doc.sales_order,
			]),
			() => {
				frappe.call({
					method: "manufacturing_plus.purchasing.orchestrator.rerun",
					args: { run_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Running..."),
					callback() {
						frm.reload_doc();
						frappe.show_alert({ message: __("This run has been updated."), indicator: "green" });
					},
				});
			}
		);
	});
	if (frm.doc.status !== "Completed") button.addClass("btn-primary");
}

// Say what a delete would touch, before it happens.
function guard_delete(frm) {
	if (frm.is_new() || frm._mp_delete_guarded) return;
	frm._mp_delete_guarded = true;

	const original = frm.savetrash.bind(frm);
	frm.savetrash = function () {
		frappe.call({
			method: "manufacturing_plus.purchasing.cleanup.get_run_impact",
			args: { run: frm.doc.name },
			callback(r) {
				const impact = r.message || {};
				const lines = [];

				const mrs = (impact.material_requests || []).map((d) => d.name);
				const pos = (impact.purchase_orders || []).map((d) => d.name);

				const plans = impact.master_production_schedules || [];
				if (plans.length) lines.push(__("Plans kept, link cleared: {0}", [plans.join(", ")]));
				if (mrs.length) lines.push(__("Material Requests kept, link cleared: {0}", [mrs.join(", ")]));
				if (pos.length) lines.push(__("Purchase Orders kept, link cleared: {0}", [pos.join(", ")]));
				if (impact.submitted_purchase_orders && impact.submitted_purchase_orders.length) {
					lines.push(
						`<b>${__("Submitted Purchase Orders stay open with the supplier: {0}", [
							impact.submitted_purchase_orders.join(", "),
						])}</b>`
					);
				}
				if (impact.demand_rows) {
					const removed = impact.demand_rows - (impact.demand_rows_kept || 0);
					lines.push(__("{0} demand row(s) removed, {1} kept because they led to a purchase", [
						removed,
						impact.demand_rows_kept || 0,
					]));
				}
				if (impact.exceptions) lines.push(__("{0} exception(s) removed", [impact.exceptions]));

				if (!lines.length) {
					original();
					return;
				}

				frappe.confirm(
					__("Deleting {0} will:", [frm.doc.name]) +
						"<br><br>" +
						lines.join("<br>") +
						"<br><br>" +
						__("No Material Request or Purchase Order is deleted. Continue?"),
					original
				);
			},
		});
	};
}
