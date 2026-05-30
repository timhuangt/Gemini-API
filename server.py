#!/usr/bin/env python3
"""
FastAPI Server for Gemini Image Generation Plugin/Extension.
Provides REST endpoints and mounts the generated images directory as static files.
Includes CORS support to allow seamless integrations from browsers or external extensions.
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.requests import Request
from pydantic import BaseModel, Field

# Add the src folder to path so we can import gemini_webapi
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from gemini_webapi import GeminiClient, logger
from gemini_webapi.types.image import GeneratedImage

COOKIES_FILE = ROOT / "cookies.json"

# ---------------------------------------------------------------------------
# Global Gemini Client State Management
# ---------------------------------------------------------------------------
class GlobalState:
    client: GeminiClient | None = None
    original_cookies: dict = {}

state = GlobalState()

def load_cookies() -> dict:
    if not COOKIES_FILE.exists():
        logger.error("cookies.json not found in project root.")
        return {}
    try:
        data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
        if "cookies" in data and isinstance(data["cookies"], dict):
            return data["cookies"]
        elif isinstance(data, dict):
            return data
    except Exception as e:
        logger.error(f"Error loading cookies.json: {e}")
    return {}

def save_cookies_state():
    if not state.client:
        return
    merged = dict(state.original_cookies)
    try:
        for cookie in state.client.cookies.jar:
            name = getattr(cookie, "name", None)
            value = getattr(cookie, "value", None)
            if isinstance(name, str) and isinstance(value, str) and value:
                merged[name] = value
    except Exception as e:
        logger.error(f"Failed to extract cookies from client for saving: {e}")
        return

    if merged == state.original_cookies:
        return

    payload = {
        "updated_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "cookies": dict(sorted(merged.items())),
    }
    
    try:
        COOKIES_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        state.original_cookies = merged
        logger.info("Automatically updated and saved refreshed cookies to cookies.json")
    except Exception as e:
        logger.error(f"Failed to write updated cookies to disk: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    logger.info("Starting Gemini API Server...")
    cookies = load_cookies()
    psid = cookies.get("__Secure-1PSID")
    psidts = cookies.get("__Secure-1PSIDTS")
    
    if not psid:
        logger.critical("Cannot initialize GeminiClient: __Secure-1PSID is missing in cookies.json.")
        # We don't crash, but endpoints will report degraded state
    else:
        extra = {k: v for k, v in cookies.items() if k not in {"__Secure-1PSID", "__Secure-1PSIDTS"}}
        state.original_cookies = cookies
        gemini_proxy = os.getenv("GEMINI_PROXY")
        if gemini_proxy:
            logger.info(f"Using proxy configuration from env: {gemini_proxy}")
            
        state.client = GeminiClient(
            secure_1psid=psid,
            secure_1psidts=psidts or "",
            cookies=extra or None,
            proxy=gemini_proxy or None,
        )
        try:
            logger.info("Initializing connection with Google Gemini...")
            # auto_refresh=True keeps __Secure-1PSIDTS rotated in the background
            await state.client.init(timeout=45, auto_close=False, auto_refresh=True)
            logger.success("Gemini client successfully initialized and authenticated.")
        except Exception as e:
            logger.error(f"Failed to authenticate/initialize Gemini Client: {e}")

    yield
    
    # --- Shutdown ---
    logger.info("Shutting down Gemini API Server...")
    if state.client:
        save_cookies_state()
        await state.client.close()
    logger.info("API Server shutdown complete.")


app = FastAPI(
    title="Gemini WebAPI Image Generation Server",
    description="Backend API Server providing image generation capabilities for external plugins and extensions.",
    version="1.0.0",
    lifespan=lifespan
)

# ---------------------------------------------------------------------------
# Middlewares & Static Files Mount
# ---------------------------------------------------------------------------
# Add CORS Middleware to support web-extension (chrome extension) cross-origin calls
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this to specific origins if deployed to production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, description="Prompt description for image generation.", example="Generate an image of a red cat.")
    no_hd: bool = Field(False, description="Disable HD original quality, download standard resolution instead.")

class ImageResponseItem(BaseModel):
    title: str
    alt: str
    base64: str = Field(..., description="Base64 Data URI of the image (data:image/...;base64,...)")

class GenerateResponse(BaseModel):
    success: bool
    text: str
    images: list[ImageResponseItem]

# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/status", tags=["Status"])
async def get_status():
    """
    Check the current health and Google authentication status of the backend client.
    """
    if not state.client:
        return {"status": "degraded", "detail": "Gemini client not initialized. Missing cookies.json?"}
    
    # Check current cookies status and trigger saving if refreshed
    save_cookies_state()
    
    return {
        "status": "healthy",
        "account_status": str(state.client.account_status),
        "cookies_updated_at": getattr(state.client, "cookies_updated_at", "N/A"),
    }

@app.post("/api/generate", response_model=GenerateResponse, tags=["Generation"])
async def api_generate_image(request: GenerateRequest, http_req: Request):
    """
    Send prompt to Gemini, generate images, save them locally, and return accessibility URLs.
    """
    if not state.client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gemini backend client is not initialized. Please verify cookies.json configuration."
        )

    # Automatically save refreshed cookies if changed
    save_cookies_state()

    logger.info(f"Received generation request. Prompt: '{request.prompt}'")
    
    try:
        # Ensure the prompt starts with a request for an image to guarantee Gemini is driven to image mode
        user_prompt = request.prompt.strip()
        lower_prompt = user_prompt.lower()
        image_prefixes = ("show me a photo of", "show me a picture of", "generate an image of", "generate a photo of", "create an image of")
        if not any(lower_prompt.startswith(p) for p in image_prefixes):
            user_prompt = f"show me a photo of {user_prompt}"
            
        # Internally optimize prompt to enforce a minimal text response and focus 100% on image output
        optimized_prompt = (
            f"{user_prompt}\n\n"
            "[System Instruction: You are an image generator. Focus purely on generating or searching the requested image. "
            "Keep any accompanying text response extremely short, concise, and under 1 sentence.]"
        )
        
        # Prompt Gemini
        response = await state.client.generate_content(optimized_prompt)
        
        # Parse output images
        result_images = []
        if response.images:
            import tempfile
            import base64
            import mimetypes
            
            for idx, image in enumerate(response.images):
                # Unique name generation
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                clean_prompt = "".join(c for c in request.prompt[:20] if c.isalnum() or c in (" ", "_", "-")).rstrip().replace(" ", "_")
                filename_base = f"api_{timestamp}_{clean_prompt}_{idx+1}"
                
                is_gen = isinstance(image, GeneratedImage)
                fetch_hd = is_gen and (not request.no_hd)
                
                # Setup custom arguments depending on image type
                kwargs = {}
                if is_gen:
                    kwargs["full_size"] = fetch_hd
                
                try:
                    # Save image inside a secure TemporaryDirectory which auto-deletes
                    with tempfile.TemporaryDirectory() as temp_dir:
                        abs_path_str = await image.save(
                            path=temp_dir,
                            filename=filename_base,
                            verbose=False,
                            **kwargs
                        )
                        
                        saved_path = Path(abs_path_str)
                        if saved_path.exists():
                            binary_data = saved_path.read_bytes()
                            
                            # Guess mime type based on file path
                            mime_type, _ = mimetypes.guess_type(saved_path)
                            if not mime_type:
                                mime_type = "image/png"  # Default fallback
                            
                            # Encode to base64 Data URI
                            b64_str = base64.b64encode(binary_data).decode("utf-8")
                            data_uri = f"data:{mime_type};base64,{b64_str}"
                            
                            result_images.append(
                                ImageResponseItem(
                                    title=image.title or "Image",
                                    alt=image.alt or "",
                                    base64=data_uri
                                )
                            )
                except Exception as save_err:
                    logger.error(f"Failed to process and encode image {idx+1}: {save_err}")
        
        # Trigger background saving again just in case cookies rotated during API call
        save_cookies_state()

        # Keep text response extremely brief to save payload size
        brief_text = response.text.strip()
        if len(brief_text) > 200:
            brief_text = brief_text[:197] + "..."

        return GenerateResponse(
            success=True,
            text=brief_text,
            images=result_images
        )

    except Exception as e:
        logger.error(f"Error during generation endpoint execution: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during image generation: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    # Listen on all interfaces so external clients in the same LAN or proxy can call
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
