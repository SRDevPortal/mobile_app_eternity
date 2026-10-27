"""Mobile-owned chat. Only the trusted backend may assert a mobile login identity.

Provider calls run on Render, outside ERP transactions. Row locks and expiring
leases make message writes, worker retries and human handoff safe across hosts.
No WA Chat Hub imports, records, hooks or permissions are used here.
"""
import json
from datetime import timedelta
from html import escape

import frappe
from frappe.utils import now_datetime, get_datetime, strip_html
from mobile_app.quicklink_policy import key, owns_external_id, clean_text, can_finish

C = "Mobile App QuickLink Conversation"
M = "Mobile App QuickLink Message"
PROMPTS = ("system_prompt", "business_info", "product_guidance", "handoff_rules", "examples")


def setup():
    if not frappe.db.exists("Role", "Mobile App QuickLink API"):
        frappe.get_doc({"doctype": "Role", "role_name": "Mobile App QuickLink API", "desk_access": 0}).insert(ignore_permissions=True)
    frappe.db.add_index(C, ["brand", "mobile_app_user", "creation"])
    frappe.db.add_index(M, ["conversation", "sequence"])
    frappe.db.add_index(M, ["job_status", "next_attempt"])


def _integration():
    if frappe.session.user == "Guest" or not {"System Manager", "Mobile App QuickLink API"}.intersection(frappe.get_roles()):
        frappe.throw("QuickLink backend access required", frappe.PermissionError)


def _brand(app_id):
    name = frappe.db.get_value("Mobile App Brand", {"app_id": app_id}, "name")
    if not name:
        frappe.throw("Unknown mobile app", frappe.DoesNotExistError)
    return frappe.get_doc("Mobile App Brand", name)


def _context(app_id, user):
    brand = _brand(app_id)
    parent = frappe.get_doc("Mobile App User", user)
    if not parent.is_active or not owns_external_id(brand.customer_id_prefix, parent.external_id):
        frappe.throw("Mobile account does not belong to this brand", frappe.PermissionError)
    return brand, parent


def _lock(doctype, name):
    frappe.db.get_value(doctype, name, "name", for_update=True)
    return frappe.get_doc(doctype, name)


def _owned(name, brand, parent):
    doc = _lock(C, name)
    if doc.brand != brand.name or doc.mobile_app_user != parent.name:
        frappe.throw("Chat not found", frappe.PermissionError)
    return doc


def _message(convo, sender, message, name=None, **extra):
    # Caller holds the conversation lock. Sequence is a stable paging cursor.
    seq = int(convo.message_sequence or 0) + 1
    convo.db_set("message_sequence", seq, update_modified=True)
    doc = frappe.get_doc(dict(doctype=M, conversation=convo.name, sequence=seq,
                             sender_type=sender, message=message, **extra))
    return doc.insert(ignore_permissions=True, set_name=name)


def _rows(convo, after=None, limit=100):
    filters = {"conversation": convo.name}
    if after:
        cursor = frappe.db.get_value(M, {"name": after, "conversation": convo.name}, "sequence")
        if cursor is None:
            frappe.throw("Invalid message cursor", frappe.PermissionError)
        filters["sequence"] = [">", cursor]
    rows = frappe.get_all(M, filters=filters, fields=["name", "sender_type", "message", "cards", "creation", "sequence"],
                         order_by="sequence asc" if after else "sequence desc", limit_page_length=limit)
    return rows if after else list(reversed(rows))


