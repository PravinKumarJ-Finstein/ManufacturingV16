// Copyright (c) 2026, Finstein and contributors
frappe.query_reports["Yield Summary"] = {
	filters: [
		{fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
		 default: frappe.defaults.get_user_default("Company")},
		{fieldname: "work_order", label: __("Work Order"), fieldtype: "Link", options: "Work Order"},
		{fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item"},
		{fieldname: "from_date", label: __("From Date"), fieldtype: "Date"},
		{fieldname: "to_date", label: __("To Date"), fieldtype: "Date"},
	],
};
