"""
video_engine.py
----------------
Car listing video generator — Seedance v1.5 Pro via fal.ai.

Model endpoint : fal-ai/bytedance/seedance/v1.5/pro/image-to-video
Audio          : always disabled (generate_audio=False)
Backend usage  : pass VideoRequest in, get VideoResult out
FastAPI        : await engine.generate_async(request)
Sync/Streamlit : engine.generate(request)
"""

import os
import time
import uuid
import asyncio
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

import fal_client
from dotenv import load_dotenv

load_dotenv()

# ── Model constants ────────────────────────────────────────────────
FAL_MODEL   = "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"
MAX_SECONDS = 12          # model hard limit per single API call
OUTPUT_DIR  = os.getenv("OUTPUT_DIR", "outputs")


# ── Input / Output contracts ───────────────────────────────────────
@dataclass
class VideoRequest:
    """Wire this from your backend endpoint."""
    image_urls:     List[str]       # 1–10 publicly accessible car photo URLs
    description:    str  = ""       # car details + desired video style
    total_duration: int  = 15       # final video length in seconds (10–30)
    resolution:     str  = "720p"   # "720p" production | "480p" testing
    aspect_ratio:   str  = "16:9"   # "16:9" landscape recommended for cars
    job_id:         str  = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def __post_init__(self):
        if not self.image_urls and not self.description.strip():
            raise ValueError("Provide at least one image_url or a description.")
        self.total_duration = max(10, min(30, self.total_duration))


@dataclass
class VideoResult:
    """Return this as JSON from your backend endpoint."""
    job_id:                  str
    output_path:             str    # local path of final MP4
    clip_count:              int
    duration_seconds:        int
    generation_time_seconds: float
    estimated_cost_usd:      float


# ── Engine ─────────────────────────────────────────────────────────
class CarVideoEngine:

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("FAL_KEY")
        if not self.api_key:
            raise RuntimeError(
                "FAL_KEY not set. Add FAL_KEY=your_key to .env\n"
                "Get key: fal.ai → Settings → API Keys"
            )
        os.environ["FAL_KEY"] = self.api_key
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def generate(self, request: VideoRequest) -> VideoResult:
        """Sync — use in Streamlit, Flask, scripts."""
        return asyncio.run(self._pipeline(request))

    async def generate_async(self, request: VideoRequest) -> VideoResult:
        """Async — use in FastAPI route handlers."""
        return await self._pipeline(request)

    async def _pipeline(self, request: VideoRequest) -> VideoResult:
        start    = time.time()
        segments = self._plan_segments(request.total_duration)

        clip_paths = await asyncio.gather(*[
            self._generate_clip(
                image_url=request.image_urls[i % len(request.image_urls)] if request.image_urls else None,
                description=request.description,
                seconds=seg,
                resolution=request.resolution,
                aspect_ratio=request.aspect_ratio,
                index=i,
            )
            for i, seg in enumerate(segments)
        ])

        final_path = (
            self._stitch(list(clip_paths), request.job_id)
            if len(clip_paths) > 1
            else clip_paths[0]
        )

        return VideoResult(
            job_id=request.job_id,
            output_path=final_path,
            clip_count=len(segments),
            duration_seconds=sum(segments),
            generation_time_seconds=round(time.time() - start, 1),
            estimated_cost_usd=round(sum(segments) * 21504 * 0.0000012, 4),
        )

    @staticmethod
    def _plan_segments(total: int) -> List[int]:
        """Split total seconds into MAX_SECONDS chunks."""
        if total <= MAX_SECONDS:
            return [total]
        n        = -(-total // MAX_SECONDS)
        base     = total // n
        segments = [base] * n
        for i in range(total - base * n):
            segments[i] += 1
        return segments

    async def _generate_clip(
        self, image_url: Optional[str], description: str,
        seconds: int, resolution: str, aspect_ratio: str, index: int,
    ) -> str:
        args = {
            "prompt":         description.strip() or "Cinematic car showcase, smooth camera motion.",
            "duration":       seconds,
            "resolution":     resolution,
            "aspect_ratio":   aspect_ratio,
            "generate_audio": False,
            "camera_fixed":   False,
        }
        if image_url:
            args["image_url"] = image_url

        handler = await fal_client.submit_async(FAL_MODEL, arguments=args)
        result  = await handler.get()
        url     = result["video"]["url"]

        path = os.path.join(OUTPUT_DIR, f"clip_{index}_{uuid.uuid4().hex[:6]}.mp4")
        await asyncio.to_thread(self._download, url, path)
        return path

    @staticmethod
    def _download(url: str, path: str) -> None:
        import urllib.request
        urllib.request.urlretrieve(url, path)

    def _stitch(self, clips: List[str], job_id: str) -> str:
        """FFmpeg lossless concat — no re-encoding."""
        list_file  = os.path.join(OUTPUT_DIR, f"list_{job_id}.txt")
        final_path = os.path.join(OUTPUT_DIR, f"final_{job_id}.mp4")

        with open(list_file, "w") as f:
            for c in clips:
                f.write(f"file '{os.path.abspath(c)}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_file, "-c", "copy", final_path],
            check=True, capture_output=True,
        )
        os.remove(list_file)
        for c in clips:
            try: os.remove(c)
            except OSError: pass

        return final_path