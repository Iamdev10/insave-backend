from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import re
import asyncio
from pathlib import Path
# Netscape HTTP Cookie File
# https://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file! Do not edit.

.instagram.com	TRUE	/	TRUE	1806622706	csrftoken	goyJGReoZklngBHbjZs_E7
.instagram.com	TRUE	/	TRUE	1806622686	datr	3YefaZFgWBqWAdZaObsBFgZC
.instagram.com	TRUE	/	TRUE	1803598686	ig_did	C21C030F-EB3C-4BED-B09D-8E6096304517
.instagram.com	TRUE	/	TRUE	1772667501	wd	1710x947
.instagram.com	TRUE	/	TRUE	1806622685	mid	aZ-H3QAEAAEYeMMA2V55eUN4Q9UE
.instagram.com	TRUE	/	TRUE	1779838706	ds_user_id	21303695929
.instagram.com	TRUE	/	TRUE	1803598693	sessionid	21303695929%3AbJrhHtSgIGXAyA%3A0%3AAYhbZHgVOJx_R_i7JRAIwAtcheTsyEZTIr388azPZA
.instagram.com	TRUE	/	TRUE	0	rur	"HIL\05421303695929\0541803598705:01fe947e641389b4870d5f033d239203d6d96304301a71bd771bf596663c4b03b6b419b0"

app = FastAPI(title="InSave API")

# ── CORS (allow your frontend domain) ────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Replace * with your domain in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)


# ── MODELS ────────────────────────────────────────────────────────────────────
class InfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format: str   # "mp4_hd", "mp4_sd", "mp3", "jpg"
    index: int = 0  # for album posts, which item to download


# ── HELPERS ───────────────────────────────────────────────────────────────────
def is_valid_instagram_url(url: str) -> bool:
    pattern = r"https?://(www\.)?instagram\.com/(p|reel|tv|stories)/[\w\-]+"
    return bool(re.match(pattern, url))

def detect_type(url: str) -> str:
    if "/reel/" in url or "/tv/" in url:
        return "video"
    return "post"  # /p/ could be image, video, or album — yt-dlp will reveal


# ── ROUTE: /info  (fetch metadata without downloading) ───────────────────────
@app.post("/info")
async def get_info(req: InfoRequest):
    if not is_valid_instagram_url(req.url):
        raise HTTPException(400, "Invalid Instagram URL")

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "extract_flat": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch media info: {str(e)}")

    # Check if album (carousel) post — yt-dlp returns entries list
    entries = info.get("entries")

    if entries:
        # Album post
        items = []
        for i, entry in enumerate(entries):
            items.append({
                "index": i,
                "type": "video" if entry.get("vcodec", "none") != "none" else "image",
                "thumbnail": entry.get("thumbnail"),
                "width": entry.get("width"),
                "height": entry.get("height"),
                "duration": entry.get("duration"),
                "title": entry.get("title", f"Item {i+1}"),
            })
        return {
            "type": "album",
            "count": len(items),
            "items": items,
            "uploader": info.get("uploader"),
            "description": info.get("description", "")[:120],
        }
    else:
        # Single item
        is_video = info.get("vcodec", "none") != "none"
        return {
            "type": "video" if is_video else "image",
            "title": info.get("title", "Instagram Media"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "width": info.get("width"),
            "height": info.get("height"),
            "uploader": info.get("uploader"),
            "description": info.get("description", "")[:120],
            "formats": _available_formats(info),
        }


def _available_formats(info: dict) -> list:
    formats = []
    if info.get("vcodec", "none") != "none":
        formats += ["mp4_hd", "mp4_sd", "mp3"]
    else:
        formats += ["jpg"]
    return formats


# ── ROUTE: /download  (download & stream file to user) ───────────────────────
@app.post("/download")
async def download_media(req: DownloadRequest):
    if not is_valid_instagram_url(req.url):
        raise HTTPException(400, "Invalid Instagram URL")

    file_id = str(uuid.uuid4())
    out_path = DOWNLOAD_DIR / file_id

    fmt = req.format

    if fmt == "mp4_hd":
        ydl_opts = {
            "outtmpl": str(out_path) + ".%(ext)s",
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "playlist_items": str(req.index + 1),
        }
        ext = "mp4"
        media_type = "video/mp4"

    elif fmt == "mp4_sd":
        ydl_opts = {
            "outtmpl": str(out_path) + ".%(ext)s",
            "format": "worstvideo[ext=mp4]+worstaudio/worst[ext=mp4]/worst",
            "merge_output_format": "mp4",
            "quiet": True,
            "playlist_items": str(req.index + 1),
        }
        ext = "mp4"
        media_type = "video/mp4"

    elif fmt == "mp3":
        ydl_opts = {
            "outtmpl": str(out_path) + ".%(ext)s",
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": True,
            "playlist_items": str(req.index + 1),
        }
        ext = "mp3"
        media_type = "audio/mpeg"

    elif fmt == "jpg":
        # For images, download thumbnail (yt-dlp fetches image directly)
        ydl_opts = {
            "outtmpl": str(out_path) + ".%(ext)s",
            "format": "best",
            "quiet": True,
            "playlist_items": str(req.index + 1),
        }
        ext = "jpg"
        media_type = "image/jpeg"

    else:
        raise HTTPException(400, "Invalid format. Use: mp4_hd, mp4_sd, mp3, jpg")

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _run_ydl, ydl_opts, req.url)
    except Exception as e:
        raise HTTPException(500, f"Download failed: {str(e)}")

    # Find the downloaded file
    files = list(DOWNLOAD_DIR.glob(f"{file_id}.*"))
    if not files:
        raise HTTPException(500, "Download failed — file not found")

    file_path = files[0]
    filename = f"insave_{file_id[:8]}.{ext}"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename,
        background=None,  # File deleted after serving — see cleanup below
    )


def _run_ydl(opts: dict, url: str):
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])


# ── ROUTE: /health ────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}
