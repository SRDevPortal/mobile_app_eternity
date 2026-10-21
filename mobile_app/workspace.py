"""Permission-aware navigation for the Mobile App workspace."""
import frappe
from frappe import _
from mobile_app.brand import FIELD

# Primary destinations already have cards or a Manage brands action.
PRIMARY = {"Mobile App User", "Mobile App Appointment", "Support Ticket", "App Support Ticket", "Mobile App Brand"}
# Shared clinical, accounting and chat tools already have their own workspaces.
SHARED = {"Patient Encounter", "Sales Invoice", "Patient", "Healthcare Practitioner", "Diet Chart",
          "Chat Conversation", "Doctor Availability Exception", "Doctor Directory Settings",
          "OPD State Record", "OPD Token Notification"}
RELATED = {"Siya Mobile Record"}


@frappe.whitelist()
def get_related_links():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)
    names = set(frappe.get_all("DocType", filters={"module": "MobileApp", "istable": 0}, pluck="name"))
    names.update(RELATED)
    result = []
    for name in sorted(names - PRIMARY - SHARED):
        if not frappe.db.exists("DocType", name) or not frappe.has_permission(name, "read"):
            continue
        meta = frappe.get_meta(name)
        if meta.istable:
            continue
        result.append(dict(doctype=name, single=bool(meta.issingle),
                           brand_filtered=bool(meta.has_field(FIELD))))
    return result
