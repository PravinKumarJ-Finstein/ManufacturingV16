// Copyright (c) 2026, Finstein and contributors
frappe.query_reports["Work Order Cost Variance"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("Completed From"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			fieldname: "to_date",
			label: __("Completed To"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "include_in_process",
			label: __("Include Work Orders Not Yet Completed"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "work_order",
			label: __("Work Order"),
			fieldtype: "Link",
			options: "Work Order",
			get_query: () => ({ filters: { docstatus: 1 } }),
		},
		{
			fieldname: "production_item",
			label: __("Finished Product"),
			fieldtype: "Link",
			options: "Item",
		},
		{ fieldname: "bom_no", label: __("BOM"), fieldtype: "Link", options: "BOM" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Completed", "In Process", "Not Started", "Stopped", "Closed"],
		},
		{
			fieldname: "cost_basis",
			label: __("Compare Standard Against"),
			fieldtype: "Select",
			options: "Produced Qty\nOrdered Qty",
			default: "Produced Qty",
		},
		{
			fieldname: "only_variances",
			label: __("Only Rows With A Variance"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		const variance_fields = [
			"material_variance",
			"material_variance_percent",
			"operation_variance",
			"operation_variance_percent",
			"total_variance",
			"variance_percent",
			"time_variance_mins",
			"time_variance_percent",
			"cost_per_unit_variance",
			"cost_per_unit_variance_percent",
		];

		if (data && variance_fields.includes(column.fieldname)) {
			const raw = flt(data[column.fieldname]);
			if (raw > 0) value = `<span style="color: var(--red-500)">${value}</span>`;
			else if (raw < 0) value = `<span style="color: var(--green-600)">${value}</span>`;
		}

		return value;
	},
};
