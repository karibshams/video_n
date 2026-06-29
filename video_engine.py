"""
video_engine.py
----------------
Car listing video generator using Seedance v1.5 Pro image-to-video via fal.ai.

Model  : fal-ai/bytedance/seedance/v1.5/pro/image-to-video
Find it: fal.ai -> Explore -> search "seedance v1.5" -> "Image to Video Pro v1.5"

Design:
- One class (CarVideoEngine), one public method (generate()).
- Videos longer than 12s are built by firing multiple clips IN PARALLEL,
  then stitching with FFmpeg so total wait stays near one single-clip time.
- Audio is always disabled (generate_audio=False). Hard requirement.
- Backend-ready: VideoRequest and VideoResult are plain dataclasses,
  easy to wire into FastAPI, Django, or any backend.
- generate()       -> synchronous  (Flask, Django, scripts, Streamlit)
- generate_async() -> async        (FastAPI route handlers)
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

# ---------------------------------------------------------------------------
# Constants — all match real Seedance v1.5 Pro specs on fal.ai
# ---------------------------------------------------------------------------

FAL_MODEL_ENDPOINT  = "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"
MAX_CLIP_SECONDS    = 12       # model hard limit: 4–12s per call
MIN_CLIP_SECONDS    = 4        # model hard minimum per call
VALID_RESOLUTIONS   = ("480p", "720p")
VALID_ASPECT_RATIOS = ("16:9", "9:16", "4:3", "1:1", "3:4", "21:9", "auto")
DEFAULT_RESOLUTION  = "720p"
DEFAULT_ASPECT      = "16:9"   # landscape — best for car videos

# Cost: no-audio token-based pricing from fal.ai docs
# tokens = (height x width x FPS x duration) / 1024
# 720p @ 24fps: (1280 x 720 x 24) / 1024 = 21,504 tokens/sec
COST_PER_TOKEN_USD  = 0.0000012   # $1.2 per million tokens (no audio)
TOKENS_PER_SEC_720P = 21504
TOKENS_PER_SEC_480P = 10800       # (854 x 480 x 24) / 1024

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs")


# ---------------------------------------------------------------------------
# Data contracts — wire these directly to your backend
# ---------------------------------------------------------------------------

@dataclass
class VideoRequest:
    """
    Input contract. Pass this from your FastAPI / Django endpoint.

    image_urls     : 1–10 publicly accessible car photo URLs.
                     For mobile uploads, pre-upload to fal storage first (see app.py).
    description    : text prompt — car details + desired video style.
    total_duration : final video length in seconds. Range: 10–30.
    resolution     : "720p" for production, "480p" for cheaper/faster testing.
    aspect_ratio   : "16:9" for landscape (recommended for car videos).
    job_id         : unique ID auto-generated per request.
    """
    image_urls:     List[str]
    description:    str = ""
    total_duration: int = 15
    resolution:     str = DEFAULT_RESOLUTION
    aspect_ratio:   str = DEFAULT_ASPECT
    job_id:         str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def __post_init__(self):
        if not self.image_urls and not self.description.strip():
            raise ValueError("Provide at least one image_url or a description.")
        if self.resolution not in VALID_RESOLUTIONS:
            raise ValueError(f"resolution must be one of {VALID_RESOLUTIONS}")
        if self.aspect_ratio not in VALID_ASPECT_RATIOS:
            raise ValueError(f"aspect_ratio must be one of {VALID_ASPECT_RATIOS}")
        self.total_duration = max(10, min(30, self.total_duration))


@dataclass
class VideoResult:
    """
    Output contract. Serialize this as JSON from your backend endpoint.

    job_id                  : matches input VideoRequest.job_id.
    output_path             : local path of the final stitched MP4.
    clip_count              : number of clips generated and stitched.
    duration_seconds        : actual video duration in seconds.
    generation_time_seconds : wall-clock seconds from request to file ready.
    estimated_cost_usd      : approximate API cost for this generation.
    """
    job_id:                  str
    output_path:             str
    clip_count:              int
    duration_seconds:        int
    generation_time_seconds: float
    estimated_cost_usd:      float


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CarVideoEngine:
    """
    Wraps Seedance v1.5 Pro (fal.ai) to produce silent car promo videos
    from photos + text description.

    Sync usage (Streamlit, Flask, scripts):
        engine = CarVideoEngine()
        result = engine.generate(request)

    Async usage (FastAPI):
        engine = CarVideoEngine()
        result = await engine.generate_async(request)
    """

    def __init__(self, api_key: Optional[str] = None, output_dir: str = OUTPUT_DIR):
        self.api_key = api_key or os.getenv("FAL_KEY")
        if not self.api_key:
            raise RuntimeError(
                "FAL_KEY is not set.\n"
                "Add FAL_KEY=your_key_here to your .env file.\n"
                "Get your key: fal.ai -> Settings -> API Keys"
            )
        os.environ["FAL_KEY"] = self.api_key  # fal_client reads this env var
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def generate(self, request: VideoRequest) -> VideoResult:
        """
        Synchronous. Use in Streamlit, Flask, Django, or plain scripts.
        Do NOT call this inside a FastAPI route — use generate_async() there.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError(
                "generate() was called inside a running async event loop.\n"
                "Inside FastAPI use: result = await engine.generate_async(request)"
            )
        return asyncio.run(self._pipeline(request))

    async def generate_async(self, request: VideoRequest) -> VideoResult:
        """
        Async. Use inside FastAPI route handlers.
        Example:
            @app.post("/generate")
            async def generate_video(req: VideoRequest):
                result = await engine.generate_async(req)
                return result
        """
        return await self._pipeline(request)

    @staticmethod
    def estimate_cost(total_seconds: int, resolution: str = "720p") -> float:
        """
        Estimate API cost before generating. Useful for showing users a price
        preview in your UI before they click Generate.
        """
        tps = TOKENS_PER_SEC_720P if resolution == "720p" else TOKENS_PER_SEC_480P
        return round(total_seconds * tps * COST_PER_TOKEN_USD, 4)

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    async def _pipeline(self, request: VideoRequest) -> VideoResult:
        start    = time.time()
        segments = self._plan_segments(request.total_duration)

        # Build parallel tasks — one per clip segment
        tasks = [
            self._generate_clip(
                image_url=(
                    request.image_urls[i % len(request.image_urls)]
                    if request.image_urls else None
                ),
                description=request.description,
                seconds=seg_len,
                resolution=request.resolution,
                aspect_ratio=request.aspect_ratio,
                index=i,
            )
            for i, seg_len in enumerate(segments)
        ]

        # Fire all clips IN PARALLEL — total wait ≈ single clip time
        clip_paths = await asyncio.gather(*tasks)

        # Stitch into one final video (or use directly if only one clip)
        final_path = (
            self._stitch_clips(list(clip_paths), request.job_id)
            if len(clip_paths) > 1
            else clip_paths[0]
        )

        return VideoResult(
            job_id=request.job_id,
            output_path=final_path,
            clip_count=len(segments),
            duration_seconds=sum(segments),
            generation_time_seconds=round(time.time() - start, 1),
            estimated_cost_usd=self.estimate_cost(sum(segments), request.resolution),
        )

    @staticmethod
    def _plan_segments(total_duration: int) -> List[int]:
        """
        Split total_duration into chunks within [MIN, MAX] seconds.
        10 -> [10]   |   20 -> [10,10]   |   25 -> [13,12]   |   30 -> [10,10,10]
        """
        if total_duration <= MAX_CLIP_SECONDS:
            return [total_duration]

        num_clips = -(-total_duration // MAX_CLIP_SECONDS)  # ceiling division
        base      = total_duration // num_clips
        segments  = [base] * num_clips
        for i in range(total_duration - base * num_clips):
            segments[i] += 1
        return segments

    async def _generate_clip(
        self,
        image_url:    Optional[str],
        description:  str,
        seconds:      int,
        resolution:   str,
        aspect_ratio: str,
        index:        int,
    ) -> str:
        """Generate one clip via fal.ai and download to local disk."""
        arguments = {
            "prompt": (
                description.strip()
                or "Smooth cinematic car showcase. Highlight exterior design, wheels, and finish."
            ),
            "duration":       seconds,    # int — matches Seedance v1.5 Pro API spec
            "resolution":     resolution,
            "aspect_ratio":   aspect_ratio,
            "generate_audio": False,      # always off — hard project requirement
            "camera_fixed":   False,      # allow camera movement for dynamic shots
        }
        if image_url:
            arguments["image_url"] = image_url

        handler   = await fal_client.submit_async(FAL_MODEL_ENDPOINT, arguments=arguments)
        result    = await handler.get()
        video_url = result["video"]["url"]

        local_path = os.path.join(
            self.output_dir, f"clip_{index}_{uuid.uuid4().hex[:6]}.mp4"
        )
        await asyncio.to_thread(self._download, video_url, local_path)
        return local_path

    @staticmethod
    def _download(url: str, dest_path: str) -> None:
        import urllib.request
        urllib.request.urlretrieve(url, dest_path)

    def _stitch_clips(self, clip_paths: List[str], job_id: str) -> str:
        """
        FFmpeg concat — no re-encoding, fast lossless join.
        Cleans up individual clip files and the temp list file after stitching.
        """
        list_file  = os.path.join(self.output_dir, f"concat_{job_id}.txt")
        final_path = os.path.join(self.output_dir, f"final_{job_id}.mp4")

        with open(list_file, "w") as f:
            for path in clip_paths:
                f.write(f"file '{os.path.abspath(path)}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_file, "-c", "copy", final_path],
            check=True, capture_output=True,
        )

        # Clean up temp files
        os.remove(list_file)
        for path in clip_paths:
            try:
                os.remove(path)
            except OSError:
                pass

        return final_path