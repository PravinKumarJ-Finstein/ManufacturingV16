// Copyright (c) 2026, Finstein and contributors
// Create Pick List from a Work Order: show what the stock allows, then pick it.
frappe.ui.form.on("Work Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (["Completed", "Stopped", "Closed"].includes(frm.doc.status)) return;
		if (!frappe.boot.manufacturing_plus || !frappe.boot.manufacturing_plus.custom_wo_pick_list) return;

		// core's own button maps every outstanding row at full qty; ours checks the stock first
		["Create", "Actions", undefined].forEach((group) => {
			try {
				frm.remove_custom_button(__("Create Pick List"), group);
			} catch (e) {
				// the button is not always there, depending on status
			}
		});

		frm.add_custom_button(__("Create Pick List"), () => open_pick_list_flow(frm), __("Create"));
	},
});

function open_pick_list_flow(frm) {
	frappe.call({
		method: "manufacturing_plus.shopfloor.work_order_pick_list.get_pick_list_preview",
		args: { work_order: frm.doc.name },
		freeze: true,
		freeze_message: __("Checking stock..."),
		callback(r) {
			const preview = r.message;
			if (!preview) return;

			if (preview.draft_pick_list) {
				frappe.confirm(
					__("Work Order {0} already has a draft Pick List {1}.", [
						frm.doc.name.bold(),
						preview.draft_pick_list.bold(),
					]) +
						"<br><br>" +
						__("Open it? Submit or delete it before picking again."),
					() => frappe.set_route("Form", "Pick List", preview.draft_pick_list)
				);
				return;
			}

			if (!preview.rows.length) {
				frappe.msgprint({
					title: __("Nothing To Pick"),
					indicator: "orange",
					message: __("Every component of this Work Order has already been transferred."),
				});
				return;
			}

			show_preview_dialog(frm, preview);
		},
	});
}

function show_preview_dialog(frm, preview) {
	const dialog = new frappe.ui.Dialog({
		title: __("Create Pick List for {0}", [frm.doc.name]),
		size: "extra-large",
		fields: [
			{ fieldname: "summary", fieldtype: "HTML" },
			{ fieldname: "components", fieldtype: "HTML" },
		],
		primary_action_label: __("Create Pick List"),
		primary_action() {
			dialog.hide();
			create_pick_list(frm);
		},
	});

	const capacity = flt(preview.component_capacity);
	const nothing = preview.rows.every((row) => flt(row.pickable_qty) <= 0);

	dialog.fields_dict.summary.$wrapper.html(summary_html(frm, preview, capacity, nothing));
	dialog.fields_dict.components.$wrapper.html(component_table(preview.rows));

	if (nothing) {
		dialog.get_primary_btn().addClass("hide");
	}

	dialog.show();
}

function summary_html(frm, preview, capacity, nothing) {
	const rows = [
		[__("Order Qty"), format_number(preview.qty)],
		[__("Produced"), format_number(preview.produced_qty)],
		[__("Can Be Picked For"), `<b>${format_number(capacity)}</b> ${__("unit(s)")}`],
	];

	const cells = rows
		.map(([label, value]) => `<div class="col-sm-4"><div class="text-muted">${label}</div>${value}</div>`)
		.join("");

	const note = nothing
		? `<div class="alert alert-warning mt-3 mb-0">${__(
				"No component has free stock right now, so there is nothing to pick. The reasons are listed below."
		  )}</div>`
		: capacity < flt(preview.qty)
		? `<div class="alert alert-info mt-3 mb-0">${__(
				"Stock covers only part of this order. A Pick List is created for what is free now; the rest stays outstanding for a later Pick List."
		  )}</div>`
		: "";

	return `<div class="row">${cells}</div>${note}`;
}

function component_table(rows) {
	const header = [
		__("Component"),
		__("Outstanding"),
		__("On Hand"),
		__("Owed To Other Orders"),
		__("Free"),
		__("Will Pick"),
		__("Expired"),
	];

	const body = rows
		.map((row) => {
			const short = flt(row.pickable_qty) < flt(row.outstanding_qty);
			const colour = flt(row.pickable_qty) <= 0 ? "text-danger" : short ? "text-warning" : "";
			const reason = row.reason
				? `<div class="small text-muted mt-1">${frappe.utils.escape_html(row.reason)}</div>`
				: "";

			return `<tr>
				<td>${frappe.utils.get_form_link("Item", row.item_code, true)}${reason}</td>
				<td class="text-right">${format_number(row.outstanding_qty)}</td>
				<td class="text-right">${format_number(row.on_hand_qty)}</td>
				<td class="text-right">${format_number(row.held_by_others_qty)}</td>
				<td class="text-right">${format_number(row.free_qty)}</td>
				<td class="text-right ${colour}"><b>${format_number(row.pickable_qty)}</b></td>
				<td class="text-right">${flt(row.expired_qty) ? format_number(row.expired_qty) : "-"}</td>
			</tr>`;
		})
		.join("");

	return `<table class="table table-bordered table-sm mt-4">
		<thead><tr>${header.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
		<tbody>${body}</tbody>
	</table>`;
}

function create_pick_list(frm) {
	frappe.call({
		method: "manufacturing_plus.shopfloor.work_order_pick_list.create_pick_list",
		args: { work_order: frm.doc.name },
		freeze: true,
		freeze_message: __("Creating Pick List..."),
		callback(r) {
			const result = r.message || {};
			if (!result.ok) {
				frappe.msgprint({
					title: __("Nothing Picked"),
					indicator: "orange",
					message: [result.reason, ...(result.issues || [])].filter(Boolean).join("<br>"),
				});
				return;
			}

			const notes = [...(result.issues || []), ...(result.warnings || [])];
			if (notes.length) {
				frappe.msgprint({
					title: __("Pick List {0} created", [result.pick_list]),
					indicator: "orange",
					message:
						__("Left outstanding for a later Pick List:") + "<br><br>" + notes.join("<br>"),
				});
			} else {
				frappe.show_alert({
					message: __("Pick List {0} created.", [result.pick_list]),
					indicator: "green",
				});
			}

			frappe.set_route("Form", "Pick List", result.pick_list);
		},
	});
}
