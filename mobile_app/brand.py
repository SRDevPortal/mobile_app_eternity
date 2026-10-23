"""Display-only app provenance. Never used to grant record access."""
import re
import frappe
from frappe import _

FIELD = "custom_app_brand"
DEFAULT_BRANDS = (
    dict(brand_name="Siya Ayurveda", app_id="siya-ayurveda", customer_id_prefix="gid://shopify/Customer/", chat_channel_account="Siya Ayurveda Patient App"),
    dict(brand_name="Seedfit", app_id="seedfit", customer_id_prefix="seedfit:gid://shopify/Customer/", chat_channel_account="Seedfit Patient App"),
)
DOCTYPES = ("Mobile App User", "Mobile App Appointment", "Patient Encounter",
            "Sales Invoice", "Support Ticket", "App Support Ticket", "Siya Mobile Record", "Chat Conversation")


def registry():
    rows = getattr(frappe.local, "mobile_app_brand_registry", None)
    if rows is None:
        rows = frappe.get_all("Mobile App Brand", fields=["name", "app_id", "customer_id_prefix", "chat_channel_account"], order_by="name")
        frappe.local.mobile_app_brand_registry = rows
    return rows


def brand_names():
    return [row.name for row in registry()]


def boot_session(bootinfo):
    bootinfo.mobile_app_brands = brand_names()


@frappe.whitelist()
def get_brands():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)
    # Only public brand labels are returned, never account credentials or records.
    return brand_names()


def identity_brand(value):
    value = str(value or "").strip()
    matches = [row.name for row in registry() if row.customer_id_prefix
               and re.fullmatch(re.escape(row.customer_id_prefix) + r"[0-9]+", value)]
    return matches[0] if len(matches) == 1 else ""


def label(value):
    value = str(value or "").strip().lower()
    matches = [row.name for row in registry() if value in (row.name.lower(), row.app_id.lower())]
    return matches[0] if len(matches) == 1 else ""


def agreed(values):
    found = {v for v in values if v in brand_names()}
    return next(iter(found)) if len(found) == 1 else ""

def linked_brand(doctype, name):
    if not name or not frappe.db.exists("DocType", doctype) or not frappe.get_meta(doctype).has_field(FIELD):
        return ""
    return frappe.db.get_value(doctype, name, FIELD) or ""

def resolve(doc):
    typ = doc.doctype
    if typ == "Mobile App User":
        return identity_brand(doc.get("external_id"))
    if typ == "Siya Mobile Record":
        return identity_brand(doc.get("account"))
    if typ == "Chat Conversation":
        matches = [row.name for row in registry() if row.chat_channel_account and row.chat_channel_account == doc.get("channel_account")]
        return matches[0] if len(matches) == 1 else ""
    if typ in ("Support Ticket", "App Support Ticket"):
        return agreed([label(doc.get("custom_mobile_app")), identity_brand(doc.get("user_id")),
                       linked_brand("Mobile App User", doc.get("custom_mobile_app_user") or doc.get("mobile_app_user"))])
    if typ == "Mobile App Appointment":
        return linked_brand("Mobile App User", doc.get("mobile_app_user"))
    if typ == "Patient Encounter":
        # A shared Patient is not app provenance. Only explicit booking links count.
        rows = frappe.get_all("Mobile App Appointment", filters={"patient_encounter": doc.name},
                              fields=[FIELD], limit_page_length=0) if doc.name else []
        return agreed([row.get(FIELD) for row in rows])
    if typ == "Sales Invoice":
        return linked_brand("Patient Encounter", doc.get("source_encounter"))
    return ""

def stamp(doc, method=None):
    if doc.meta.has_field(FIELD):
        doc.set(FIELD, resolve(doc))

def sync_encounter(doc, method=None):
    """Bookings can acquire their encounter link after creation."""
    names = {doc.get("patient_encounter")}
    previous = doc.get_doc_before_save()
    if previous:
        names.add(previous.get("patient_encounter"))
    for name in names - {None, ""}:
        if frappe.db.exists("Patient Encounter", name):
            encounter = frappe.get_doc("Patient Encounter", name)
            value = resolve(encounter)
            if encounter.get(FIELD) != value:
                frappe.db.set_value("Patient Encounter", name, FIELD, value, update_modified=False)
                if frappe.get_meta("Sales Invoice").has_field("source_encounter"):
                    for invoice in frappe.get_all("Sales Invoice", filters={"source_encounter": name}, pluck="name"):
                        frappe.db.set_value("Sales Invoice", invoice, FIELD, value, update_modified=False)

