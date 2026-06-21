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
# Configuration
# ---------------------------------------------------------------------------

FAL_MODEL_ENDPOINT = "fal-ai/bytedance/seedance/v1.5/fast/image-to-video"
MAX_CLIP_SECONDS = 12          # hard model limit per single call
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs")


@dataclass
class VideoRequest:
    """Everything needed to generate one car video."""
    image_urls: List[str]                     # 1-10 car photo URLs (hosted, publicly reachable)
    description: str = ""                     # optional text description
    total_duration: int = 15                   # desired final video length, 10-30s
    resolution: str = "1080p"                  # "720p" or "1080p"
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def __post_init__(self):
        if not self.image_urls and not self.description:
            raise ValueError("Provide at least one image or a description.")
        self.total_duration = max(10, min(30, self.total_duration))


@dataclass
class VideoResult:
    job_id: str
    output_path: str
    clip_count: int
    duration_seconds: int
    generation_time_seconds: float
    estimated_cost_usd: float


class CarVideoEngine:
    """
    Wraps Seedance v1.5 Fast to turn car photos + description into a single
    silent promotional video of any length between 10-30 seconds.
    """

    COST_PER_SECOND = 0.022  # Seedance v1.5 Fast pricing on fal.ai

    def __init__(self, api_key: Optional[str] = None, output_dir: str = OUTPUT_DIR):
        self.api_key = api_key or os.getenv("FAL_KEY")
        if not self.api_key:
            raise RuntimeError("FAL_KEY not set. Put it in your .env file.")
        os.environ["FAL_KEY"] = self.api_key  # fal_client reads this env var

        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, request: VideoRequest) -> VideoResult:
        """Synchronous entry point. Runs the async pipeline under the hood."""
        return asyncio.run(self._generate_async(request))

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    async def _generate_async(self, request: VideoRequest) -> VideoResult:
        start = time.time()

        segments = self._plan_segments(request.total_duration, len(request.image_urls))

        # Fire all clip generations in parallel
        tasks = [
            self._generate_clip(
                image_url=request.image_urls[i % len(request.image_urls)] if request.image_urls else None,
                description=request.description,
                seconds=seg_len,
                resolution=request.resolution,
                index=i,
            )
            for i, seg_len in enumerate(segments)
        ]
        clip_paths = await asyncio.gather(*tasks)

        # Stitch if more than one clip, otherwise just use the single clip
        if len(clip_paths) > 1:
            final_path = self._stitch_clips(clip_paths, request.job_id)
        else:
            final_path = clip_paths[0]

        elapsed = round(time.time() - start, 1)
        cost = round(sum(segments) * self.COST_PER_SECOND, 3)

        return VideoResult(
            job_id=request.job_id,
            output_path=final_path,
            clip_count=len(segments),
            duration_seconds=sum(segments),
            generation_time_seconds=elapsed,
            estimated_cost_usd=cost,
        )

    def _plan_segments(self, total_duration: int, image_count: int) -> List[int]:
        """
        Split total_duration into chunks no larger than MAX_CLIP_SECONDS.
        e.g. 30s -> [10, 10, 10], 20s -> [10, 10], 12s -> [12]
        """
        if total_duration <= MAX_CLIP_SECONDS:
            return [total_duration]

        num_clips = -(-total_duration // MAX_CLIP_SECONDS)  # ceil division
        base = total_duration // num_clips
        segments = [base] * num_clips
        # distribute remainder seconds across the first few clips
        remainder = total_duration - base * num_clips
        for i in range(remainder):
            segments[i] += 1
        return segments

    async def _generate_clip(
        self,
        image_url: Optional[str],
        description: str,
        seconds: int,
        resolution: str,
        index: int,
    ) -> str:
        """Calls Seedance v1.5 Fast for a single clip and downloads the result."""

        arguments = {
            "prompt": description or "Smooth cinematic showcase of the car, highlighting design and details.",
            "duration": str(min(seconds, MAX_CLIP_SECONDS)),
            "resolution": resolution,
            "generate_audio": False,  # hard requirement: no audio, ever
        }
        if image_url:
            arguments["image_url"] = image_url

        handler = await fal_client.submit_async(FAL_MODEL_ENDPOINT, arguments=arguments)
        result = await handler.get()

        video_url = result["video"]["url"]
        local_path = os.path.join(self.output_dir, f"clip_{index}_{uuid.uuid4().hex[:6]}.mp4")
        self._download(video_url, local_path)
        return local_path

    @staticmethod
    def _download(url: str, dest_path: str) -> None:
        import urllib.request
        urllib.request.urlretrieve(url, dest_path)

    def _stitch_clips(self, clip_paths: List[str], job_id: str) -> str:
        """Joins clips end-to-end with FFmpeg (no re-encoding when codecs match)."""
        list_file = os.path.join(self.output_dir, f"concat_{job_id}.txt")
        with open(list_file, "w") as f:
            for path in clip_paths:
                f.write(f"file '{os.path.abspath(path)}'\n")

        final_path = os.path.join(self.output_dir, f"final_{job_id}.mp4")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", final_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        os.remove(list_file)
        return final_path