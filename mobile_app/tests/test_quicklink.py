"""Run on a test site; every test rolls back its synthetic records."""
from unittest import TestCase
from datetime import timedelta
import frappe
from mobile_app.api import quicklink as q


class TestQuickLink(TestCase):
    def setUp(self):
        self.previous_user = frappe.session.user
        frappe.set_user("Administrator")
        self.suffix = str(frappe.utils.now_datetime().timestamp()).replace('.', '')
        self.brands = []
        self.users = []
        for index, brand_name in enumerate(("Siya Ayurveda", "Seedfit")):
            b = frappe.get_doc("Mobile App Brand", brand_name)
            b.db_set({"quicklink_enabled": 1, "quicklink_system_prompt": f"You are brand {index}."})
            u = frappe.get_doc({"doctype": "Mobile App User", "external_id": b.customer_id_prefix + self.suffix + str(index),
                "is_active": 1, "full_name": "QuickLink synthetic test"}).insert(ignore_permissions=True)
            self.brands.append(b); self.users.append(u)
        self.app = self.brands[0].app_id
        self.user = self.users[0].name
        self.chat = self.call("open_session")["conversation_id"]

    def tearDown(self):
        frappe.db.rollback()
        frappe.set_user(self.previous_user)

    def call(self, action, **kw):
        return q.dispatch(self.app, self.user, action, dict(conversation=getattr(self, "chat", None), **kw))

    def send(self, client="one", message="Hello"):
        return self.call("send_message", client_message_id=client, message=message)

    def test_brand_owner_cursor_and_guest_isolation(self):
        other_user = frappe.get_doc({"doctype": "Mobile App User", "external_id": self.brands[0].customer_id_prefix + self.suffix + "999",
            "is_active": 1, "full_name": "Other synthetic user"}).insert(ignore_permissions=True)
        with self.assertRaises(frappe.PermissionError):
            q.dispatch(self.app, other_user.name, "get_messages", {"conversation": self.chat})
        with self.assertRaises(frappe.PermissionError):
            q.dispatch(self.brands[1].app_id, self.user, "get_messages", {"conversation": self.chat})
        other = q.dispatch(self.brands[1].app_id, self.users[1].name, "open_session")
        with self.assertRaises(frappe.PermissionError):
            self.call("get_messages", after="foreign")
        with self.assertRaises(frappe.PermissionError):
            q.dispatch(self.app, self.user, "get_messages", {"conversation": other["conversation_id"]})
        frappe.set_user("Guest")
        with self.assertRaises(frappe.PermissionError): q.desk(self.chat)
        for f, args in [(q.dispatch, (self.app, self.user, "open_session")), (q.claim, (self.app,)), (q.finish, (self.app, "x", "x"))]:
            with self.assertRaises(frappe.PermissionError): f(*args)

    def test_retry_job_lease_and_latest_prompt(self):
        first = self.send(); again = self.send()
        self.assertTrue(again["duplicate"]); self.assertEqual(first["message_id"], again["message_id"])
        with self.assertRaises(frappe.ValidationError): self.send(message="Changed")
        self.brands[0].db_set("quicklink_system_prompt", "Updated prompt")
        job = q.claim(self.app)
        self.assertEqual(job["prompts"]["system_prompt"], "Updated prompt")
        self.assertIsNone(q.claim(self.app))
        self.assertFalse(q.finish(self.app, job["message_id"], "wrong", "Bad")["accepted"])
        self.assertTrue(q.finish(self.app, job["message_id"], job["lease"], "Hello back")["accepted"])
        self.assertFalse(q.finish(self.app, job["message_id"], job["lease"], "Duplicate")["accepted"])
        messages = self.call("get_messages")["messages"]
        self.assertEqual([r["message"] for r in messages], ["Hello", "Hello back"])
        self.assertEqual(len(self.call("get_messages", after=first["message_id"])["messages"]), 1)

    def test_expired_lease_and_provider_failure_are_bounded(self):
        self.send(); first = q.claim(self.app)
        frappe.db.set_value(q.M, first["message_id"], "lease_until", frappe.utils.now_datetime()-timedelta(seconds=1))
        second = q.claim(self.app)
        self.assertNotEqual(first["lease"], second["lease"])
        self.assertFalse(q.finish(self.app, first["message_id"], first["lease"], "Old reply")["accepted"])
        self.assertTrue(q.finish(self.app, second["message_id"], second["lease"])["retry"])
        frappe.db.set_value(q.M, first["message_id"], "next_attempt", frappe.utils.now_datetime()-timedelta(seconds=1))
        third = q.claim(self.app)
        q.finish(self.app, third["message_id"], third["lease"])
        self.assertIsNone(q.claim(self.app))
        self.assertEqual(frappe.db.get_value(q.M, first["message_id"], "job_status"), "Failed")
        self.assertEqual(self.call("get_messages")["messages"][-1]["sender_type"], "System")

    def test_handoff_cancels_ai_and_mirrors_both_directions(self):
        self.send(); job = q.claim(self.app)
        ticket = self.call("escalate")
        self.assertEqual(self.call("escalate")["ticket"], ticket["ticket"])
        self.assertFalse(q.finish(self.app, job["message_id"], job["lease"], "Late AI")["accepted"])
        self.send("human", "Question for agent")
        self.assertEqual(frappe.db.count("Support Ticket Message", {"ticket": ticket["ticket"]}), 1)
        result = q.desk(self.chat, "Agent reply")
        self.assertEqual(result["messages"][-1]["message"], "Agent reply")
        self.assertEqual(result["messages"][-1]["sender_type"], "Agent")
        self.assertFalse(result["ai_ready"]); self.assertTrue(result["can_send"])
        self.assertNotIn("Late AI", [m["message"] for m in result["messages"]])
        frappe.db.set_value("Support Ticket", ticket["ticket"], "status", "Closed")
        self.assertFalse(self.call("get_messages")["can_send"])

    def test_new_chat_retries_and_disabled_or_inactive_accounts(self):
        self.send(); job = q.claim(self.app)
        new = self.call("new_session")
        self.assertEqual(new["conversation_id"], self.call("new_session")["conversation_id"])
        self.assertEqual(new["conversation_id"], self.call("open_session")["conversation_id"])
        self.assertFalse(q.finish(self.app, job["message_id"], job["lease"], "Late")["accepted"])
        self.brands[0].db_set("quicklink_enabled", 0)
        self.assertFalse(self.call("open_session")["ai_ready"])
        self.users[0].db_set("is_active", 0)
        with self.assertRaises(frappe.PermissionError): self.call("open_session")

    def test_no_patient_profile_is_needed_and_no_medical_record_is_sent(self):
        self.send(); job = q.claim(self.app)
        self.assertEqual(set(job), {"message_id", "lease", "brand", "app_id", "prompts", "history", "cards"})
        self.assertEqual(self.call("get_messages")["identity_status"], "Unverified")

    def test_history_pages_do_not_skip_equal_timestamp_messages(self):
        convo = q._lock(q.C, self.chat)
        rows = [q._message(convo, "Agent", f"Reply {i}") for i in range(105)]
        self.assertEqual(len(self.call("get_messages")["messages"]), 100)
        page = self.call("get_messages", after=rows[0].name)["messages"]
        tail = self.call("get_messages", after=page[-1]["id"])["messages"]
        self.assertEqual(len(page), 100)
        self.assertEqual([r["id"] for r in page + tail], [r.name for r in rows[1:]])