def prepare_invoice_brand_schema():
    """Repair metadata left by a failed install before core schema sync runs.

    No invoice data or existing invoice column is altered here. Frappe DDL can
    commit Custom Field metadata before adding the physical column fails.
    """
    if not frappe.db.exists("DocType", "Sales Invoice"):
        return
    field = frappe.db.get_value("Custom Field", {"dt": "Sales Invoice", "fieldname": FIELD},
                                ["name", "fieldtype"], as_dict=True)
    if field and field.fieldtype == "Link" and not frappe.db.has_column("Sales Invoice", FIELD):
        frappe.db.set_value("Custom Field", field.name,
                            {"fieldtype": "Small Text", "options": "", "search_index": 0},
                            update_modified=False)
        frappe.clear_cache(doctype="Sales Invoice")


def brand_field_definition(doctype, insert_after, existing=None):
    # A crowded Sales Invoice can exceed MariaDB's 65,535-byte logical row
    # limit with another VARCHAR(140). TEXT has only a small inline footprint.
    # Retain successfully installed Link columns; never rebuild their tables.
    text_storage = doctype == "Sales Invoice" and not (
        existing and existing.fieldtype == "Link" and frappe.db.has_column(doctype, FIELD)
    )
    return dict(fieldname=FIELD, label="App Brand", fieldtype="Small Text" if text_storage else "Link",
                options="" if text_storage else "Mobile App Brand", insert_after=insert_after,
                read_only=1, in_list_view=1, in_standard_filter=1, search_index=0 if text_storage else 1,
                description="Source app. Blank means no unambiguous app origin is recorded.")


def setup():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    for defaults in DEFAULT_BRANDS:
        if not frappe.db.exists("Mobile App Brand", defaults["brand_name"]):
            frappe.get_doc(dict(doctype="Mobile App Brand", **defaults)).insert(ignore_permissions=True)
    frappe.local.mobile_app_brand_registry = None
    definitions = {}
    for doctype in DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            meta = frappe.get_meta(doctype)
            existing = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": FIELD}, ["name", "fieldtype"], as_dict=True)
            if existing and existing.fieldtype == "Select":
                # Preserve legacy Select metadata until a separately validated
                # conversion; never scan business tables during installation.
                continue
            definitions[doctype] = [brand_field_definition(doctype, meta.fields[0].fieldname, existing)]
    create_custom_fields(definitions, update=True)
    repair_missing_brand_columns()
    # Historical records are updated only by an administrator-started job.
    from mobile_app.brand_backfill import ensure_state
    ensure_state()


def repair_missing_brand_columns():
    """Finish DDL left incomplete after Custom Field metadata was committed.

    create_custom_fields can skip unchanged definitions on retry. Check the
    physical schema separately; this deployment-only operation never backfills
    historical brand values. Already synchronized tables incur no DDL.
    """
    prepare_invoice_brand_schema()
    repaired = []
    for doctype in DOCTYPES:
        if not frappe.db.exists("DocType", doctype):
            continue
        frappe.clear_cache(doctype=doctype)
        if not frappe.get_meta(doctype).has_field(FIELD):
            continue
        # A prior failed ALTER must not be concealed by cached column metadata.
        frappe.cache.hdel("table_columns", "tab" + doctype)
        if not frappe.db.has_column(doctype, FIELD):
            frappe.db.updatedb(doctype)
            frappe.cache.hdel("table_columns", "tab" + doctype)
            if not frappe.db.has_column(doctype, FIELD):
                raise RuntimeError(f"Brand column repair did not complete for {doctype}")
            repaired.append(doctype)
    return repaired

def backfill():
    """Compatibility entry point: request background work, never scan inline."""
    from mobile_app.brand_backfill import start
    return start()

@frappe.whitelist()
def counts(brand=""):
    if brand not in ("", "Unclassified", *brand_names()):
        frappe.throw(_("Invalid app brand"))
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)
    filters = {FIELD: ["is", "not set"]} if brand == "Unclassified" else ({FIELD: brand} if brand else {})
    result = {}
    for typ in DOCTYPES:
        if not frappe.db.exists("DocType", typ) or not frappe.has_permission(typ, "read"):
            result[typ] = None
            continue
        rows = frappe.get_list(typ, filters=filters, fields=["count(name) as total"], limit_page_length=1)
        result[typ] = rows[0].total if rows else 0
    return result


@frappe.whitelist()
def refresh_record_brands():
    frappe.only_for("System Manager")
    frappe.local.mobile_app_brand_registry = None
    return backfill()
