"""
video_engine.py
----------------
Car listing video generator using Seedance v1.5 Pro image-to-video via fal.ai.

Model  : fal-ai/bytedance/seedance/v1.5/pro/image-to-video
Find it: fal.ai -> Explore -> search "seedance v1.5" -> "Image to Video Pro v1.5"

Design:
- One class (CarVideoEngine), one public method (generate()).
- Videos longer than 12s are built by firing multiple clips IN PARALLEL,
  then stitching with FFmpeg — so total wait stays near one single-clip time.
- Audio is always disabled (generate_audio=False). Hard requirement.
- Backend-ready: VideoRequest and VideoResult are plain dataclasses,
  easy to wire into FastAPI, Django, or any backend.
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
# Constants — all match the real Seedance v1.5 Pro specs on fal.ai
# ---------------------------------------------------------------------------

FAL_MODEL_ENDPOINT  = "fal-ai/bytedance/seedance/v1.5/pro/image-to-video"
MAX_CLIP_SECONDS    = 12        # model hard limit: 4–12s per single call
MIN_CLIP_SECONDS    = 4         # model hard minimum
VALID_RESOLUTIONS   = ("480p", "720p")   # 480p = cheaper/faster, 720p = production
VALID_ASPECT_RATIOS = ("16:9", "9:16", "4:3", "1:1", "3:4", "21:9", "auto")
DEFAULT_RESOLUTION  = "720p"
DEFAULT_ASPECT      = "16:9"    # landscape — correct for car showcase videos

# Cost reference (no-audio, token-based): ~$0.13 per 5s 720p clip
# Tokens = (height x width x FPS x duration) / 1024
# 720p @ 24fps, 5s = (1280 x 720 x 24 x 5) / 1024 = 107,520 tokens → ~$0.13
COST_PER_TOKEN_USD  = 0.0000012   # $1.2 per million tokens (no audio)
TOKENS_PER_SEC_720P = 21504       # (1280 x 720 x 24) / 1024

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs")


# ---------------------------------------------------------------------------
# Public data contracts (wire these to your backend)
# ---------------------------------------------------------------------------

@dataclass
class VideoRequest:
    """
    Input contract. Wire this from your FastAPI/Django endpoint.

    Fields:
        image_urls      : list of 1–10 publicly accessible car photo URLs.
                          For local uploads, pre-upload to fal storage or S3 first.
        description     : text prompt describing the car and desired video style.
        total_duration  : desired final video length in seconds (10–30).
        resolution      : "720p" for production, "480p" for cheaper testing.
        aspect_ratio    : "16:9" for landscape (recommended for car videos).
        job_id          : auto-generated unique ID for this request.
    """
    image_urls:     List[str]
    description:    str  = ""
    total_duration: int  = 15
    resolution:     str  = DEFAULT_RESOLUTION
    aspect_ratio:   str  = DEFAULT_ASPECT
    job_id:         str  = field(default_factory=lambda: uuid.uuid4().hex[:10])

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
    Output contract. Return this from your backend endpoint as JSON.

    Fields:
        job_id                   : matches the input VideoRequest.job_id.
        output_path              : local file path of the final stitched video.
        clip_count               : number of clips generated and stitched.
        duration_seconds         : actual final video duration in seconds.
        generation_time_seconds  : wall-clock time from request to file ready.
        estimated_cost_usd       : approximate API cost for this generation.
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
    Wraps fal.ai Seedance v1.5 Pro image-to-video to produce silent
    car promotional videos from photos and a text description.

    Usage:
        engine = CarVideoEngine()
        result = engine.generate(VideoRequest(
            image_urls=["https://..."],
            description="2022 BMW M3, blue, showcase exterior and alloy wheels.",
            total_duration=20,
        ))
        print(result.output_path)
    """

    def __init__(self, api_key: Optional[str] = None, output_dir: str = OUTPUT_DIR):
        self.api_key = api_key or os.getenv("FAL_KEY")
        if not self.api_key:
            raise RuntimeError(
                "FAL_KEY is not set.\n"
                "Add it to your .env file: FAL_KEY=your_key_here\n"
                "Get your key from: fal.ai -> Settings -> API Keys"
            )
        os.environ["FAL_KEY"] = self.api_key   # fal_client reads this env var
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def generate(self, request: VideoRequest) -> VideoResult:
        """Synchronous entry point. Safe to call from any backend framework."""
        return asyncio.run(self._generate_async(request))

    @staticmethod
    def estimate_cost(total_seconds: int, resolution: str = "720p") -> float:
        """Utility: estimate cost before generating. Call from your pricing UI."""
        tokens_per_sec = TOKENS_PER_SEC_720P if resolution == "720p" else TOKENS_PER_SEC_720P // 2
        return round(total_seconds * tokens_per_sec * COST_PER_TOKEN_USD, 4)

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    async def _generate_async(self, request: VideoRequest) -> VideoResult:
        start = time.time()
        segments = self._plan_segments(request.total_duration)

        # Fire all clip generations IN PARALLEL for speed
        tasks = [
            self._generate_clip(
                image_url=request.image_urls[i % len(request.image_urls)] if request.image_urls else None,
                description=request.description,
                seconds=seg_len,
                resolution=request.resolution,
                aspect_ratio=request.aspect_ratio,
                index=i,
            )
            for i, seg_len in enumerate(segments)
        ]
        clip_paths = await asyncio.gather(*tasks)

        # Stitch multiple clips into one final video
        final_path = (
            self._stitch_clips(list(clip_paths), request.job_id)
            if len(clip_paths) > 1
            else clip_paths[0]
        )

        elapsed = round(time.time() - start, 1)
        cost    = self.estimate_cost(sum(segments), request.resolution)

        return VideoResult(
            job_id=request.job_id,
            output_path=final_path,
            clip_count=len(segments),
            duration_seconds=sum(segments),
            generation_time_seconds=elapsed,
            estimated_cost_usd=cost,
        )

    @staticmethod
    def _plan_segments(total_duration: int) -> List[int]:
        """
        Split total_duration into chunks within [MIN_CLIP_SECONDS, MAX_CLIP_SECONDS].
        Examples:
            10s -> [10]
            20s -> [10, 10]
            25s -> [13, 12]
            30s -> [10, 10, 10]
        """
        if total_duration <= MAX_CLIP_SECONDS:
            return [total_duration]

        num_clips = -(-total_duration // MAX_CLIP_SECONDS)  # ceiling division
        base      = total_duration // num_clips
        segments  = [base] * num_clips
        remainder = total_duration - base * num_clips
        for i in range(remainder):
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
        """Single clip generation. Called in parallel for multi-clip videos."""

        arguments = {
            "prompt": (
                description.strip()
                or "Smooth cinematic car showcase. Highlight exterior design, wheels, and finish."
            ),
            "duration":       seconds,          # int, NOT string — matches real API spec
            "resolution":     resolution,
            "aspect_ratio":   aspect_ratio,
            "generate_audio": False,            # ALWAYS False — no audio requirement
            "camera_fixed":   False,            # allow camera movement for dynamic car shots
        }
        if image_url:
            arguments["image_url"] = image_url

        handler = await fal_client.submit_async(FAL_MODEL_ENDPOINT, arguments=arguments)
        result  = await handler.get()

        video_url  = result["video"]["url"]
        local_path = os.path.join(
            self.output_dir, f"clip_{index}_{uuid.uuid4().hex[:6]}.mp4"
        )
        self._download(video_url, local_path)
        return local_path

    @staticmethod
    def _download(url: str, dest_path: str) -> None:
        import urllib.request
        urllib.request.urlretrieve(url, dest_path)

    def _stitch_clips(self, clip_paths: List[str], job_id: str) -> str:
        """FFmpeg concat — no re-encoding, fast, lossless join."""
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
        os.remove(list_file)
        return final_path