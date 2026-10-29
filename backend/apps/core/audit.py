# =============================================================================
# === backend/apps/core/audit.py ===
# =============================================================================
"""
record_audit() — one line in the audit log for every change HR makes
(G3, 28 Oct 2026): who, when, what, and the values before and after.
Attendance decisions use it now; employee and payroll changes will too.
"""
from .models import AuditEntry


def record_audit(*, organization, actor, action, target, summary, before=None, after=None, note=""):
    return AuditEntry.objects.create(
        organization=organization,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        target_type=target._meta.label_lower,
        target_id=str(target.pk),
        summary=summary[:255],
        data={"before": before or {}, "after": after or {}, "note": note},
    )


def audit_payload(entry):
    return {
        "id": str(entry.id),
        "at": entry.created_at.isoformat(),
        "actor": entry.actor.full_name if entry.actor else "Sistem",
        "action": entry.action,
        "summary": entry.summary,
        "note": (entry.data or {}).get("note", ""),
    }
