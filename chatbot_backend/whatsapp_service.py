import os
import base64
import httpx
from typing import Optional
from dotenv import load_dotenv

load_dotenv(override=True)

WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")

async def download_media(media_id: str) -> tuple[bytes, str]:
    """
    Downloads a media file (image or document) from Meta's servers.
    Returns (binary_data, mime_type).
    """
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}

    async with httpx.AsyncClient() as client:
        # Step 1: Get the real CDN download URL from Meta
        meta_url = f"https://graph.facebook.com/v19.0/{media_id}"
        response = await client.get(meta_url, headers=headers)
        response.raise_for_status()
        media_info = response.json()
        
        download_url = media_info.get("url")
        mime_type = media_info.get("mime_type", "image/jpeg")
        
        # Step 2: Download the actual binary file from CDN
        media_response = await client.get(download_url, headers=headers)
        media_response.raise_for_status()
        
        return media_response.content, mime_type


async def upload_media(file_bytes: bytes, mime_type: str, filename: str) -> Optional[str]:
    """
    Uploads a file to Meta's media server.
    Returns a media_id string that can be used in send_whatsapp_document().
    """
    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}"}
    
    files = {
        "file": (filename, file_bytes, mime_type),
        "messaging_product": (None, "whatsapp"),
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, files=files)
            response.raise_for_status()
            data = response.json()
            media_id = data.get("id")
            print(f"Uploaded media to Meta. media_id: {media_id}")
            return media_id
    except httpx.HTTPError as e:
        print(f"Failed to upload media to Meta: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response data: {e.response.text}")
        return None


async def send_whatsapp_document(to_phone_number: str, media_id: str, filename: str, caption: str = ""):
    """
    Sends a document message (e.g. PDF) to a student using a pre-uploaded media_id.
    """
    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_number,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
            "caption": caption,
        },
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            print(f"Successfully sent document to {to_phone_number}")
            return True
    except httpx.HTTPError as e:
        print(f"Failed to send document to {to_phone_number}: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response data: {e.response.text}")
        return False


async def send_whatsapp_message(to_phone_number: str, message_text: str):
    """
    Sends a plain text message back to the student using Meta's Cloud API.
    """
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_TOKEN:
        print("Warning: WhatsApp credentials not set. Simulating message send.")
        print(f"[SIMULATED OUTBOX -> {to_phone_number}]: {message_text}")
        return True

    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone_number,
        "type": "text",
        "text": {"body": message_text},
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            print(f"Successfully sent message to {to_phone_number}")
            return True
    except httpx.HTTPError as e:
        print(f"Failed to send WhatsApp message: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response data: {e.response.text}")
        return False
