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

// Say what a delete would take with it — and stop it when a Purchase Order is already placed.
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
				const ordered = impact.submitted_purchase_orders || [];

				if (ordered.length) {
					frappe.msgprint({
						title: __("Purchase Order already placed"),
						indicator: "red",
						message:
							__("{0} cannot be deleted: it has submitted Purchase Order(s) {1}.", [
								frm.doc.name.bold(),
								ordered.join(", ").bold(),
							]) +
							"<br><br>" +
							__("Cancel those Purchase Orders first, then delete this run."),
					});
					return;
				}

				const lines = [];
				const pos = (impact.purchase_orders || []).map((d) => d.name);
				const mrs = (impact.material_requests || []).map((d) => d.name);
				const submitted_mrs = impact.submitted_material_requests || [];
				const plans = impact.master_production_schedules || [];

				if (pos.length) lines.push(__("Purchase Orders deleted: {0}", [pos.join(", ")]));
				if (mrs.length) lines.push(__("Material Requests deleted: {0}", [mrs.join(", ")]));
				if (submitted_mrs.length) {
					lines.push(
						`<b>${__("Submitted Material Requests cancelled first: {0}", [
							submitted_mrs.join(", "),
						])}</b>`
					);
				}
				if (impact.demand_rows) lines.push(__("{0} demand row(s) deleted", [impact.demand_rows]));
				if (impact.reservations) {
					lines.push(
						__("{0} stock reservation(s) released and deleted", [impact.reservations])
					);
				}
				if (impact.exceptions) lines.push(__("{0} exception(s) deleted", [impact.exceptions]));
				if (plans.length) lines.push(__("Plans kept, link cleared: {0}", [plans.join(", ")]));

				if (!lines.length) {
					original();
					return;
				}

				frappe.confirm(
					__("Deleting {0} will:", [frm.doc.name]) +
						"<br><br>" +
						lines.join("<br>") +
						"<br><br>" +
						__("This cannot be undone. Continue?"),
					original
				);
			},
		});
	};
}
