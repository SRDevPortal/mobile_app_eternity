"""Regression coverage for installation on wide Sales Invoice tables."""
import unittest
from unittest.mock import patch

import frappe
from frappe.database.schema import get_definition
from mobile_app import brand
from mobile_app.mobileapp.doctype.mobile_app_brand.mobile_app_brand import MobileAppBrand


class TestBrandSchema(unittest.TestCase):
    def test_new_invoice_uses_text_and_other_documents_keep_links(self):
        field = brand.brand_field_definition("Sales Invoice", "name")
        self.assertEqual(get_definition(field["fieldtype"]), "text")
        self.assertEqual(field["search_index"], 0)
        self.assertTrue(field["read_only"])
        for doctype in set(brand.DOCTYPES) - {"Sales Invoice"}:
            self.assertEqual(brand.brand_field_definition(doctype, "name")["fieldtype"], "Link")

    def test_successful_link_install_is_not_converted(self):
        existing = frappe._dict(fieldtype="Link")
        with patch.object(frappe.db, "has_column", return_value=True):
            self.assertEqual(brand.brand_field_definition("Sales Invoice", "name", existing)["fieldtype"], "Link")
        with patch.object(frappe.db, "has_column", return_value=False):
            self.assertEqual(brand.brand_field_definition("Sales Invoice", "name", existing)["fieldtype"], "Small Text")
        with patch.object(frappe.db, "has_column", return_value=True):
            self.assertEqual(brand.brand_field_definition("Sales Invoice", "name", frappe._dict(fieldtype="Small Text"))["fieldtype"], "Small Text")

    def test_partial_install_metadata_repaired_without_touching_invoices(self):
        field = frappe._dict(name="Sales Invoice-custom_app_brand", fieldtype="Link")
        with patch.object(frappe.db, "exists", return_value=True), \
                patch.object(frappe.db, "get_value", return_value=field), \
                patch.object(frappe.db, "has_column", return_value=False), \
                patch.object(frappe.db, "set_value") as update, \
                patch.object(frappe, "clear_cache"):
            brand.prepare_invoice_brand_schema()
        update.assert_called_once_with("Custom Field", field.name,
            {"fieldtype": "Small Text", "options": "", "search_index": 0}, update_modified=False)

    def test_preflight_leaves_existing_columns_and_legacy_fields_untouched(self):
        for fieldtype, present in (("Link", True), ("Select", False), ("Small Text", True)):
            with patch.object(frappe.db, "exists", return_value=True), \
                    patch.object(frappe.db, "get_value", return_value=frappe._dict(fieldtype=fieldtype)), \
                    patch.object(frappe.db, "has_column", return_value=present), \
                    patch.object(frappe.db, "set_value") as update:
                brand.prepare_invoice_brand_schema()
                update.assert_not_called()

    def test_brand_used_by_invoice_cannot_be_deleted(self):
        with patch.object(frappe.db, "exists", return_value=True), \
                patch.object(frappe.db, "has_column", return_value=True):
            with self.assertRaises(frappe.LinkExistsError):
                MobileAppBrand.on_trash(frappe._dict(name="Seedfit"))

    def test_mariadb_wide_row_rejects_link_but_accepts_text_with_filtering(self):
        if frappe.db.db_type != "mariadb":
            self.skipTest("MariaDB row-size regression")
        table = "brand_row_limit_" + frappe.generate_hash(length=10)
        columns = ", ".join(f"c{i} varchar(140)" for i in range(116))
        connection = frappe.db.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"CREATE TEMPORARY TABLE {table} ({columns}) ENGINE=InnoDB ROW_FORMAT=DYNAMIC CHARACTER SET utf8mb4")
                with self.assertRaises(Exception) as caught:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN custom_app_brand varchar(140)")
                self.assertEqual(caught.exception.args[0], 1118)
                field = brand.brand_field_definition("Sales Invoice", "name")
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN custom_app_brand {get_definition(field['fieldtype'])}")
                cursor.execute(f"INSERT INTO {table} (custom_app_brand) VALUES (%s), (%s), (NULL)", ("Siya Ayurveda", "Seedfit"))
                for value in ("Siya Ayurveda", "Seedfit"):
                    cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE custom_app_brand=%s", (value,))
                    self.assertEqual(cursor.fetchone()[0], 1)
                cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE custom_app_brand IS NULL")
                self.assertEqual(cursor.fetchone()[0], 1)
        finally:
            # Temporary table disappears with this separate connection, without
            # committing any application/test transaction.
            connection.close()
