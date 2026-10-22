import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
import frappe
from mobile_app import brand, brand_backfill as job


class TestBrandBackfill(unittest.TestCase):
    def state(self, **kwargs):
        state = frappe._dict(doctype_index=0, last_name="", processed=0, changed=0, status="Pending")
        state.update(kwargs)
        state.save = Mock()
        return state

    @contextmanager
    def rows(self, names):
        def get_all(typ, filters, **kwargs):
            cursor = filters.get("name", [None, ""])[1]
            return [n for n in names if n > cursor][:kwargs["limit_page_length"]]
        with patch.object(brand, "DOCTYPES", ("Mobile App User",)),              patch.object(frappe.db, "exists", return_value=True),              patch.object(frappe, "get_meta", return_value=Mock(has_field=lambda field: True)),              patch.object(frappe, "get_all", side_effect=get_all) as query,              patch.object(frappe, "get_doc", side_effect=lambda typ, name, **kw: frappe._dict(name=name)),              patch.object(brand, "resolve", return_value="Seedfit"),              patch.object(frappe.db, "set_value") as update,              patch.object(job, "monotonic", return_value=0):
            yield query, update

    def test_caps_batches_and_resumes_with_keyset(self):
        state = self.state()
        with self.rows([f"test-{i:04}" for i in range(205)]) as (query, update):
            job.process_batch(state)
            self.assertEqual(state.processed, 200)
            self.assertEqual(state.last_name, "test-0199")
            self.assertEqual(state.status, "Running")
            self.assertEqual(update.call_count, 200)
            job.process_batch(state)
            self.assertEqual(state.processed, 205)
            self.assertEqual(state.changed, 205)
            self.assertEqual(state.status, "Completed")
            self.assertEqual(query.call_args_list[1].kwargs["filters"], {"name": [">", "test-0199"]})
            self.assertNotIn("start", query.call_args.kwargs)

    def test_time_budget_checkpoints_early(self):
        state = self.state()
        with self.rows(["a", "b"]), patch.object(job, "monotonic", side_effect=[0, 11, 11]):
            job.process_batch(state)
        self.assertEqual(state.last_name, "a")
        self.assertEqual(state.processed, 1)
        self.assertEqual(state.status, "Running")

    def test_install_does_not_backfill_or_scan_business_records(self):
        with patch.object(brand, "repair_missing_brand_columns") as repair, patch.object(frappe.db, "exists", return_value=True),              patch.object(frappe.db, "get_value", return_value=None),              patch.object(frappe, "get_meta", return_value=frappe._dict(fields=[frappe._dict(fieldname="name")])),              patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields"),              patch.object(job, "ensure_state") as ensure,              patch.object(frappe, "get_all") as scan, patch.object(brand, "backfill") as fill:
            brand.setup()
        ensure.assert_called_once()
        scan.assert_not_called()
        fill.assert_not_called()
        repair.assert_called_once()

    def test_legacy_select_preserved_without_data_scan(self):
        with patch.object(brand, "repair_missing_brand_columns"), patch.object(frappe.db, "exists", return_value=True),              patch.object(frappe.db, "get_value", return_value=frappe._dict(fieldtype="Select")),              patch.object(frappe, "get_meta"),              patch("frappe.custom.doctype.custom_field.custom_field.create_custom_fields") as fields,              patch.object(job, "ensure_state"), patch.object(frappe, "get_all") as scan:
            brand.setup()
        fields.assert_called_once_with({}, update=True)
        scan.assert_not_called()

    def test_failed_batch_rolls_back_and_keeps_previous_cursor(self):
        state = self.state(last_name="previous")
        with patch.object(job, "maintenance_lock") as lock,              patch.object(frappe, "get_doc", return_value=state),              patch.object(frappe.db, "sql", return_value=[(50,)]),              patch.object(job, "process_batch", side_effect=RuntimeError("interrupted")),              patch.object(frappe.db, "rollback") as rollback,              patch.object(frappe.db, "commit") as commit,              patch.object(frappe.db, "set_value") as update, patch.object(frappe, "log_error"):
            lock.return_value.__enter__.return_value = True
            with self.assertRaises(RuntimeError):
                job.run_batch()
        rollback.assert_called_once()
        commit.assert_called_once()
        self.assertEqual(update.call_args.args[2]["status"], "Failed")
        self.assertNotIn("last_name", update.call_args.args[2])

    def test_duplicate_worker_does_no_work(self):
        with patch.object(job, "maintenance_lock") as lock, patch.object(job, "process_batch") as process:
            lock.return_value.__enter__.return_value = False
            job.run_batch()
            process.assert_not_called()

    def test_failed_run_resumes_without_resetting_progress(self):
        state = self.state(status="Failed", last_name="previous", processed=200)
        with patch.object(job, "maintenance_lock") as lock,              patch.object(frappe, "only_for"), patch.object(job, "ensure_state"),              patch.object(frappe, "get_doc", return_value=state),              patch.object(frappe.db, "commit"), patch.object(job, "enqueue") as enqueue:
            lock.return_value.__enter__.return_value = True
            job.start()
        self.assertEqual(state.last_name, "previous")
        self.assertEqual(state.processed, 200)
        self.assertEqual(state.status, "Pending")
        enqueue.assert_called_once()

    def test_scheduler_recovers_pending_jobs_but_not_completed(self):
        with patch.object(frappe.db, "exists", return_value=True),              patch.object(frappe.db, "get_value", side_effect=["Running", "Completed"]),              patch.object(job, "enqueue") as enqueue:
            job.schedule()
            job.schedule()
        enqueue.assert_called_once()

    def test_start_requires_system_manager(self):
        with patch.object(frappe, "only_for", side_effect=frappe.PermissionError),              patch.object(job, "ensure_state") as ensure:
            with self.assertRaises(frappe.PermissionError):
                job.start()
        ensure.assert_not_called()

    def test_data_and_checkpoint_rollback_together(self):
        frappe.db.savepoint("brand_batch_atomic")
        try:
            state = frappe.get_doc(dict(doctype=job.DOCTYPE, name="test-atomic-brand-batch", status="Pending")).insert(ignore_permissions=True)
            user = frappe.get_doc(dict(doctype="Mobile App User",
                external_id="seedfit:gid://shopify/Customer/999999999899991",
                full_name="Batch atomic test", is_active=1)).insert()
            frappe.db.set_value(user.doctype, user.name, brand.FIELD, "", update_modified=False)
            frappe.db.savepoint("brand_batch_before")
            real_get_all = frappe.get_all
            def get_all(typ, **kwargs):
                return [user.name] if typ == "Mobile App User" else real_get_all(typ, **kwargs)
            with patch.object(brand, "DOCTYPES", ("Mobile App User",)),                  patch.object(frappe, "get_all", side_effect=get_all),                  patch.object(job, "BATCH_SIZE", 1):
                job.process_batch(state)
            self.assertEqual(frappe.db.get_value(user.doctype, user.name, brand.FIELD), "Seedfit")
            self.assertEqual(frappe.db.get_value(job.DOCTYPE, state.name, "processed"), 1)
            frappe.db.rollback(save_point="brand_batch_before")
            self.assertEqual(frappe.db.get_value(user.doctype, user.name, brand.FIELD), "")
            self.assertEqual(frappe.db.get_value(job.DOCTYPE, state.name, "processed"), 0)
        finally:
            frappe.db.rollback(save_point="brand_batch_atomic")
