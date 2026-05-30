#!/usr/bin/env python3
"""
Demo script for gemini-webapi showing how to use cookies.json in a CLI-only server environment.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add the src folder to path so we can import gemini_webapi before installing
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from gemini_webapi import GeminiClient, logger

COOKIES_FILE = ROOT / "cookies.json"

def load_cookies():
    if not COOKIES_FILE.exists():
        print(f"Error: {COOKIES_FILE} not found. Please place your exported cookies here.")
        sys.exit(1)
    
    try:
        data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading {COOKIES_FILE}: {e}")
        sys.exit(1)
        
    cookies = {}
    
    # Support both flat {name: value} and nested {"cookies": {name: value}} format
    if "cookies" in data and isinstance(data["cookies"], dict):
        cookies = data["cookies"]
    elif isinstance(data, dict):
        cookies = data
    else:
        print("Unsupported cookies.json format.")
        sys.exit(1)
        
    return cookies

def save_cookies(client_cookies, original_cookies):
    merged = dict(original_cookies)
    try:
        for cookie in client_cookies.jar:
            name = getattr(cookie, "name", None)
            value = getattr(cookie, "value", None)
            if isinstance(name, str) and isinstance(value, str) and value:
                merged[name] = value
    except Exception as e:
        logger.warning(f"Failed to extract cookies from client session: {e}")
        return

    # Only save if something has changed
    if merged == original_cookies:
        return

    payload = {
        "updated_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "cookies": dict(sorted(merged.items())),
    }
    
    try:
        COOKIES_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Successfully auto-refreshed cookies and updated {COOKIES_FILE.name}")
    except Exception as e:
        logger.error(f"Failed to write updated cookies to {COOKIES_FILE}: {e}")

async def main():
    # 1. Load the initial cookies
    cookies = load_cookies()
    psid = cookies.get("__Secure-1PSID")
    psidts = cookies.get("__Secure-1PSIDTS")
    
    if not psid:
        print("Error: __Secure-1PSID not found in cookies.json.")
        sys.exit(1)
        
    # Extra cookies (like AEC, COMPASS, NID, etc.)
    extra = {k: v for k, v in cookies.items() if k not in {"__Secure-1PSID", "__Secure-1PSIDTS"}}

    print("Initializing Gemini Client...")
    # 2. Build the client
    client = GeminiClient(
        secure_1psid=psid,
        secure_1psidts=psidts or "",
        cookies=extra or None,
    )
    
    try:
        # 3. Initialize connection (auto_refresh=True enables background rotation of __Secure-1PSIDTS)
        await client.init(timeout=30, auto_close=False, auto_refresh=True)
        print("Client successfully initialized and authenticated!")
        
        # 4. Prompt Gemini
        prompt = "Hello! Please reply with a very short, polite greeting to confirm you are online."
        print(f"\nPrompting Gemini: '{prompt}'...")
        
        response = await client.generate_content(prompt)
        print("\nGemini Response:")
        print("-" * 40)
        print(response.text)
        print("-" * 40)
        chat_id = response.metadata[0] if response.metadata else "N/A"
        print(f"Chat ID: {chat_id}\n")
        
    except Exception as e:
        print(f"An error occurred: {e}")
        
    finally:
        # 5. Persist the updated cookies back to the JSON file
        save_cookies(client.cookies, cookies)

if __name__ == "__main__":
    asyncio.run(main())