def _payload(convo, brand, after=None):
    human = convo.mode == "Human"
    if human and convo.support_ticket:
        status = frappe.db.get_value("Support Ticket", convo.support_ticket, "status")
        if status in ("Closed", "Resolved"):
            convo.db_set("mode", "Closed")
    return {"conversation_id": convo.name, "status": convo.mode, "mode": convo.mode,
            "identity_status": "Unverified", "profile_required": False,
            "ai_ready": bool(brand.quicklink_enabled and convo.mode == "AI"),
            "can_send": convo.mode == "Human" or (convo.mode == "AI" and bool(brand.quicklink_enabled)),
            "support_ticket": convo.support_ticket,
            "messages": [{"id": r.name, "sender_type": r.sender_type, "message": r.message,
                          "content_type": "Text", "created_at": str(r.creation), "delivery_status": "Delivered",
                          "cards": json.loads(r.cards or "[]")} for r in _rows(convo, after)]}


def _cancel_jobs(convo):
    frappe.db.set_value(M, {"conversation": convo.name, "job_status": ["in", ["Queued", "Processing"]]},
                        {"job_status": "Cancelled", "lease_token": None}, update_modified=False)


def _handoff(convo, brand, parent):
    if convo.support_ticket:
        return {"ticket": convo.support_ticket, "ticket_number": convo.support_ticket, "created": False}
    transcript = "\n\n".join(f"{r.sender_type}: {r.message}" for r in _rows(convo, limit=100))[-18000:]
    ticket = frappe.get_doc({"doctype": "Support Ticket", "naming_series": "ST-.YYYY.-",
        "user_id": parent.external_id, "custom_mobile_app": brand.name, "custom_mobile_app_user": parent.name,
        "customer_name": parent.full_name or "App user", "user_name": parent.full_name or "App user",
        "email": parent.email, "user_email": parent.email, "phone": parent.phone, "user_phone": parent.phone,
        "subject": "QuickLink care-team request", "category": "AI Chat Care Team", "priority": "Medium", "status": "Open",
        "description": escape(f"Conversation: {convo.name}\n\n{transcript}").replace("\n", "<br>")}).insert(ignore_permissions=True)
    convo.db_set({"mode": "Human", "support_ticket": ticket.name})
    _cancel_jobs(convo)
    _message(convo, "System", "The care team has been contacted. AI replies are paused while an agent helps you.")
    return {"ticket": ticket.name, "ticket_number": ticket.ticket_number or ticket.name, "created": True}


