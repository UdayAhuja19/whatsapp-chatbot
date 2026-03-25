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
You are a helpful educational assistant for high school students.
CRITICAL RULE: You can ONLY be used for academic purposes. If the user asks a question that is not related to academics, education, or studying, you must politely decline and state that you are only for academic purposes.
CRITICAL RULE 2: You can ONLY communicate in English. If the user asks a question in any other language, politely respond in English that you can only be used in English.
Target your explanations, vocabulary, and difficulty strictly at the level of a high school student (grades 9-12).
Answer questions clearly and accurately using plain text only.
For math, write equations as readable text (e.g. "x^2 + 3x + 2" or "sin(x)") — NO LaTeX, NO dollar signs, NO backslashes.
Keep responses concise as they will be read on a phone screen.
IF AND ONLY IF you have successfully answered an academic question or explained a topic, you MUST add exactly this sentence at the very end of your message:
"Shall we run through some practice questions on this?"
DO NOT add this sentence if you are declining a non-academic query.
"""

# Used only when generating PDF documents — LaTeX is rendered beautifully in the PDF
SYSTEM_PROMPT_PDF = """
You are an educational assistant tailoring content for high school students. Answer student questions and generate study materials (like practice worksheets) clearly and accurately.
TARGET AUDIENCE: Target your explanations, vocabulary, and difficulty strictly at the level of a high school student (grades 9-12).
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


async def decide_pdf_intent(chat_history: list, new_message: str) -> str:
    """
    Uses Claude to determine if a PDF should be generated, and what type.
    Returns a string in the format "INTENT|Topic" 
    e.g. "PDF_SOLUTION|Agriculture Methane Emissions"
    or "NONE|None".
    """
    system_prompt = (
        "You are an intent classification engine for an educational WhatsApp bot. "
        "Analyze the user's latest message combined with the chat history. "
        "Determine if the user wants an academic PDF document generated AND identify the specific academic topic they are referring to. "
        "Your output MUST be strictly in the format: INTENT|Topic Name\n\n"
        "INTENT must be EXACTLY ONE of the following:\n"
        "1. FOLLOW_UP_WORKSHEET (if the bot previously offered practice questions and the user accepted, agreed, or requested specific alterations to the practice)\n"
        "2. PDF_WORKSHEET (if the user explicitly asks to generate a worksheet)\n"
        "3. PDF_QUESTION_PAPER (if the user explicitly asks for a test or question paper)\n"
        "4. PDF_SOLUTION (if the user explicitly asks for notes, summary, or a structured solution in a PDF document. "
        "If the user just says 'in a pdf format please', look at the previous conversation to determine the topic!)\n"
        "5. NONE (if the user is just chatting normally, asking a question to be answered in chat, declining an offer, or if a PDF is not strictly necessary)\n\n"
        "The Topic Name should be 2-5 words summarizing the core academic subject. Do not include conversational words like 'please' or 'worksheet'. If INTENT is NONE, the Topic Name can just be None."
    )
    
    # We only need the last few messages for context to save tokens and inference time
    recent_history = [
        {"role": m["role"], "content": m["content"]}
        for m in chat_history[-4:] if isinstance(m.get("content"), str)
    ]
    
    messages = recent_history + [{"role": "user", "content": new_message}]
    
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=30,
            temperature=0.0,
            system=system_prompt,
            messages=messages
        )
        result = response.content[0].text.strip()
        
        # Parse the output safely
        for tag in ["FOLLOW_UP_WORKSHEET", "PDF_WORKSHEET", "PDF_QUESTION_PAPER", "PDF_SOLUTION"]:
            if result.upper().startswith(tag):
                return result
        return "NONE|None"
    except Exception as e:
        print(f"Error in intent classification: {e}")
        return "NONE|None"
