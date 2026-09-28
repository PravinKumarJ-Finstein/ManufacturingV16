// Copyright (c) 2026, Finstein and contributors
frappe.query_reports["Sales Order Purchase Coverage"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
		 default: frappe.defaults.get_user_default("Company")},
		{fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order"},
		{fieldname: "item_code", label: __("Raw Material"), fieldtype: "Link", options: "Item"},
		{fieldname: "status", label: __("Status"), fieldtype: "Select",
		 options: ["", "In Stock", "Short", "Ordered", "Partially Ordered", "Received", "Exception", "Superseded"]},
		{fieldname: "from_date", label: __("Delivery From"), fieldtype: "Date"},
		{fieldname: "to_date", label: __("Delivery To"), fieldtype: "Date"},
	],
};
