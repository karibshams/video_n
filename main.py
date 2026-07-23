"""
main.py — CLI usage example
Run: python main.py
"""

from video_engine import CarVideoEngine, VideoRequest

request = VideoRequest(
    image_urls=["https://example.com/car_front.jpg"],   # replace with real URL
    description="2022 Toyota Corolla, white, showcase exterior and wheels.",
    total_duration=20,
    resolution="720p",
    aspect_ratio="16:9",
)

result = CarVideoEngine().generate(request)

print(f"Output : {result.output_path}")
print(f"Clips  : {result.clip_count}")
print(f"Time   : {result.generation_time_seconds}s")
print(f"Cost   : ${result.estimated_cost_usd}")