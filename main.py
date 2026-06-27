"""
main.py
-------
Example usage of CarVideoEngine. Run this to test from command line.

Usage:
    python main.py
"""

from video_engine import CarVideoEngine, VideoRequest


def main():
    engine = CarVideoEngine()

    # Replace these URLs with real publicly accessible car photo URLs
    # For testing, upload photos via the Streamlit app (app.py) instead
    request = VideoRequest(
        image_urls=[
            "https://example.com/car_front.jpg",   # replace with real URL
            "https://example.com/car_side.jpg",    # replace with real URL
        ],
        description=(
            "2022 Toyota Corolla, white, low mileage, clean interior. "
            "Smooth cinematic showcase of exterior shine, alloy wheels, "
            "and spacious interior. Slow orbit camera, bright daylight."
        ),
        total_duration=20,      # 10–30 seconds
        resolution="720p",      # "720p" production | "480p" testing
        aspect_ratio="16:9",    # landscape — best for car videos
    )

    print(f"[CarVideoEngine] Generating {request.total_duration}s video (job: {request.job_id})")
    print(f"  Model    : fal-ai/bytedance/seedance/v1.5/pro/image-to-video")
    print(f"  Audio    : disabled")
    print(f"  Est cost : ~${CarVideoEngine.estimate_cost(request.total_duration, request.resolution)} USD")
    print()

    result = engine.generate(request)

    print("Done.")
    print(f"  Output file  : {result.output_path}")
    print(f"  Clips made   : {result.clip_count}")
    print(f"  Duration     : {result.duration_seconds}s")
    print(f"  Time taken   : {result.generation_time_seconds}s")
    print(f"  Actual cost  : ${result.estimated_cost_usd} USD")


if __name__ == "__main__":
    main()