# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt
"""Bring in the custom fields this app adds to core doctypes.

The fields themselves are **not** written here. They live as Customize Form exports, one
JSON file per doctype, in ``manufacturing_plus/manufacturing_plus/custom/``. Each file
carries ``sync_on_migrate``, so Frappe loads it on every ``bench migrate`` and on install —
and, unlike building the fields from a dictionary in code, that path *updates* a field that
is already there instead of leaving the old definition in place. Changing a label, an order
or a property is then a change to the JSON and a migrate.

To change a field: edit it with **Customize Form** on a site, export it back over the file
(``bench --site <site> export-customizations --doctype "<Doctype>" --module "Manufacturing Plus"``),
or edit the JSON by hand.
"""

import frappe


def create_custom_fields() -> None:
	"""Kept as the app's entry point; the work is Frappe's customization sync."""
	from frappe.modules.utils import sync_customizations

	sync_customizations("manufacturing_plus")
	frappe.clear_cache()