@frappe.whitelist(methods=["POST"])
def dispatch(app_id, user, action, body=None):
    _integration()
    body = frappe.parse_json(body or {})
    if not isinstance(body, dict):
        frappe.throw("Invalid request")
    brand, parent = _context(app_id, user)
    if action == "open_session":
        _lock("Mobile App User", parent.name)
        rows = frappe.get_all(C, filters={"brand": brand.name, "mobile_app_user": parent.name},
                              pluck="name", order_by="creation desc, name desc", limit_page_length=1)
        convo = _owned(rows[0], brand, parent) if rows else frappe.get_doc({"doctype": C, "brand": brand.name,
            "mobile_app_user": parent.name, "mode": "AI"}).insert(ignore_permissions=True)
        return _payload(convo, brand)
    convo = _owned(body.get("conversation"), brand, parent)
    if action == "get_messages":
        return _payload(convo, brand, body.get("after"))
    if action == "new_session":
        _payload(convo, brand)  # Reconcile a support ticket closed by an agent.
        name = "ql-" + key(convo.name, "next")
        if frappe.db.exists(C, name):
            return _payload(_owned(name, brand, parent), brand)
        if convo.mode == "Human":
            frappe.throw("Finish the care-team conversation before starting a new chat")
        convo.db_set("mode", "Closed")
        _cancel_jobs(convo)
        fresh = frappe.get_doc({"doctype": C, "brand": brand.name, "mobile_app_user": parent.name,
            "mode": "AI", "previous_conversation": convo.name}).insert(ignore_permissions=True, set_name=name)
        return _payload(fresh, brand)
    if action == "escalate":
        return _handoff(convo, brand, parent)
    if action != "send_message":
        frappe.throw("Unknown QuickLink action")
    text = clean_text(body.get("message"), 4000)
    client = clean_text(body.get("client_message_id"), 150)
    name = "qlm-" + key(convo.name, client)
    if frappe.db.exists(M, name):
        saved = frappe.get_doc(M, name)
        if saved.message != text:
            frappe.throw("Message ID was already used with different text")
        return {"conversation_id": convo.name, "message_id": name, "duplicate": True}
    state = _payload(convo, brand)
    if not state["can_send"]:
        frappe.throw("Chat is unavailable. Contact the care team or start a new chat.")
    # Bound provider usage across new conversations as well as within a thread.
    counts = frappe.db.sql("""select sum(m.creation>%s) as recent, count(*) as daily
        from `tabMobile App QuickLink Message` m join `tabMobile App QuickLink Conversation` c on c.name=m.conversation
        where c.brand=%s and c.mobile_app_user=%s and m.sender_type='Customer' and m.creation>%s""",
        (now_datetime()-timedelta(minutes=1), brand.name, parent.name, now_datetime()-timedelta(days=1)), as_dict=True)[0]
    if int(counts.recent or 0) >= 12:
        frappe.throw("Please wait a minute before sending more messages")
    if convo.mode == "AI" and int(counts.daily or 0) >= 200:
        frappe.throw("Daily AI message limit reached. Please contact the care team.")
    if convo.mode == "AI" and frappe.db.exists(M, {"conversation": convo.name, "job_status": ["in", ["Queued", "Processing"]]}):
        frappe.throw("Please wait for the current reply or contact the care team")
    cards = body.get("cards") or []
    if not isinstance(cards, list) or len(cards) > 3 or len(json.dumps(cards)) > 16000:
        frappe.throw("Invalid catalogue reference")
    saved = _message(convo, "Customer", text, name=name, cards=json.dumps(cards),
                     job_status="Queued" if convo.mode == "AI" else "None", next_attempt=now_datetime())
    if convo.mode == "Human":
        ticket = frappe.get_doc("Support Ticket", convo.support_ticket)
        msg = frappe.get_doc({"doctype": "Support Ticket Message", "ticket": ticket.name, "sender_type": "User",
            "sender_id": parent.external_id, "sender_name": parent.full_name or "App user", "message": escape(text).replace("\n", "<br>")})
        msg.flags.quicklink_origin = True
        msg.insert(ignore_permissions=True)
        saved.db_set("support_message", msg.name)
    return {"conversation_id": convo.name, "message_id": saved.name, "duplicate": False}


@frappe.whitelist(methods=["POST"])
def claim(app_id):
    _integration()
    brand = _brand(app_id)
    if not brand.quicklink_enabled:
        return None
    # Select bounded candidates, then recheck under the conversation lock.
    candidates = frappe.db.sql("""select m.name, m.conversation from `tabMobile App QuickLink Message` m
        join `tabMobile App QuickLink Conversation` c on c.name=m.conversation
        where c.brand=%s and c.mode='AI' and
        ((m.job_status='Queued' and m.next_attempt<=%s) or (m.job_status='Processing' and m.lease_until<=%s))
        order by m.creation asc limit 10""", (brand.name, now_datetime(), now_datetime()), as_dict=True)
    for row in candidates:
        convo = _lock(C, row.conversation)
        msg = frappe.get_doc(M, row.name)
        now = now_datetime()
        due = ((msg.job_status == "Queued" and get_datetime(msg.next_attempt) <= now)
               or (msg.job_status == "Processing" and get_datetime(msg.lease_until) <= now))
        if not due or convo.mode != "AI":
            continue
        try:
            _context(app_id, convo.mobile_app_user)
        except frappe.PermissionError:
            msg.db_set("job_status", "Cancelled")
            continue
        if int(msg.attempts or 0) >= 3:
            _fail(convo, msg)
            continue
        lease = frappe.generate_hash(length=32)
        msg.db_set({"job_status": "Processing", "attempts": int(msg.attempts or 0) + 1,
                    "lease_token": lease, "lease_until": now + timedelta(seconds=120), "prompt_revision": str(brand.modified)})
        history = frappe.get_all(M, filters={"conversation": convo.name, "sequence": ["<=", msg.sequence],
            "sender_type": ["in", ["Customer", "AI"]]}, fields=["sender_type", "message"], order_by="sequence desc", limit_page_length=20)
        return {"message_id": msg.name, "lease": lease, "brand": brand.name, "app_id": app_id,
                "prompts": {p: (brand.get("quicklink_" + p) or "")[:12000] for p in PROMPTS},
                "history": list(reversed(history)), "cards": json.loads(msg.cards or "[]")}
    return None


