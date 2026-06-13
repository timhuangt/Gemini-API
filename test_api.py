#!/usr/bin/env python3
"""
Test client to verify the local Gemini API Server using Python's built-in urllib.
Sends a prompt and formats the Base64 output cleanly without flooding the terminal.
"""

import json
import urllib.request
import urllib.error
import sys

def test_api():
    url = "http://localhost:8000/api/generate"
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Microsoft 365 security features"
    payload = {
        "prompt": prompt,
        "no_hd": True  # Use standard resolution for faster turnaround in testing
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    
    print("==================================================")
    print("      Gemini API Server - End-to-End Test        ")
    print("==================================================")
    print(f"Sending POST request to: {url}")
    print(f"Prompt: '{payload['prompt']}'")
    print("Waiting for response (this can take 10-25 seconds)...")
    print("-" * 50)
    
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            status_code = response.status
            print(f"HTTP Status Code: {status_code} (Success)")
            
            resp_body = response.read().decode("utf-8")
            result = json.loads(resp_body)
            
            print(f"API Success Flag: {result.get('success')}")
            print("\nGemini Answer (Truncated to first 400 chars):")
            print("-" * 50)
            text_resp = result.get("text", "")
            print(text_resp[:400] + ("..." if len(text_resp) > 400 else ""))
            print("-" * 50)
            
            images = result.get("images", [])
            print(f"\nImages Returned: {len(images)}")
            
            for idx, img in enumerate(images):
                b64_data = img.get("base64", "")
                prefix = b64_data[:60] if b64_data else "N/A"
                print(f"\n📸 [Image {idx + 1}/{len(images)}]")
                print(f"  - Title: {img.get('title', 'N/A')}")
                print(f"  - Alt/Desc: {img.get('alt', 'N/A')}")
                print(f"  - Base64 Data URI Prefix: {prefix}...")
                print(f"  - Base64 Data Length: {len(b64_data)} characters")
                with open("output.txt", "w") as file:
                    file.write(b64_data)
                
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode('utf-8')}")
    except urllib.error.URLError as e:
        print(f"Failed to connect to API Server: {e.reason}")
        print("Is the API server running on port 8000?")
    except TimeoutError:
        print("Request timed out after 45 seconds.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    test_api()
