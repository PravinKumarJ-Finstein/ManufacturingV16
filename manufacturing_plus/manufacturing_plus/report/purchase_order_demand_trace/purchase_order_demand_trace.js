// Copyright (c) 2026, Finstein and contributors
frappe.query_reports["Purchase Order Demand Trace"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
		 default: frappe.defaults.get_user_default("Company")},
		{fieldname: "purchase_order", label: __("Purchase Order"), fieldtype: "Link", options: "Purchase Order"},
		{fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier"},
		{fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order"},
	],
};
