"""Web Push (VAPID) for the meeting_soon out-of-app reminder.

Delivers a browser push notification even when the PrismAI tab is closed. Fully
self-contained — no third-party service. Keys are a single application-server
VAPID keypair set in env:

  VAPID_PUBLIC_KEY   base64url uncompressed P-256 point (sent to the browser as
                     applicationServerKey)
  VAPID_PRIVATE_KEY  the private key as PEM (multi-line ok in env)
  VAPID_SUBJECT      mailto:you@domain — required by the push services

Generate a keypair once with:  python -c "import webpush; webpush.generate_vapid_keys()"
and paste the two values (+ a mailto subject) into the backend env.

Everything degrades gracefully: if keys/deps are missing, vapid_public_key()
returns "" (the frontend then hides the opt-in) and send_to_user() is a no-op.
"""

from __future__ import annotations

import json
import os

from auth import supabase

_PUBLIC = os.getenv("VAPID_PUBLIC_KEY", "").strip()
_PRIVATE = os.getenv("VAPID_PRIVATE_KEY", "").strip().replace("\\n", "\n")
_SUBJECT = os.getenv("VAPID_SUBJECT", "").strip() or "mailto:admin@meetprismai.com"
_TABLE = "push_subscriptions"


def enabled() -> bool:
    if not (_PUBLIC and _PRIVATE and supabase):
        return False
    try:
        import pywebpush  # noqa: F401
        return True
    except Exception:
        return False


def vapid_public_key() -> str:
    return _PUBLIC if enabled() else ""


# ── subscription storage ──────────────────────────────────────────────────────
def save_subscription(user_id: str, endpoint: str, keys: dict) -> bool:
    if not supabase or not user_id or not endpoint:
        return False
    p256dh = (keys or {}).get("p256dh")
    auth = (keys or {}).get("auth")
    if not p256dh or not auth:
        return False
    try:
        supabase.table(_TABLE).upsert(
            {"user_id": str(user_id), "endpoint": endpoint, "p256dh": p256dh, "auth": auth},
            on_conflict="endpoint",
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[webpush] save_subscription failed uid={str(user_id)[:8]}: {exc!r}")
        return False


def delete_subscription(user_id: str, endpoint: str) -> None:
    if not supabase or not endpoint:
        return
    try:
        supabase.table(_TABLE).delete().eq("user_id", str(user_id)).eq("endpoint", endpoint).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[webpush] delete_subscription failed: {exc!r}")


# ── send ──────────────────────────────────────────────────────────────────────
def send_to_user(user_id: str, title: str, body: str, url: str | None = None) -> int:
    """Push to all of a user's subscribed browsers. Stale subscriptions (404/410)
    are pruned. Returns the number of successful sends. Never raises."""
    if not enabled() or not user_id:
        return 0
    from pywebpush import webpush, WebPushException
    try:
        subs = supabase.table(_TABLE).select("endpoint, p256dh, auth").eq("user_id", str(user_id)).execute().data or []
    except Exception as exc:  # noqa: BLE001
        print(f"[webpush] list subs failed uid={str(user_id)[:8]}: {exc!r}")
        return 0
    payload = json.dumps({"title": title, "body": body, "url": url or "/dashboard"})
    sent = 0
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s["endpoint"],
                    "keys": {"p256dh": s["p256dh"], "auth": s["auth"]},
                },
                data=payload,
                vapid_private_key=_PRIVATE,
                vapid_claims={"sub": _SUBJECT},
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):  # gone — drop the dead subscription
                delete_subscription(str(user_id), s["endpoint"])
            else:
                print(f"[webpush] send failed uid={str(user_id)[:8]} status={status}: {exc!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"[webpush] send error uid={str(user_id)[:8]}: {exc!r}")
    return sent


# ── one-time key generation (dev helper) ──────────────────────────────────────
def generate_vapid_keys() -> None:
    """Print a fresh VAPID keypair for the env. Run once, locally."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    import base64

    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    raw_pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()
    print("VAPID_PUBLIC_KEY=" + public_b64)
    print("VAPID_PRIVATE_KEY (PEM, set as-is — env can hold multi-line):")
    print(private_pem)
    print('VAPID_SUBJECT=mailto:admin@meetprismai.com')


if __name__ == "__main__":
    generate_vapid_keys()
