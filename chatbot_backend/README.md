# EduBot — AI-Powered Educational WhatsApp Chatbot

An educational WhatsApp chatbot backend that acts as a personal tutor for high school students. Students send questions via text, images, or PDFs on WhatsApp and receive clear explanations or beautifully formatted PDF study materials — all within the chat.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![Claude](https://img.shields.io/badge/Anthropic-Claude_API-6B4FBB)
![WhatsApp](https://img.shields.io/badge/WhatsApp-Cloud_API-25D366?logo=whatsapp&logoColor=white)

## How It Works

```
Student sends a message on WhatsApp (text, image, or PDF)
        │
        ▼
Meta Webhook → FastAPI Backend (returns 200 OK immediately)
        │
        ▼
Intent Classification (AI pre-flight check)
        │
        ├── Regular question → Claude generates a text reply → sent back via WhatsApp
        │
        └── PDF request (notes/worksheet/question paper)
                │
                ▼
        Claude generates structured content
                │
                ▼
        ReportLab renders a styled PDF with LaTeX math
                │
                ▼
        PDF uploaded to Meta → delivered in WhatsApp chat
```

## Features

- **Multi-modal input** — accepts text messages, images (photos of handwritten questions), and PDF documents
- **AI intent classification** — a lightweight pre-flight Claude call determines whether the student wants a chat reply or a PDF document, and what type (notes, worksheet, or question paper)
- **PDF generation** — produces professionally styled, multi-page PDFs with branded headers/footers, formatted headings, bullet points, code blocks, and LaTeX-rendered math equations
- **Chat memory** — stores conversation history in MongoDB (with graceful fallback to in-memory storage) so the bot remembers context across messages
- **Duplicate deduplication** — handles Meta's duplicate webhook deliveries
- **Concurrency control** — per-user processing locks prevent race conditions from rapid messages
- **Async throughout** — background task processing with immediate 200 OK responses to avoid webhook retry storms

## PDF Output Types

| Intent | Trigger | Output |
|---|---|---|
| `PDF_SOLUTION` | "give me notes on...", "explain in a pdf" | Structured explanation with step-by-step solutions |
| `PDF_WORKSHEET` | "make a worksheet on..." | Practice questions + answer key on a separate page |
| `PDF_QUESTION_PAPER` | "create a test on..." | Questions only, no solutions |
| `FOLLOW_UP_WORKSHEET` | "yes" (after bot offers practice) | Auto-generated worksheet based on the topic just discussed |

## Tech Stack

| Component | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| AI | Anthropic Claude API (text + vision) |
| Messaging | Meta WhatsApp Cloud API |
| Database | MongoDB Atlas (PyMongo) |
| PDF Engine | ReportLab Platypus + Matplotlib (LaTeX rendering) |
| Tunneling | ngrok (for local development) |
| HTTP Client | httpx (async) |

## Project Structure

```
chatbot_backend/
├── main.py               # FastAPI app, webhook endpoints, message routing
├── ai_service.py         # Claude API integration, system prompts, intent classification
├── whatsapp_service.py   # WhatsApp Cloud API (send/receive messages, media upload/download)
├── pdf_service.py        # PDF generation with ReportLab (styles, markdown parsing, LaTeX math)
├── database.py           # MongoDB connection with in-memory fallback
├── requirements.txt      # Python dependencies
├── run.sh                # Start script (server + ngrok tunnel)
└── .env                  # API keys and config (not committed)
```

## Setup

### Prerequisites

- Python 3.10+
- A [Meta Developer](https://developers.facebook.com/) app with WhatsApp Cloud API enabled
- An [Anthropic](https://console.anthropic.com/) API key
- [ngrok](https://ngrok.com/) for exposing your local server
- MongoDB Atlas cluster (optional — falls back to in-memory storage)

### Installation

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/edubot-whatsapp.git
cd edubot-whatsapp/chatbot_backend

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the `chatbot_backend/` directory:

```env
# Meta WhatsApp API
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_TOKEN=your_whatsapp_access_token
VERIFY_TOKEN=your_webhook_verify_token

# Anthropic Claude API
ANTHROPIC_API_KEY=sk-ant-...

# Database (optional)
MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/
```

### Running

```bash
# Option 1: Use the run script (starts server + ngrok)
chmod +x run.sh
./run.sh

# Option 2: Start manually
uvicorn main:app --reload
# Then in another terminal:
ngrok http 8000
```

Copy the ngrok HTTPS URL and paste it into your Meta app's webhook settings as:
```
https://your-ngrok-url.ngrok-free.app/webhook
```
