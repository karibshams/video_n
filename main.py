"""
main.py
-------
Entry point. Shows how to use CarVideoEngine to turn car photos + a
description into a finished silent promotional video.

Run:
    python main.py
"""

from video_engine import CarVideoEngine, VideoRequest


def main():
    engine = CarVideoEngine()

    request = VideoRequest(
        image_urls=[
            "https://example.com/car_front.jpg",
            "https://example.com/car_side.jpg",
            "https://example.com/car_interior.jpg",
        ],
        description=(
            "2021 Toyota Corolla, white, low mileage, clean interior. "
            "Showcase exterior shine, alloy wheels, and spacious interior."
        ),
        total_duration=20,   # any value 10-30 is accepted
        resolution="1080p",
    )

    print(f"Generating {request.total_duration}s video (job {request.job_id})...")
    result = engine.generate(request)

    print("\nDone.")
    print(f"  Output file     : {result.output_path}")
    print(f"  Clips generated : {result.clip_count}")
    print(f"  Final duration  : {result.duration_seconds}s")
    print(f"  Time taken      : {result.generation_time_seconds}s")
    print(f"  Estimated cost  : ${result.estimated_cost_usd}")


if __name__ == "__main__":
    main()