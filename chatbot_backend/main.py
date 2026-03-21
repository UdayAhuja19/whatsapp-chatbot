import os
import re
import asyncio
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv
import uvicorn

# Import our custom modules
import database
import ai_service
import whatsapp_service
import pdf_service

load_dotenv(override=True)

app = FastAPI(title="Educational WhatsApp Chatbot")

# In-memory lock for concurrency management
processing_locks = set()

# Track message IDs we've already seen (Meta sends duplicates)
seen_message_ids = set()

# Keywords that trigger sending a PDF document instead of (or in addition to) plain text
PDF_TRIGGER_KEYWORDS = [
    "pdf", "notes", "study guide", "summarize", "summary", "revision",
    "cheat sheet", "document", "write up", "worksheet", "question paper",
    "answer key", "more questions", "practice", "test paper"
]

def wants_pdf_response(text: str) -> bool:
    """Returns True if the student's message suggests they want a PDF."""
    lower = text.lower()
    return any(kw in lower for kw in PDF_TRIGGER_KEYWORDS)

def extract_title(text: str) -> str:
    """Extract a short title from the student's message for the PDF filename."""
    cleaned = re.sub(r"(give me|create|generate|make|write|summarize|a |an |the |pdf|notes|for)", "", text, flags=re.IGNORECASE)
    words = cleaned.strip().split()
    return " ".join(words[:6]).title() or "Study Notes"


@app.get("/")
async def root():
    return {"status": "ok", "message": "WhatsApp Chatbot Backend is running."}

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Required by Meta to verify the webhook URL during developer app setup."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "my_secure_verify_token")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return int(challenge)
        else:
            raise HTTPException(status_code=403, detail="Verification failed")
    raise HTTPException(status_code=400, detail="Missing parameters")


