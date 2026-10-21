import unittest
from unittest.mock import patch
import frappe
from mobile_app import brand

class TestBrand(unittest.TestCase):
    def setUp(self):
        frappe.local.mobile_app_brand_registry = None
        brand.registry()

    def tearDown(self):
        frappe.local.mobile_app_brand_registry = None

    def test_exact_identity_namespaces(self):
        self.assertEqual(brand.identity_brand("gid://shopify/Customer/123"), "Siya Ayurveda")
        self.assertEqual(brand.identity_brand("seedfit:gid://shopify/Customer/123"), "Seedfit")
        for value in ("123", "unknown", "other:gid://shopify/Customer/123", "seedfit:garbage", None):
            self.assertEqual(brand.identity_brand(value), "")

    def test_support_conflicts_remain_unclassified(self):
        with patch.object(brand, "linked_brand", return_value="Seedfit"):
            self.assertEqual(brand.resolve(frappe._dict(doctype="Support Ticket", custom_mobile_app="Siya Ayurveda")), "")

    def test_shared_patient_does_not_determine_invoice_brand(self):
        with patch.object(brand, "linked_brand", return_value="") as lookup:
            self.assertEqual(brand.resolve(frappe._dict(doctype="Sales Invoice", patient="same-patient")), "")
            lookup.assert_called_once_with("Patient Encounter", None)

    def test_ambiguous_encounter_is_unclassified(self):
        with patch.object(frappe, "get_all", return_value=[{brand.FIELD:"Siya Ayurveda"},{brand.FIELD:"Seedfit"}]):
            self.assertEqual(brand.resolve(frappe._dict(doctype="Patient Encounter", name="test")), "")

    def test_channel_identity(self):
        for channel, expected in (("Seedfit Patient App", "Seedfit"), ("Siya Ayurveda Patient App", "Siya Ayurveda"), ("WhatsApp", "")):
            self.assertEqual(brand.resolve(frappe._dict(doctype="Chat Conversation", channel_account=channel)), expected)

    def test_new_user_is_stamped_and_rollback(self):
        frappe.db.savepoint("brand_fixture")
        try:
            doc = frappe.get_doc(dict(doctype="Mobile App User", external_id="seedfit:gid://shopify/Customer/999999999987654", full_name="Brand filter test", is_active=1)).insert()
            self.assertEqual(doc.get(brand.FIELD), "Seedfit")
            self.assertEqual(frappe.db.get_value(doc.doctype, doc.name, brand.FIELD), "Seedfit")
        finally:
            frappe.db.rollback(save_point="brand_fixture")

    def test_counts_use_permission_filtered_list(self):
        with patch.object(frappe.db, "exists", return_value=True), patch.object(frappe, "has_permission", return_value=True), patch.object(frappe, "get_list", return_value=[frappe._dict(total=3)]) as query:
            result = brand.counts("Seedfit")
            self.assertEqual(result["Mobile App User"], 3)
            self.assertEqual(query.call_args.kwargs["filters"], {brand.FIELD:"Seedfit"})

    def test_inaccessible_counts_are_not_disclosed(self):
        with patch.object(frappe.db, "exists", return_value=True), patch.object(frappe, "has_permission", return_value=False), patch.object(frappe, "get_list") as query:
            self.assertTrue(all(v is None for v in brand.counts().values()))
            query.assert_not_called()

    def test_new_brand_drives_identity_channel_and_user_without_code_changes(self):
        frappe.db.savepoint("brand_master_fixture")
        try:
            record = frappe.get_doc(dict(doctype="Mobile App Brand", brand_name="Test Third App",
                app_id="test-third-app", customer_id_prefix="test-third-app:gid://shopify/Customer/",
                chat_channel_account="Test Third App Channel")).insert()
            self.assertIn(record.name, brand.get_brands())
            account = "test-third-app:gid://shopify/Customer/999999999876543"
            self.assertEqual(brand.identity_brand(account), record.name)
            self.assertEqual(brand.label("test-third-app"), record.name)
            self.assertEqual(brand.resolve(frappe._dict(doctype="Chat Conversation", channel_account="Test Third App Channel")), record.name)
            user = frappe.get_doc(dict(doctype="Mobile App User", external_id=account,
                full_name="Third brand test", is_active=1)).insert()
            self.assertEqual(user.get(brand.FIELD), record.name)
            record.app_id = "different-id"
            with self.assertRaises(frappe.ValidationError):
                record.save()
        finally:
            frappe.db.rollback(save_point="brand_master_fixture")
            frappe.local.mobile_app_brand_registry = None

    def test_duplicate_namespace_and_reserved_name_rejected(self):
        for values in (
            dict(brand_name="Duplicate Namespace Test", app_id="duplicate-test", customer_id_prefix="seedfit:gid://shopify/Customer/"),
            dict(brand_name="Unclassified", app_id="reserved-test"),
        ):
            with self.assertRaises(frappe.ValidationError):
                frappe.get_doc(dict(doctype="Mobile App Brand", **values)).insert()

    def test_display_brand_fields_link_to_master(self):
        for typ in brand.DOCTYPES:
            if frappe.db.exists("DocType", typ):
                field = frappe.get_meta(typ).get_field(brand.FIELD)
                self.assertEqual(field.fieldtype, "Link")
                self.assertEqual(field.options, "Mobile App Brand")
