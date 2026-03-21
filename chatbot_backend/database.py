import os
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

# We will try to connect to MongoDB, but fall back to local memory if macOS blocks the SRV DNS!
try:
    print("Trying to connect to MongoDB...")
    # 3-second timeout so it doesn't hang forever
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    client.admin.command('ping')  # Force a connection check
    db = client.get_database("whatsapp_bot")
    users_collection = db["users"]
    messages_collection = db["messages"]
    USING_DB = True
    print("✅ MongoDB Connected Successfully!")
except Exception as e:
    print(f"⚠️ MongoDB Connection Failed (macOS DNS issue): {e}")
    print("⚠️ Falling back to IN-MEMORY storage temporarily so you can test the AI!")
    USING_DB = False

# Temporary In-Memory storage if DB fails
memory_messages = []

def is_authorized(phone_number: str) -> bool:
    if USING_DB:
        user = users_collection.find_one({"phone_number": phone_number})
        return bool(user)
    return True # Temporary free pass

def save_message(phone_number: str, role: str, content: str):
    if USING_DB:
        messages_collection.insert_one({
            "phone_number": phone_number,
            "role": role,
            "content": content
        })
    else:
        memory_messages.append({
            "phone_number": phone_number,
            "role": role,
            "content": content
        })

def get_chat_history(phone_number: str, limit: int = 10, max_chars_per_msg: int = 500) -> list:
    """
    Retrieves recent chat history, truncating long messages to keep API calls fast.

    - limit: max number of messages to retrieve (reduced from 20 to 10)
    - max_chars_per_msg: older messages get truncated to this length to save tokens
      (only the last 2 messages are kept in full for immediate context)
    """
    if USING_DB:
        cursor = messages_collection.find({"phone_number": phone_number}).sort("_id", -1).limit(limit)
        messages = list(cursor)
        messages.reverse()
    else:
        messages = [m for m in memory_messages if m["phone_number"] == phone_number][-limit:]

    formatted_history = []
    total = len(messages)
    for i, msg in enumerate(messages):
        content = msg["content"]
        # Keep the last 2 messages in full (they're the most relevant context)
        # Truncate older ones to save tokens
        if i < total - 2 and len(content) > max_chars_per_msg:
            content = content[:max_chars_per_msg] + "... [truncated]"
        formatted_history.append({
            "role": msg["role"],
            "content": content
        })
    return formatted_history
