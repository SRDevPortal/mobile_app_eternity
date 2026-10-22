import re
import frappe
from frappe import _
from frappe.model.document import Document


class MobileAppBrand(Document):
    def validate(self):
        self.brand_name = (self.brand_name or "").strip()
        self.app_id = (self.app_id or "").strip().lower()
        self.customer_id_prefix = (self.customer_id_prefix or "").strip() or None
        self.chat_channel_account = (self.chat_channel_account or "").strip() or None
        if not self.brand_name or self.brand_name.lower() in ("all brands", "unclassified"):
            frappe.throw(_("Choose a brand name other than All brands or Unclassified."))
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", self.app_id):
            frappe.throw(_("App ID must start with a lowercase letter and contain only letters, numbers, hyphens or underscores."))
        if self.customer_id_prefix and not re.fullmatch(r"(?:[a-z][a-z0-9_-]*:)?gid://shopify/Customer/", self.customer_id_prefix):
            frappe.throw(_("Customer ID Prefix must be gid://shopify/Customer/ or an app namespace followed by :gid://shopify/Customer/."))
        for row in frappe.get_all("Mobile App Brand", fields=["name", "app_id", "customer_id_prefix", "chat_channel_account"]):
            if row.name == self.name:
                continue
            # Names and IDs are both accepted by existing support integrations.
            if {self.brand_name.lower(), self.app_id} & {row.name.lower(), row.app_id.lower()}:
                frappe.throw(_("Brand name or App ID conflicts with an existing brand."))
            for field in ("customer_id_prefix", "chat_channel_account"):
                if self.get(field) and self.get(field) == row.get(field):
                    frappe.throw(_("{0} already belongs to another brand.").format(self.meta.get_label(field)))
        old = self.get_doc_before_save()
        if old and any(self.get(f) != old.get(f) for f in ("brand_name", "app_id", "customer_id_prefix", "chat_channel_account")):
            from mobile_app.brand import DOCTYPES, FIELD
            if any(frappe.db.exists("DocType", dt) and frappe.get_meta(dt).has_field(FIELD)
                   and frappe.db.exists(dt, {FIELD: self.name}) for dt in DOCTYPES):
                frappe.throw(_("This brand is already used by records. Its identity mapping cannot be changed; create a separate brand for a different app."))

    def on_update(self):
        frappe.local.mobile_app_brand_registry = None

    def on_trash(self):
        # TEXT invoice provenance is not covered by Frappe's Link checks.
        from mobile_app.brand import FIELD
        if (frappe.db.exists("DocType", "Sales Invoice")
                and frappe.db.has_column("Sales Invoice", FIELD)
                and frappe.db.exists("Sales Invoice", {FIELD: self.name})):
            frappe.throw(_("This brand is used by Sales Invoices and cannot be deleted."), frappe.LinkExistsError)
        frappe.local.mobile_app_brand_registry = None
