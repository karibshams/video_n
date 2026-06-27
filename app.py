"""
app.py
------
Streamlit test console for the CarVideoEngine.

Upload car photos + write a description → generate a silent promotional
video using Seedance v1.5 Pro (fal.ai) → watch it right in the browser.

This is a TESTING tool only — not the production mobile app.

Run:
    streamlit run app.py
"""

import os
import tempfile
import streamlit as st
import fal_client

from video_engine import CarVideoEngine, VideoRequest, VALID_RESOLUTIONS

# ------------------------------------------------------------------
# Page config
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Car Video AI — Test Console",
    page_icon="🚗",
    layout="centered",
)

st.title("🚗 Car Video AI — Test Console")
st.caption(
    "Model: Seedance v1.5 Pro image-to-video (fal.ai) · "
    "No audio · Silent promotional video"
)

# ------------------------------------------------------------------
# API key check
# ------------------------------------------------------------------
fal_key = os.getenv("FAL_KEY", "")
if not fal_key:
    st.error(
        "⚠️ FAL_KEY not found in your .env file.\n\n"
        "Add this line to your `.env` file and restart:\n"
        "`FAL_KEY=your_api_key_here`\n\n"
        "Get your key: fal.ai → Settings → API Keys"
    )
    st.stop()
else:
    st.success("✅ FAL_KEY loaded — ready to generate.")

# ------------------------------------------------------------------
# Input: Car photos
# ------------------------------------------------------------------
st.subheader("1. Upload car photos")
st.caption("Upload 1–10 car photos. The model uses the first photo as the reference frame.")
uploaded_files = st.file_uploader(
    "Accepted: JPG, JPEG, PNG, WEBP",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
)
if uploaded_files and len(uploaded_files) > 10:
    st.warning("Maximum 10 photos. Only the first 10 will be used.")
    uploaded_files = uploaded_files[:10]

# ------------------------------------------------------------------
# Input: Description
# ------------------------------------------------------------------
st.subheader("2. Car description")
st.caption("Describe the car and how you want the video to look. Be specific for better results.")
description = st.text_area(
    "Description / prompt",
    placeholder=(
        "e.g. 2022 Toyota Corolla, white exterior, clean interior, low mileage. "
        "Smooth cinematic showcase of the exterior, alloy wheels, and interior. "
        "Slow orbit camera, bright daylight."
    ),
    height=120,
)

# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------
st.subheader("3. Video settings")
col1, col2, col3 = st.columns(3)
with col1:
    duration = st.slider(
        "Duration (seconds)", min_value=10, max_value=30, value=15, step=1
    )
with col2:
    resolution = st.selectbox(
        "Resolution",
        options=list(VALID_RESOLUTIONS),
        index=0,
        help="720p = production quality | 480p = faster & cheaper for testing",
    )
with col3:
    aspect_ratio = st.selectbox(
        "Aspect ratio",
        options=["16:9", "9:16", "4:3", "1:1"],
        index=0,
        help="16:9 recommended for car showcase videos",
    )

# Cost estimate
from video_engine import CarVideoEngine
est_cost = CarVideoEngine.estimate_cost(duration, resolution)
clips_needed = max(1, -(-duration // 12))   # ceiling division
st.info(
    f"**Estimated cost:** ~${est_cost} USD  |  "
    f"**Clips to generate:** {clips_needed} (run in parallel)  |  "
    f"**Expected wait:** ~{30 + (clips_needed - 1) * 5}–{60}s"
)

# ------------------------------------------------------------------
# Generate
# ------------------------------------------------------------------
generate_clicked = st.button("🎬 Generate Video", type="primary", use_container_width=True)

if generate_clicked:
    if not uploaded_files and not description.strip():
        st.error("Please upload at least one photo OR write a description.")
        st.stop()

    # Upload photos to fal.ai temporary storage (gives us public URLs)
    image_urls = []
    if uploaded_files:
        with st.spinner(f"Uploading {len(uploaded_files)} photo(s) to fal.ai storage..."):
            for f in uploaded_files:
                ext = os.path.splitext(f.name)[1] or ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                try:
                    url = fal_client.upload_file(tmp_path)
                    image_urls.append(url)
                finally:
                    os.remove(tmp_path)
        st.caption(f"✅ {len(image_urls)} photo(s) uploaded.")

    # Build request
    request = VideoRequest(
        image_urls=image_urls,
        description=description.strip(),
        total_duration=duration,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
    )

    # Run engine
    engine = CarVideoEngine()
    progress_text = (
        f"Generating {duration}s video in {clips_needed} parallel clip(s)... "
        f"please wait 30–90 seconds."
    )
    with st.spinner(progress_text):
        try:
            result = engine.generate(request)
        except Exception as e:
            st.error(f"Generation failed: {e}")
            st.stop()

    # Show result
    st.success("✅ Video generated successfully!")
    st.video(result.output_path)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Duration",    f"{result.duration_seconds}s")
    col2.metric("Time taken",  f"{result.generation_time_seconds}s")
    col3.metric("Cost",        f"${result.estimated_cost_usd}")
    col4.metric("Clips made",  result.clip_count)

    st.caption(
        f"Job ID: `{result.job_id}` · "
        f"Saved at: `{result.output_path}` · "
        f"Model: Seedance v1.5 Pro (fal-ai/bytedance/seedance/v1.5/pro/image-to-video)"
    )

    # Download button
    with open(result.output_path, "rb") as vf:
        st.download_button(
            label="⬇️ Download video",
            data=vf,
            file_name=f"car_video_{result.job_id}.mp4",
            mime="video/mp4",
        )