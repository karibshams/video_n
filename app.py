"""
app.py
------
Streamlit test console for CarVideoEngine.
Upload car photos + description -> generate a silent video -> watch in browser.

Run:
    streamlit run app.py
"""

import os
import tempfile
import streamlit as st

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
    "Model: Seedance v1.5 Pro (fal-ai/bytedance/seedance/v1.5/pro/image-to-video) · "
    "No audio · Silent car promotional video"
)

# ------------------------------------------------------------------
# API key check — must be in .env before starting
# ------------------------------------------------------------------
fal_key = os.getenv("FAL_KEY", "")
if not fal_key:
    st.error(
        "FAL_KEY not found.\n\n"
        "1. Open your `.env` file\n"
        "2. Add: `FAL_KEY=your_api_key_here`\n"
        "3. Restart: `streamlit run app.py`\n\n"
        "Get your key: fal.ai → Settings → API Keys"
    )
    st.stop()

st.success("✅ FAL_KEY loaded.")

# ------------------------------------------------------------------
# Section 1: Car photos
# ------------------------------------------------------------------
st.subheader("1. Upload car photos")
st.caption("1–10 photos. The first photo is used as the video start frame.")

uploaded_files = st.file_uploader(
    "JPG / JPEG / PNG / WEBP",
    type=["jpg", "jpeg", "png", "webp"],
    accept_multiple_files=True,
)
if uploaded_files and len(uploaded_files) > 10:
    st.warning("Only the first 10 photos will be used.")
    uploaded_files = uploaded_files[:10]

# ------------------------------------------------------------------
# Section 2: Description
# ------------------------------------------------------------------
st.subheader("2. Car description")
description = st.text_area(
    "Describe the car and the video style you want",
    placeholder=(
        "e.g. 2022 Toyota Corolla, white exterior, low mileage, clean interior. "
        "Smooth cinematic showcase of the exterior, alloy wheels, and interior. "
        "Slow orbit camera, bright daylight, no text overlays."
    ),
    height=120,
)

# ------------------------------------------------------------------
# Section 3: Settings
# ------------------------------------------------------------------
st.subheader("3. Video settings")
col1, col2, col3 = st.columns(3)
with col1:
    duration = st.slider("Duration (sec)", min_value=10, max_value=30, value=15, step=1)
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
        help="16:9 = landscape, best for car videos",
    )

# Live cost + timing estimate
est_cost     = CarVideoEngine.estimate_cost(duration, resolution)
clips_needed = -(-duration // 12)   # ceiling division
st.info(
    f"**Estimated cost:** ~${est_cost} USD  |  "
    f"**Clips (parallel):** {clips_needed}  |  "
    f"**Expected wait:** ~30–90s"
)

# ------------------------------------------------------------------
# Generate
# ------------------------------------------------------------------
generate_clicked = st.button(
    "🎬 Generate Video", type="primary", use_container_width=True
)

if generate_clicked:
    if not uploaded_files and not description.strip():
        st.error("Upload at least one photo OR write a description.")
        st.stop()

    # Upload photos to fal.ai temp storage to get public URLs
    import fal_client
    image_urls = []
    if uploaded_files:
        with st.spinner(f"Uploading {len(uploaded_files)} photo(s)..."):
            for f in uploaded_files:
                ext = os.path.splitext(f.name)[1] or ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                try:
                    url = fal_client.upload_file(tmp_path)
                    image_urls.append(url)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
        st.caption(f"✅ {len(image_urls)} photo(s) uploaded to fal.ai storage.")

    # Build request and run engine
    request = VideoRequest(
        image_urls=image_urls,
        description=description.strip(),
        total_duration=duration,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
    )

    engine = CarVideoEngine()
    with st.spinner(f"Generating {duration}s video ({clips_needed} clip(s) in parallel)..."):
        try:
            result = engine.generate(request)
        except Exception as e:
            st.error(f"Generation failed:\n\n{e}")
            st.stop()

    # Results
    st.success("✅ Done!")
    st.video(result.output_path)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Duration",   f"{result.duration_seconds}s")
    c2.metric("Time taken", f"{result.generation_time_seconds}s")
    c3.metric("Cost",       f"${result.estimated_cost_usd}")
    c4.metric("Clips",      result.clip_count)

    st.caption(f"Job: `{result.job_id}` · File: `{result.output_path}`")

    with open(result.output_path, "rb") as vf:
        st.download_button(
            label="⬇️ Download MP4",
            data=vf,
            file_name=f"car_video_{result.job_id}.mp4",
            mime="video/mp4",
        )