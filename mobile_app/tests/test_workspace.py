import unittest
from unittest.mock import patch
import frappe
from mobile_app import workspace


class TestWorkspace(unittest.TestCase):
    def test_links_exclude_child_tables_existing_cards_and_inaccessible_doctypes(self):
        def meta(name):
            return frappe._dict(istable=name == "Child Row", issingle=name == "Settings",
                                has_field=lambda field: name == "Siya Mobile Record")
        with patch.object(frappe, "get_all", return_value=["Mobile App User", "Mobile App Brand", "Child Row", "Settings", "Hidden", "Patient", "Patient Encounter", "Sales Invoice", "Healthcare Practitioner", "Diet Chart", "Chat Conversation"]), \
             patch.object(frappe.db, "exists", return_value=True), \
             patch.object(frappe, "has_permission", side_effect=lambda name, perm: name != "Hidden"), \
             patch.object(frappe, "get_meta", side_effect=meta):
            rows = {row["doctype"]: row for row in workspace.get_related_links()}
            for excluded in ("Mobile App User", "Mobile App Brand", "Child Row", "Hidden", *workspace.SHARED):
                self.assertNotIn(excluded, rows)
            self.assertTrue(rows["Siya Mobile Record"]["brand_filtered"])
            self.assertFalse(rows["Settings"]["brand_filtered"])
            self.assertTrue(rows["Settings"]["single"])

    def test_live_links_match_metadata_and_read_permissions(self):
        for row in workspace.get_related_links():
            meta = frappe.get_meta(row["doctype"])
            self.assertFalse(meta.istable)
            self.assertTrue(frappe.has_permission(row["doctype"], "read"))
            self.assertEqual(row["brand_filtered"], bool(meta.has_field("custom_app_brand")))