def _fail(convo, msg):
    msg.db_set({"job_status": "Failed", "lease_token": None, "last_error": "provider_unavailable"})
    name = "qlm-" + key(msg.name, "failure")
    if not frappe.db.exists(M, name):
        _message(convo, "System", "AI could not reply. Please try again or select Contact care team.", name=name)


@frappe.whitelist(methods=["POST"])
def finish(app_id, message_id, lease, reply=None):
    _integration()
    brand = _brand(app_id)
    msg = frappe.get_doc(M, message_id)
    convo = _lock(C, msg.conversation)
    msg.reload()
    if convo.brand != brand.name:
        frappe.throw("Message not found", frappe.PermissionError)
    _context(app_id, convo.mobile_app_user)
    if not can_finish(msg.job_status, msg.lease_token, lease, get_datetime(msg.lease_until) if msg.lease_until else None,
                      now_datetime(), convo.mode, bool(brand.quicklink_enabled)):
        return {"accepted": False}
    if not reply:
        if int(msg.attempts) >= 3:
            _fail(convo, msg)
        else:
            msg.db_set({"job_status": "Queued", "lease_token": None, "last_error": "provider_unavailable",
                        "next_attempt": now_datetime() + timedelta(seconds=15 * int(msg.attempts))})
        return {"accepted": True, "retry": msg.job_status == "Queued"}
    text = clean_text(reply, 12000)
    name = "qlm-" + key(msg.name, "reply")
    if not frappe.db.exists(M, name):
        _message(convo, "AI", text, name=name, reply_to=msg.name, cards=msg.cards)
    msg.db_set({"job_status": "Done", "lease_token": None, "last_error": None})
    return {"accepted": True}


def mirror_support_message(doc, method=None):
    if doc.flags.quicklink_origin:
        return
    names = frappe.get_all(C, filters={"support_ticket": doc.ticket}, pluck="name", limit_page_length=1)
    if not names:
        return
    convo = _lock(C, names[0])
    name = "qlm-" + key("support", doc.name)
    if not frappe.db.exists(M, name) and doc.sender_type in ("Agent", "User"):
        _message(convo, "Agent" if doc.sender_type == "Agent" else "Customer", strip_html(doc.message or "") or "(Empty message)",
                 name=name, support_message=doc.name)


@frappe.whitelist(methods=["POST"])
def desk(conversation, message=None):
    """Read/reply through existing support permissions, never a mobile API token in Desk."""
    convo = frappe.get_doc(C, conversation)
    convo.check_permission("read")
    if message:
        if not convo.support_ticket:
            frappe.throw("The customer has not requested an agent yet")
        ticket = frappe.get_doc("Support Ticket", convo.support_ticket)
        ticket.check_permission("write")
        frappe.has_permission("Support Ticket Message", "create", throw=True)
        if ticket.status in ("Closed", "Resolved"):
            frappe.throw("This support ticket is closed")
        frappe.get_doc({"doctype": "Support Ticket Message", "ticket": ticket.name, "sender_type": "Agent",
            "sender_id": frappe.session.user, "sender_name": frappe.utils.get_fullname(),
            "message": escape(clean_text(message, 4000)).replace("\n", "<br>")}).insert()
    return _payload(convo, frappe.get_doc("Mobile App Brand", convo.brand))