async def process_message(sender_phone: str, text_body: str, message_type: str,
                          media_bytes: bytes = None, media_mime_type: str = None):
    """
    Background task that does all the heavy lifting:
    calls Claude, generates PDF if needed, sends WhatsApp reply.
    Runs AFTER we've already returned 200 OK to Meta.
    """
    try:
        # 1. Retrieve Memory
        history = database.get_chat_history(sender_phone, limit=10)

        # 2. Detect if the student wants a PDF output
        send_pdf = wants_pdf_response(text_body)
        
        ai_prompt = text_body
        document_type = "Solution"
        base_topic = extract_title(text_body if text_body else "Attached Content")

        # ── Check if they are saying "yes" to a worksheet offer ──
        positive_phrases = ["yes", "yeah", "yep", "yup", "sure", "ok", "okay", "please", "do it", "of course", "definitely", "why not", "go ahead", "sounds good", "perfect", "y"]
        user_reply = text_body.strip().lower()
        is_affirmative = user_reply in positive_phrases or any(user_reply.startswith(p + " ") or user_reply.startswith(p + ".") for p in positive_phrases)
        if is_affirmative and history:
            # Look at the last message from the assistant
            last_bot_msg = next((msg["content"] for msg in reversed(history) if msg["role"] == "assistant"), "")
            if "practice worksheet" in last_bot_msg.lower() or "practice questions" in last_bot_msg.lower() or "practice" in last_bot_msg.lower():
                send_pdf = True
                document_type = "Worksheet"
                
                # Extract the actual topic from the user's PREVIOUS message
                last_user_msg = next((msg["content"] for msg in reversed(history) if msg["role"] == "user" and msg["content"]), "")
                if last_user_msg and last_user_msg.lower() not in positive_phrases:
                    base_topic = extract_title(last_user_msg)
                else:
                    base_topic = "Practice"

                ai_prompt = (
                    "Please generate a practice worksheet based strictly on ALL the academic topics and concepts covered in our last conversation (including any attached images). "
                    "Extract EVERY SINGLE subject or concept discussed. For EACH topic/concept you find, you MUST generate exactly 2 questions. "
                    "For example, if we discussed 1 topic, generate 2 questions. If we discussed 3 topics, generate 6 questions. "
                    "Group and categorize the questions properly under clear subheadings for each topic. "
                    "This could be math, science, history, languages, or any other subject. "
                    "Make the difficulty similar to the concepts we just discussed. "
                    "LIST ALL THE CATEGORIZED QUESTIONS FIRST. "
                    "Then, include the solutions at the very end of the document on a new page (use a level 1 heading EXACTLY like '# Answer Key'). "
                    "Use clear headings, bullet points, and LaTeX math formatting ONLY IF the subject requires math. "
                    "Do NOT include any conversational text, just the worksheet and the answer key."
                )

        if send_pdf and ai_prompt == text_body:
            # When a normal PDF is requested (not the auto-worksheet trigger above)
            topic = text_body if text_body else "the attached content"
            if "question paper" in text_body.lower() or "test paper" in text_body.lower():
                document_type = "Question Paper"
                ai_prompt = (
                    f"Please generate a question paper for: {topic}. "
                    f"List the questions clearly using bullet points and LaTeX math formatting where appropriate. "
                    f"DO NOT include an answer key or solutions in this document. "
                    f"Do NOT include any conversational text, just the questions."
                )
            elif "worksheet" in text_body.lower():
                document_type = "Worksheet"
                ai_prompt = (
                    f"Please generate a worksheet for: {topic}. "
                    f"LIST ALL THE QUESTIONS FIRST clearly using bullet points and LaTeX math formatting. "
                    f"Then, include the solutions at the very end of the document on a new page (use a level 1 heading EXACTLY like '# Answer Key'). "
                    f"Do NOT include any conversational text, just the worksheet and the answer key."
                )
            else:
                document_type = "Solution"
                ai_prompt = (
                    f"Please provide a complete, well-structured, and detailed educational solution/explanation for: {topic}. "
                    f"Solve the FULL problem and all of its sub-parts step-by-step. "
                    f"Use clear headings (using # symbols), bullet points, and LaTeX math formatting where appropriate for clarity. "
                    f"Do NOT include any conversational text, pleasantries, or offers to help further. Do NOT mention being an assistant, do NOT mention PDFs — "
                    f"just provide the full academic content and nothing else."
                )

        pdf_title = f"{base_topic} {document_type}".strip()

        # 3. Generating a PDF takes time -> Send placeholder IMMEDIATELY before Claude
        if send_pdf:
            await whatsapp_service.send_whatsapp_message(sender_phone, "Generating your notes... one moment!")

        # 4. Generate AI Response
        print(f"[{sender_phone}] Calling Claude API...")
        ai_reply = await ai_service.generate_response(
            chat_history=history,
            new_message=ai_prompt,
            media_bytes=media_bytes,
            media_mime_type=media_mime_type,
            pdf_mode=send_pdf,
        )
        print(f"[{sender_phone}] Claude responded ({len(ai_reply)} chars)")

        # 5. Send the final response
        success = False
        if send_pdf:
            try:
                pdf_path = pdf_service.generate_pdf(title=pdf_title, content=ai_reply)

                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()

                os.unlink(pdf_path)

                safe_filename = re.sub(r"[^\w\s-]", "", pdf_title).strip().replace(" ", "_") + ".pdf"
                media_id = await whatsapp_service.upload_media(pdf_bytes, "application/pdf", safe_filename)

                if media_id:
                    success = await whatsapp_service.send_whatsapp_document(
                        to_phone_number=sender_phone,
                        media_id=media_id,
                        filename=safe_filename,
                        caption=f"Here are your notes on: {pdf_title}"
                    )
                else:
                    print("PDF upload failed. Falling back to text reply.")
                    success = await whatsapp_service.send_whatsapp_message(sender_phone, ai_reply)

            except Exception as e:
                import traceback
                print(f"PDF generation/send failed: {e}")
                traceback.print_exc()
                success = await whatsapp_service.send_whatsapp_message(sender_phone, ai_reply)
        else:
            success = await whatsapp_service.send_whatsapp_message(sender_phone, ai_reply)

        # 5. Save Conversation State
        if success:
            user_content = text_body if text_body else f"[Sent a {message_type}]"
            database.save_message(phone_number=sender_phone, role="user", content=user_content)
            database.save_message(phone_number=sender_phone, role="assistant", content=ai_reply)

    except Exception as e:
        print(f"[{sender_phone}] ERROR in background processing: {e}")
        import traceback
        traceback.print_exc()
        # Try to notify the student something went wrong
        try:
            await whatsapp_service.send_whatsapp_message(
                sender_phone, "Sorry, something went wrong. Please try again!"
            )
        except Exception:
            pass

    finally:
        # ALWAYS release the lock, no matter what
        processing_locks.discard(sender_phone)
        print(f"[{sender_phone}] Lock released.")


