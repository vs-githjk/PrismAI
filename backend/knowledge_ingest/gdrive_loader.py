"""Google Drive loader. Reuses the existing google_access_token."""

from clients import get_http

from .loaders_base import LoadedDoc, LoaderError
from . import pdf_loader

DRIVE_API = "https://www.googleapis.com/drive/v3/files"


async def _get_metadata(file_id: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    async with get_http() as client:
        resp = await client.get(
            f"{DRIVE_API}/{file_id}",
            headers=headers,
            params={"fields": "mimeType,name"},
            timeout=15.0,
        )
    if resp.status_code == 401:
        raise LoaderError("Google access expired — please reconnect.")
    if resp.status_code == 404:
        raise LoaderError("File not found in Drive (or no access).")
    if resp.status_code != 200:
        raise LoaderError(f"Drive metadata error {resp.status_code}")
    return resp.json()


async def _download_or_export(file_id: str, token: str, mime: str) -> bytes:
    headers = {"Authorization": f"Bearer {token}"}
    if mime == "application/vnd.google-apps.document":
        url = f"{DRIVE_API}/{file_id}/export"
        params = {"mimeType": "text/plain"}
    elif mime == "application/vnd.google-apps.spreadsheet":
        url = f"{DRIVE_API}/{file_id}/export"
        params = {"mimeType": "text/csv"}
    else:
        url = f"{DRIVE_API}/{file_id}"
        params = {"alt": "media"}
    async with get_http() as client:
        resp = await client.get(url, headers=headers, params=params, timeout=60.0)
    if resp.status_code != 200:
        raise LoaderError(f"Drive download failed: {resp.status_code}")
    return resp.content


async def load(file_id: str, token: str) -> LoadedDoc:
    if not token:
        raise LoaderError("Google Drive is not connected.")
    meta = await _get_metadata(file_id, token)
    mime = meta.get("mimeType", "")
    content = await _download_or_export(file_id, token, mime)

    if mime == "application/pdf":
        return await pdf_loader.load(content)

    text = content.decode("utf-8", errors="replace").strip()
    if not text:
        raise LoaderError("File is empty or unreadable.")

    return LoadedDoc(text=text, page_metadata=[{"gdrive_file_id": file_id, "name": meta.get("name")}])
