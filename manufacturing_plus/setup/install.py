# Copyright (c) 2026, Finstein and contributors
# For license information, please see license.txt

from manufacturing_plus.planning.features import apply_permissions
from manufacturing_plus.setup.custom_fields import create_custom_fields
from manufacturing_plus.setup.defaults import ensure_settings


def after_install():
	create_custom_fields()
	ensure_settings()
	apply_permissions()


def after_migrate():
	create_custom_fields()
	ensure_settings()
	apply_permissions()
