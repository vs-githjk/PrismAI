"""Notification center endpoints (#9). All auth-gated via require_user_id — a user
only ever sees/marks their OWN notifications.

GET /notifications          -> merged list (stored + synthesized action_due) + unread_count
POST /notifications/{id}/read
POST /notifications/read-all

Web Push (meeting_soon out-of-app delivery):
GET  /notifications/push/key         -> VAPID public key
POST /notifications/push/subscribe   -> store a browser push subscription
POST /notifications/push/unsubscribe -> drop one
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_user_id
import notifications as notif

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def get_notifications(user_id: str = Depends(require_user_id)):
    stored = notif.list_stored(user_id)
    synthesized = notif.synthesize_action_due(user_id)
    # Synthesized action_due first (time-sensitive), then stored newest-first.
    return {
        "notifications": synthesized + stored,
        "unread_count": notif.unread_count(user_id),  # stored only; client adds non-dismissed synths
        "synthesized_ids": [n["id"] for n in synthesized],
    }


@router.post("/{notif_id}/read")
async def read_one(notif_id: int, user_id: str = Depends(require_user_id)):
    if not notif.mark_read(user_id, notif_id):
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"ok": True}


@router.post("/read-all")
async def read_all(user_id: str = Depends(require_user_id)):
    notif.mark_all_read(user_id)
    return {"ok": True}


# ── Web Push ──────────────────────────────────────────────────────────────────
class PushSubscription(BaseModel):
    endpoint: str
    keys: dict  # {p256dh, auth}


@router.get("/push/key")
async def push_key():
    import webpush
    key = webpush.vapid_public_key()
    if not key:
        raise HTTPException(status_code=503, detail="Push not configured")
    return {"public_key": key}


@router.post("/push/subscribe")
async def push_subscribe(sub: PushSubscription, user_id: str = Depends(require_user_id)):
    import webpush
    if not webpush.save_subscription(user_id, sub.endpoint, sub.keys):
        raise HTTPException(status_code=400, detail="Invalid subscription")
    return {"ok": True}


@router.post("/push/unsubscribe")
async def push_unsubscribe(sub: PushSubscription, user_id: str = Depends(require_user_id)):
    import webpush
    webpush.delete_subscription(user_id, sub.endpoint)
    return {"ok": True}
