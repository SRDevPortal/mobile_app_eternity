"""Resumable, explicitly started app-brand maintenance on the long queue."""
from contextlib import contextmanager
from time import monotonic

import frappe
from frappe import _
from mobile_app import brand

DOCTYPE = "Mobile App Brand Update"
NAME = "record-brands"
BATCH_SIZE = 200
BATCH_SECONDS = 10
JOB_ID = "mobile-app-brand-update"


def ensure_state():
    if not frappe.db.exists(DOCTYPE, NAME):
        frappe.get_doc(dict(doctype=DOCTYPE, name=NAME, status="Idle")).insert(ignore_permissions=True)


@contextmanager
def maintenance_lock():
    # Shared by requests and workers. The job times out before this lease expires.
    lock = frappe.cache.lock(JOB_ID, timeout=240)
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


def enqueue():
    frappe.enqueue(
        "mobile_app.brand_backfill.run_batch", queue="long", timeout=180,
        job_id=JOB_ID, deduplicate=True, enqueue_after_commit=True,
    )


def start():
    frappe.only_for("System Manager")
    with maintenance_lock() as acquired:
        if not acquired:
            return {"status": "Running", "name": NAME}
        ensure_state()
        state = frappe.get_doc(DOCTYPE, NAME)
        if state.status in ("Idle", "Completed"):
            state.doctype_index = state.processed = state.changed = 0
            state.last_name = ""
        state.status = "Pending"
        state.last_error = ""
        state.save(ignore_permissions=True)
        # Publish the checkpoint before releasing the lock. This API is only
        # maintenance, never called from business-document hooks.
        frappe.db.commit()
    enqueue()
    return {"status": "Pending", "name": NAME}


def schedule():
    """One batch per scheduler tick; also recovers a lost/killed queue job."""
    if not frappe.db.exists("DocType", DOCTYPE):
        return
    if frappe.db.get_value(DOCTYPE, NAME, "status") in ("Pending", "Running"):
        enqueue()


def process_batch(state):
    """Update rows and checkpoint in the caller's *same* transaction."""
    started = monotonic()
    checked = 0
    frappe.local.mobile_app_brand_registry = None
    while state.doctype_index < len(brand.DOCTYPES) and checked < BATCH_SIZE:
        typ = brand.DOCTYPES[state.doctype_index]
        if not frappe.db.exists("DocType", typ) or not frappe.get_meta(typ).has_field(brand.FIELD):
            state.doctype_index += 1
            state.last_name = ""
            continue
        # Keyset pagination uses the primary key; no COUNT or growing OFFSET.
        names = frappe.get_all(
            typ, filters={"name": [">", state.last_name]} if state.last_name else {},
            pluck="name", order_by="name asc", limit_page_length=BATCH_SIZE - checked,
        )
        if not names:
            state.doctype_index += 1
            state.last_name = ""
            continue
        for name in names:
            # Read the current row under a lock, avoiding stale overwrites while
            # normal users edit a booking. No save/business hooks are invoked.
            try:
                row = frappe.get_doc(typ, name, for_update=True)
            except frappe.DoesNotExistError:
                row = None
            if row:
                value = brand.resolve(row)
                if (row.get(brand.FIELD) or "") != value:
                    frappe.db.set_value(typ, name, brand.FIELD, value, update_modified=False)
                    state.changed += 1
            state.last_name = name
            state.processed += 1
            checked += 1
            if monotonic() - started >= BATCH_SECONDS:
                break
        if monotonic() - started >= BATCH_SECONDS:
            break
    state.status = "Completed" if state.doctype_index >= len(brand.DOCTYPES) else "Running"
    state.last_error = ""
    state.save(ignore_permissions=True)


def run_batch():
    """Only a background job: release row locks after every bounded batch."""
    with maintenance_lock() as acquired:
        if not acquired:
            return
        state = frappe.get_doc(DOCTYPE, NAME)
        if state.status not in ("Pending", "Running"):
            return
        # Fail promptly on a hot row instead of occupying a worker for 50s.
        old_wait = frappe.db.sql("SELECT @@SESSION.innodb_lock_wait_timeout")[0][0]
        try:
            frappe.db.sql("SET SESSION innodb_lock_wait_timeout = 3")
            process_batch(state)
            frappe.db.commit()
        except Exception:
            # The previous checkpoint survives; no partially updated batch.
            frappe.db.rollback()
            frappe.db.set_value(DOCTYPE, NAME, {
                "status": "Failed",
                "last_error": _("Batch interrupted. Use Refresh record brands to resume. See Error Log for details."),
            })
            frappe.db.commit()
            frappe.log_error(title="Mobile app brand update failed")
            raise
        finally:
            frappe.db.sql("SET SESSION innodb_lock_wait_timeout = %s", (old_wait,))
