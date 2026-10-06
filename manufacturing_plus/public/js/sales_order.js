// Copyright (c) 2026, Finstein and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		frm.add_custom_button(
			__("Get Expected Delivery Date"),
			() => fill_delivery_dates(frm, { overwrite: true }),
			__("Manufacturing Plus")
		);
	},

	// the button that sits under the Delivery Date field
	mp_get_expected_delivery_date(frm) {
		fill_delivery_dates(frm, { overwrite: true });
	},

	transaction_date(frm) {
		fill_delivery_dates(frm, { silent: true });
	},
});

frappe.ui.form.on("Sales Order Item", {
	qty: (frm, cdt, cdn) => schedule(frm, cdt, cdn),
	item_code: (frm, cdt, cdn) => schedule(frm, cdt, cdn),
	warehouse: (frm, cdt, cdn) => schedule(frm, cdt, cdn),
});

let timer = null;

function schedule(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row || !row.item_code || !row.qty) return;
	clearTimeout(timer);
	timer = setTimeout(() => fill_delivery_dates(frm, { silent: true, rows: [row] }), 400);
}

function fill_delivery_dates(frm, { overwrite = false, silent = false, rows = null } = {}) {
	const source = rows || frm.doc.items || [];
	const items = source
		.filter((r) => r.item_code && r.qty)
		.map((r) => ({
			idx: r.idx,
			item_code: r.item_code,
			qty: r.qty,
			uom: r.uom,
			conversion_factor: r.conversion_factor,
			warehouse: r.warehouse,
		}));

	if (!items.length) {
		if (!silent) frappe.msgprint(__("Add an item with a quantity first."));
		return;
	}

	frappe.call({
		method: "manufacturing_plus.planning.expected_delivery.get_expected_delivery_dates_bulk",
		args: {
			items: JSON.stringify(items),
			transaction_date: frm.doc.transaction_date,
			company: frm.doc.company,
			sales_order: frm.doc.name,
		},
		freeze: !silent,
		freeze_message: __("Working out the delivery date..."),
		callback(r) {
			if (!r.message) return;

			let latest = null;
			const problems = [];

			r.message.forEach((result) => {
				const row = (frm.doc.items || []).find((i) => i.idx === result.idx);
				if (!row) return;

				frappe.model.set_value(row.doctype, row.name, {
					mp_expected_delivery_date: result.expected_delivery_date,
					mp_rm_lead_days: result.rm_lead_days,
					mp_queue_days: result.queue_days,
					mp_production_days: result.production_days,
					mp_buffer_days: result.buffer_days,
					mp_bom_used: result.bom_no,
					mp_calc_status: result.status,
				});

				if (result.expected_delivery_date) {
					if (overwrite || !row.delivery_date) {
						frappe.model.set_value(
							row.doctype,
							row.name,
							"delivery_date",
							result.expected_delivery_date
						);
					}
					if (!latest || result.expected_delivery_date > latest) {
						latest = result.expected_delivery_date;
					}
				} else {
					problems.push(`#${result.idx} ${result.item_code} (${result.status || __("no date")})`);
				}
			});

			if (latest && (overwrite || !frm.doc.delivery_date)) {
				frm.set_value("delivery_date", latest);
			}
			frm.refresh_field("items");

			if (!silent && latest) {
				frappe.show_alert({
					message: __("Delivery dates updated. Latest: {0}", [frappe.datetime.str_to_user(latest)]),
					indicator: "green",
				});
			}

			if (problems.length) {
				frappe.msgprint({
					title: __("No date for some rows"),
					indicator: "orange",
					message:
						__("These rows could not be worked out, so their Delivery Date is untouched:") +
						"<br>" +
						problems.join("<br>"),
				});
			}
		},
	});
}

// --- Forecast orders (Kaynes selling flow) ---
frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		apply_forecast_rules(frm);
		show_forecast_coverage(frm);
	},

	mp_is_forecast(frm) {
		apply_forecast_rules(frm);
	},
});

// A forecast has no customer PO behind it, so the PO fields cannot be mandatory.
function apply_forecast_rules(frm) {
	const forecast = !!frm.doc.mp_is_forecast;

	["po_no", "po_date"].forEach((field) => {
		frm.set_df_property(field, "reqd", forecast ? 0 : 1);
	});
	frm.refresh_fields(["po_no", "po_date"]);

	if (forecast && frm.doc.docstatus < 2) {
		frm.dashboard.add_indicator(__("Forecast Order"), "blue");
	}
}

function show_forecast_coverage(frm) {
	if (!frm.doc.mp_is_forecast || frm.doc.docstatus !== 1) return;

	frappe.call({
		method: "manufacturing_plus.selling.forecast.get_forecast_coverage",
		args: { sales_order: frm.doc.name },
		callback(r) {
			const rows = (r.message || {}).rows || [];
			const confirmed = rows.filter((row) => flt(row.confirmed_qty) > 0);
			if (!confirmed.length) return;

			const lines = confirmed
				.map((row) =>
					__("{0}: {1} of {2} confirmed, {3} left", [
						row.item_code,
						format_number(row.confirmed_qty),
						format_number(row.forecast_qty),
						format_number(row.remaining_qty),
					])
				)
				.join("<br>");

			frm.dashboard.add_comment(lines, "blue", true);
		},
	});
}
