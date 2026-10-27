"""Pure helpers for mobile-owned QuickLink; no dependencies on other ERP apps."""
import hashlib
import json
import re


def key(*parts):
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def owns_external_id(prefix, external_id):
    return bool(prefix and re.fullmatch(re.escape(prefix) + r"[0-9]+", external_id or ""))


def clean_text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Invalid message or identifier")
    return value.strip()


def can_finish(status, lease, supplied_lease, lease_until, now, mode, enabled):
    return (status == "Processing" and bool(lease) and lease == supplied_lease
            and lease_until is not None and lease_until > now and mode == "AI" and enabled)
