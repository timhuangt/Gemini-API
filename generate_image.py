#!/usr/bin/env python3
"""
Dedicated image generation script for gemini-webapi.
Supports command-line arguments and interactive mode to generate and download full-resolution images.
"""

import asyncio
import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Add the src folder to path so we can import gemini_webapi before installing
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from gemini_webapi import GeminiClient, logger
from gemini_webapi.types.image import GeneratedImage

COOKIES_FILE = ROOT / "cookies.json"
DEFAULT_OUTPUT_DIR = ROOT / "output"

def load_cookies():
    if not COOKIES_FILE.exists():
        print(f"Error: {COOKIES_FILE.name} not found. Please log in first or place cookies.json in the project root.")
        sys.exit(1)
    
    try:
        data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error reading {COOKIES_FILE.name}: {e}")
        sys.exit(1)
        
    cookies = {}
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
        logger.error(f"Failed to write updated cookies: {e}")

async def generate_images(prompt: str, output_dir: Path, no_hd: bool):
    # 1. Load cookies
    cookies = load_cookies()
    psid = cookies.get("__Secure-1PSID")
    psidts = cookies.get("__Secure-1PSIDTS")
    
    if not psid:
        print("Error: __Secure-1PSID not found in cookies.json.")
        sys.exit(1)
        
    extra = {k: v for k, v in cookies.items() if k not in {"__Secure-1PSID", "__Secure-1PSIDTS"}}

    print("Initializing Gemini Client...")
    client = GeminiClient(
        secure_1psid=psid,
        secure_1psidts=psidts or "",
        cookies=extra or None,
    )
    
    try:
        # Initialize
        await client.init(timeout=45, auto_close=False, auto_refresh=True)
        print("Client connected and authenticated successfully!")
        
        # Prepare directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\nSending image generation prompt to Gemini:\n> {prompt}\n")
        print("Generating images (this may take 10-30 seconds)...")
        
        # Request content generation
        response = await client.generate_content(prompt)
        
        if not response.images:
            print("\n⚠️ Gemini did not generate any images.")
            print("Explanation or response from Gemini:")
            print("-" * 50)
            print(response.text)
            print("-" * 50)
            print("\nHint: Try rephrasing your prompt. Make sure it explicitly asks to generate, design, or create an image (e.g., 'Generate an image of...'). Also ensure the prompt complies with safety guidelines.")
            return

        print(f"\n✨ Successfully received {len(response.images)} images from Gemini!")
        
        for idx, image in enumerate(response.images):
            print(f"\n[Image {idx + 1}/{len(response.images)}]")
            print(f"- Title/Alt: {image.title or 'N/A'}")
            if image.alt:
                print(f"- Description: {image.alt}")
            
            # Format file name
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # Clean prompt for file name segment
            clean_prompt = "".join(c for c in prompt[:20] if c.isalnum() or c in (" ", "_", "-")).rstrip().replace(" ", "_")
            file_name_base = f"gen_{timestamp}_{clean_prompt}_{idx+1}"
            
            is_gen = isinstance(image, GeneratedImage)
            fetch_hd = is_gen and (not no_hd)
            
            if fetch_hd:
                print("- Quality: Requesting Full-Resolution (HD) original image via Google RPC...")
            else:
                print("- Quality: Fetching standard preview resolution...")

            try:
                # Save the image using package's save utility
                kwargs = {}
                if is_gen:
                    kwargs["full_size"] = fetch_hd
                
                save_path = await image.save(
                    path=str(output_dir),
                    filename=file_name_base,
                    verbose=False,
                    **kwargs
                )
                print(f"✅ Saved to: {save_path}")
                print(f"   Size: {os.path.getsize(save_path) / 1024:.1f} KB")
            except Exception as e:
                print(f"❌ Failed to save image {idx+1}: {e}")
                
    except Exception as e:
        print(f"\n❌ An error occurred during the generation process: {e}")
    finally:
        # Save updated cookies back to json
        save_cookies(client.cookies, cookies)
        await client.close()

def main():
    parser = argparse.ArgumentParser(description="Generate images with Google Gemini Web API.")
    parser.add_argument("-p", "--prompt", type=str, help="The image description prompt to send to Gemini.")
    parser.add_argument("-o", "--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="Directory to save generated images (default: ./output).")
    parser.add_argument("--no-hd", action="store_true", help="Download the fast preview quality instead of pulling full-resolution original image via RPC.")
    
    args = parser.parse_args()
    
    if args.prompt:
        prompt = args.prompt
    else:
        # Interactive mode
        print("==================================================")
        print("       Gemini AI Image Generator (CLI Mode)       ")
        print("==================================================")
        print("Type your prompt to generate beautiful images.")
        print("Example: 'Generate an image of a futuristic cyberpunk city with neon lights.'")
        print("-" * 50)
        try:
            prompt = input("Enter your prompt: ").strip()
            if not prompt:
                print("Empty prompt. Exiting.")
                sys.exit(0)
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(0)

    output_path = Path(args.output_dir)
    asyncio.run(generate_images(prompt, output_path, args.no_hd))

if __name__ == "__main__":
    main()
