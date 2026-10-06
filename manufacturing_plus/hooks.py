app_name = "manufacturing_plus"
app_title = "Manufacturing Plus"
app_publisher = "Finstein"
app_description = "Auto delivery date and auto purchase"
app_email = "prabakaran.b@finstein.ai"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "manufacturing_plus",
# 		"logo": "/assets/manufacturing_plus/logo.png",
# 		"title": "Manufacturing Plus",
# 		"route": "/manufacturing_plus",
# 		"has_permission": "manufacturing_plus.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/manufacturing_plus/css/manufacturing_plus.css"
# app_include_js = "/assets/manufacturing_plus/js/manufacturing_plus.js"

# include js, css files in header of web template
# web_include_css = "/assets/manufacturing_plus/css/manufacturing_plus.css"
# web_include_js = "/assets/manufacturing_plus/js/manufacturing_plus.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "manufacturing_plus/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# has_permission = {"doctype": "app.permission.has_permission"}

# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "manufacturing_plus/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "manufacturing_plus.utils.jinja_methods",
# 	"filters": "manufacturing_plus.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "manufacturing_plus.install.before_install"
# after_install = "manufacturing_plus.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "manufacturing_plus.uninstall.before_uninstall"
# after_uninstall = "manufacturing_plus.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "manufacturing_plus.utils.before_app_install"
# after_app_install = "manufacturing_plus.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "manufacturing_plus.utils.before_app_uninstall"
# after_app_uninstall = "manufacturing_plus.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "manufacturing_plus.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "manufacturing_plus.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["manufacturing_plus.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"manufacturing_plus.tasks.all"
# 	],
# 	"daily": [
# 		"manufacturing_plus.tasks.daily"
# 	],
# 	"hourly": [
# 		"manufacturing_plus.tasks.hourly"
# 	],
# 	"weekly": [
# 		"manufacturing_plus.tasks.weekly"
# 	],
# 	"monthly": [
# 		"manufacturing_plus.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "manufacturing_plus.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "manufacturing_plus.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "manufacturing_plus.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "manufacturing_plus.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
before_request = ["manufacturing_plus.overrides.mrp_report.apply"]
# after_request = ["manufacturing_plus.utils.after_request"]

# Job Events
# ----------
before_job = ["manufacturing_plus.overrides.mrp_report.apply"]
# after_job = ["manufacturing_plus.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"manufacturing_plus.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# Manufacturing Plus
# ------------------

after_install = "manufacturing_plus.setup.install.after_install"
after_migrate = "manufacturing_plus.setup.install.after_migrate"

doc_events = {
	"Sales Order": {
		"before_validate": "manufacturing_plus.planning.sales_order.set_expected_delivery_dates",
		"before_update_after_submit": "manufacturing_plus.planning.sales_order.recompute_after_submit",
		"on_update_after_submit": "manufacturing_plus.purchasing.events.refresh_after_update_items",
		"on_submit": "manufacturing_plus.purchasing.events.enqueue_auto_purchase",
		"on_cancel": "manufacturing_plus.purchasing.events.release_on_sales_order_cancel",
	},
	"Purchase Order": {
		"on_submit": "manufacturing_plus.purchasing.events.sync_dates_from_purchase_order",
		"on_update_after_submit": "manufacturing_plus.purchasing.events.sync_dates_from_purchase_order",
		"on_cancel": "manufacturing_plus.purchasing.events.release_on_purchase_order_cancel",
	},
	"Purchase Receipt": {
		"on_submit": "manufacturing_plus.purchasing.events.close_demand_on_receipt",
	},
	"Master Production Schedule": {
		"on_trash": "manufacturing_plus.purchasing.cleanup.on_mps_trash",
	},
	"Auto Purchase Run": {
		"on_trash": "manufacturing_plus.purchasing.cleanup.on_run_trash",
	},
	"Work Order": {
		"validate": "manufacturing_plus.shopfloor.work_order.validate_work_order",
		"before_submit": "manufacturing_plus.shopfloor.work_order.apply_pick_list_buffer",
		"on_submit": "manufacturing_plus.purchasing.events.release_reservation_on_work_order",
	},
	"Production Plan": {
		"on_submit": "manufacturing_plus.shopfloor.work_order.track_planned_qty",
		"on_cancel": "manufacturing_plus.shopfloor.work_order.track_planned_qty",
	},
	"Job Card": {
		"validate": "manufacturing_plus.shopfloor.job_card.validate_job_card",
		"on_update": "manufacturing_plus.shopfloor.job_card.update_work_order_status",
	},
	"Pick List": {
		"validate": "manufacturing_plus.shopfloor.pick_list.validate_pick_list",
		"before_save": "manufacturing_plus.shopfloor.pick_list.warn_on_duplicate",
		"before_submit": "manufacturing_plus.shopfloor.spool.validate_spool_allocation",
		"on_submit": [
			"manufacturing_plus.shopfloor.spool.consume_spools",
			"manufacturing_plus.shopfloor.pick_list.create_stock_entry_on_submit",
		],
		"on_cancel": "manufacturing_plus.shopfloor.spool.release_spools",
	},
}

scheduler_events = {
	"daily": [
		"manufacturing_plus.purchasing.tasks.release_expired_reservations",
		"manufacturing_plus.purchasing.tasks.delete_stale_draft_pos",
	],
	"cron": {
		"0 2 * * *": ["manufacturing_plus.shopfloor.cleanup.run_cleanup"],
		"0 7 * * *": ["manufacturing_plus.shopfloor.can_build.run_daily_can_build"],
	},
}

override_doctype_dashboards = {
	"Master Production Schedule": "manufacturing_plus.purchasing.dashboards.master_production_schedule",
}

extend_bootinfo = "manufacturing_plus.planning.features.hide_disabled_doctypes"

has_permission = {
	doctype: "manufacturing_plus.planning.features.has_permission"
	for doctype in [
		"Yield Entry",
		"Job Setup Checklist",
		"Job Setup Verification",
		"Pick List Configuration",
		"MP Item Package",
		"Excess Issue Note",
		"Stores Return",
		"Combo Parts",
		"Can Build Log",
		"Sales Order Material Demand",
		"MPS Stock Reservation",
		"Auto Purchase Run",
		"Auto Purchase Exception",
	]
}

doctype_js = {
	"Sales Order": "public/js/sales_order.js",
	"Work Order": "public/js/work_order.js",
	"Pick List": "public/js/pick_list.js",
	"Purchase Receipt": "public/js/purchase_receipt.js",
}
