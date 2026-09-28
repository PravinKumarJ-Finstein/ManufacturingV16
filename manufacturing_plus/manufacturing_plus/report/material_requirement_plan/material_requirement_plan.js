// Copyright (c) 2026, Finstein and contributors
frappe.query_reports["Material Requirement Plan"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
		 default: frappe.defaults.get_user_default("Company")},
		{fieldname: "group_by_item", label: __("Summarise By Item"), fieldtype: "Check", default: 1},
		{fieldname: "item_code", label: __("Raw Material"), fieldtype: "Link", options: "Item"},
		{fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order"},
		{fieldname: "master_production_schedule", label: __("MPS"), fieldtype: "Link",
		 options: "Master Production Schedule"},
		{fieldname: "status", label: __("Status"), fieldtype: "Select",
		 options: ["", "Short", "Exception", "Ordered", "Partially Ordered", "Received", "In Stock"]},
		{fieldname: "include_covered", label: __("Include Covered Lines"), fieldtype: "Check", default: 0},
		{fieldname: "from_date", label: __("Delivery From"), fieldtype: "Date"},
		{fieldname: "to_date", label: __("Delivery To"), fieldtype: "Date"},
	],
};