@app.post("/webhook")
async def receive_message(request: Request):
    """
    Receives incoming WhatsApp messages from Meta.
    Returns 200 OK immediately, then processes the message in the background.
    """
    body = await request.json()

    try:
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "ignored"}

        message = messages[0]
        message_id = message.get("id", "")
        sender_phone = message.get("from")
        message_type = message.get("type", "text")

        # ── Deduplicate: Meta often sends the same webhook 2-3 times ──
        if message_id in seen_message_ids:
            print(f"[{sender_phone}] Duplicate message {message_id}. Ignoring.")
            return {"status": "duplicate"}
        seen_message_ids.add(message_id)

        # Keep the seen set from growing forever (cap at 1000)
        if len(seen_message_ids) > 1000:
            seen_message_ids.clear()

        # ── Extract content based on message type ──
        text_body = ""
        media_bytes = None
        media_mime_type = None

        if message_type == "text":
            text_body = message.get("text", {}).get("body", "")
            print(f"\n[TEXT MESSAGE] from {sender_phone}: {text_body}")

        elif message_type == "image":
            media_id = message.get("image", {}).get("id")
            text_body = message.get("image", {}).get("caption", "")
            print(f"\n[IMAGE MESSAGE] from {sender_phone} (media_id: {media_id})")
            try:
                media_bytes, media_mime_type = await whatsapp_service.download_media(media_id)
                print(f"  -> Downloaded image: {len(media_bytes)} bytes, type: {media_mime_type}")
            except Exception as e:
                print(f"  -> Failed to download image: {e}")
                await whatsapp_service.send_whatsapp_message(sender_phone, "Sorry, I couldn't download your image. Please try again!")
                return {"status": "media_error"}

        elif message_type == "document":
            media_id = message.get("document", {}).get("id")
            filename = message.get("document", {}).get("filename", "document")
            text_body = message.get("document", {}).get("caption", "")
            print(f"\n[DOCUMENT MESSAGE] from {sender_phone}: '{filename}' (media_id: {media_id})")
            try:
                media_bytes, media_mime_type = await whatsapp_service.download_media(media_id)
                print(f"  -> Downloaded document: {len(media_bytes)} bytes, type: {media_mime_type}")
            except Exception as e:
                print(f"  -> Failed to download document: {e}")
                await whatsapp_service.send_whatsapp_message(sender_phone, "Sorry, I couldn't open your document. Please try again!")
                return {"status": "media_error"}

        else:
            print(f"\n[UNSUPPORTED TYPE: {message_type}] from {sender_phone}. Ignoring.")
            await whatsapp_service.send_whatsapp_message(sender_phone, "Sorry, I can only handle text messages, images, and PDF files right now!")
            return {"status": "unsupported_type"}

        # ── Concurrency Lock ──
        if sender_phone in processing_locks:
            print(f"[{sender_phone}] is already processing. Ignoring concurrent message.")
            return {"status": "locked"}

        processing_locks.add(sender_phone)

        # ── Fire off background task and return 200 immediately ──
        asyncio.create_task(
            process_message(sender_phone, text_body, message_type, media_bytes, media_mime_type)
        )

    except Exception as e:
        print(f"Error parsing webhook: {e}")
        import traceback
        traceback.print_exc()

    # Always return 200 OK immediately so Meta doesn't retry
    return {"status": "processed"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
