import os
import base64
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv(override=True)

# Initialize the async client
client = AsyncAnthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY", "dummy_key"),
    timeout=60.0,  # 60 second timeout so requests don't hang forever
)

# ── System prompts ────────────────────────────────────────────────

# Used for normal WhatsApp text replies — no LaTeX, no markdown symbols
SYSTEM_PROMPT_PLAIN = """
You are a helpful educational assistant for students.
CRITICAL RULE: You can ONLY be used for academic purposes. If the user asks a question that is not related to academics, education, or studying, you must politely decline and state that you are only for academic purposes.
CRITICAL RULE 2: You can ONLY communicate in English. If the user asks a question in any other language, politely respond in English that you can only be used in English.
Answer questions clearly and accurately using plain text only.
For math, write equations as readable text (e.g. "x^2 + 3x + 2" or "sin(x)") — NO LaTeX, NO dollar signs, NO backslashes.
Keep responses concise as they will be read on a phone screen.
IF AND ONLY IF you have successfully answered an academic question or explained a topic, you MUST add exactly this sentence at the very end of your message:
"Shall we run through some practice questions on this?"
DO NOT add this sentence if you are declining a non-academic query.
"""

# Used only when generating PDF documents — LaTeX is rendered beautifully in the PDF
SYSTEM_PROMPT_PDF = """
You are an educational assistant. Answer student questions and generate study materials (like practice worksheets) clearly and accurately.
CRITICAL RULE: You can ONLY be used for academic purposes. If the user asks a question that is not related to academics, education, or studying, politely decline and state your purpose.
CRITICAL RULE 2: You can ONLY communicate in English. If the user asks a question in any other language, politely respond in English that you can only be used in English.
The system will AUTOMATICALLY convert your text response into a formatted PDF document.

RESPONSE STRUCTURE:
- Use ## headings for each step (## Step 1: ..., ## Step 2: ..., etc.)
- Use bullet points and numbered lists where appropriate.
- After the last step, write the final answer and stop. Do NOT add a summary or recap.
- Your entire response MUST consist ONLY of the academic content (steps, math, practice questions, or solutions). No conversational frames, no introductions, no follow-up offers.
- BANNED: conversational filler, pleasantries, or off-topic chat.

MATH RULES (LaTeX will be rendered in the PDF):
- Display equations: wrap in $$ on their own line. Example: $$\\frac{d}{dx}[x^3] = 3x^2$$
- Inline math: write as plain text (e.g. "where u = 4x") — NEVER use single $ delimiters.
- Allowed LaTeX: \\frac, \\int, \\sum, \\sqrt, \\sin, \\cos, \\tan, \\log, \\ln, \\lim, \\cdot, Greek letters, superscripts, subscripts.
- BANNED LaTeX: \\boxed, \\text, \\mathrm, \\begin, \\end, \\displaystyle.
"""

async def generate_response(chat_history: list, new_message: str, media_bytes: bytes = None, media_mime_type: str = None, pdf_mode: bool = False) -> str:
    """
    Calls the Anthropic Claude API.
    Supports both plain text and vision (image/PDF) inputs.
    Use pdf_mode=True when generating content for a PDF document.
    """
    system_prompt = SYSTEM_PROMPT_PDF if pdf_mode else SYSTEM_PROMPT_PLAIN
    messages = chat_history.copy()
    
    # Build the content block for the new message
    if media_bytes and media_mime_type:
        # Encode the binary media to base64 for Claude
        b64_data = base64.standard_b64encode(media_bytes).decode("utf-8")
        
        # Claude uses a special content array when media is attached
        content = []
        
        # Attach the image or PDF document
        if "pdf" in media_mime_type:
            # PDFs are treated as documents
            content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": media_mime_type,
                    "data": b64_data,
                }
            })
        else:
            # Images (jpeg, png, gif, webp)
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_mime_type,
                    "data": b64_data,
                }
            })
        
        # Add the user's text as a separate block
        # For images, we always append a strong instruction to treat it as an academic doubt
        is_image = media_mime_type and not "pdf" in media_mime_type
        image_instruction = (
            "Please analyze this image. If it contains a question, consider it an academic doubt and solve it for me step-by-step. "
            "If it doesn't contain a specific question, please explain the academic topic shown in the image."
        )

        if new_message:
            if is_image and not pdf_mode:
                content.append({"type": "text", "text": f"{new_message}\n\n{image_instruction}"})
            else:
                content.append({"type": "text", "text": new_message})
        else:
            if is_image:
                content.append({"type": "text", "text": image_instruction})
            else:
                content.append({"type": "text", "text": "Please analyze this document for me."})
        messages.append({"role": "user", "content": content})
    else:
        # Plain text message - the simple original path
        messages.append({"role": "user", "content": new_message})
    
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            system=system_prompt,
            messages=messages
        )
        return response.content[0].text
    except Exception as e:
        print(f"Error calling Claude API: {e}")
        return "I'm sorry, I am currently experiencing technical difficulties. Please try again later."
