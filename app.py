"""
app.py — Streamlit test console
Run: streamlit run app.py
"""

import os
import tempfile
import fal_client
import streamlit as st
from video_engine import CarVideoEngine, VideoRequest

st.set_page_config(page_title="Car Video AI Test", page_icon="🚗")
st.title("🚗 Car Video AI — Test Console")

# API key check
if not os.getenv("FAL_KEY"):
    st.error("FAL_KEY not found in .env — add it and restart.")
    st.stop()
st.success("✅ FAL_KEY loaded.")

# Inputs
st.subheader("1. Car photos")
files = st.file_uploader("Upload 1–10 car photos (JPG/PNG/WEBP)",
                          type=["jpg","jpeg","png","webp"],
                          accept_multiple_files=True)
if files and len(files) > 10:
    files = files[:10]

st.subheader("2. Description")
description = st.text_area("Describe the car and video style",
    placeholder="e.g. 2022 Toyota Corolla white, showcase exterior and wheels, slow orbit camera.")

st.subheader("3. Settings")
c1, c2, c3 = st.columns(3)
duration     = c1.slider("Duration (sec)", 10, 30, 15)
resolution   = c2.selectbox("Resolution", ["720p", "480p"])
aspect_ratio = c3.selectbox("Aspect ratio", ["16:9", "9:16", "4:3", "1:1"])

clips_needed = -(-duration // 12)
st.info(f"Estimated cost: ~${round(duration * 21504 * 0.0000012, 3)} USD · Clips: {clips_needed} · Wait: ~30–90s")

# Generate
if st.button("🎬 Generate Video", type="primary", use_container_width=True):
    if not files and not description.strip():
        st.error("Upload a photo or write a description.")
        st.stop()

    image_urls = []
    if files:
        with st.spinner("Uploading photos..."):
            for f in files:
                ext = os.path.splitext(f.name)[1] or ".jpg"
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                try:
                    image_urls.append(fal_client.upload_file(tmp_path))
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

    request = VideoRequest(
        image_urls=image_urls,
        description=description.strip(),
        total_duration=duration,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
    )

    with st.spinner(f"Generating {duration}s video..."):
        try:
            result = CarVideoEngine().generate(request)
        except Exception as e:
            st.error(f"Failed: {e}")
            st.stop()

    st.success("✅ Done!")
    st.video(result.output_path)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Duration",  f"{result.duration_seconds}s")
    c2.metric("Time",      f"{result.generation_time_seconds}s")
    c3.metric("Cost",      f"${result.estimated_cost_usd}")
    c4.metric("Clips",     result.clip_count)

    with open(result.output_path, "rb") as vf:
        st.download_button("⬇️ Download MP4", vf,
                           file_name=f"car_{result.job_id}.mp4", mime="video/mp4")