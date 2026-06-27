"""
app.py
------
Simple Streamlit app to TEST the CarVideoEngine visually.

Upload 1-10 car photos, write a description, choose duration -> watch the
generated video right in the browser. This is for testing only (uses your
free fal.ai credit) - it is not the production mobile app.

Run:
    streamlit run app.py
"""

import os
import tempfile
import streamlit as st

from video_engine import CarVideoEngine, VideoRequest

st.set_page_config(page_title="Car Video AI - Test", page_icon="🚗", layout="centered")

st.title("🚗 Car Video AI — Test Console")
st.caption("Upload car photos + a description to test video generation before going to production.")

# ---------------------------------------------------------------------
# API key check
# ---------------------------------------------------------------------
api_key_present = bool(os.getenv("FAL_KEY"))
if not api_key_present:
    st.warning(
        "No FAL_KEY found. Add it to your `.env` file as `FAL_KEY=your_key_here`, "
        "then restart this app."
    )

# ---------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------
st.subheader("1. Upload car photos")
uploaded_files = st.file_uploader(
    "Upload 1–10 photos (JPG/PNG). At least one photo OR a description is required.",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

st.subheader("2. Description")
description = st.text_area(
    "Describe the car / desired video style",
    placeholder="e.g. 2021 Toyota Corolla, white, low mileage. Showcase exterior shine and alloy wheels.",
    height=100,
)

st.subheader("3. Settings")
col1, col2 = st.columns(2)
with col1:
    duration = st.slider("Video duration (seconds)", min_value=10, max_value=30, value=15, step=1)
with col2:
    resolution = st.selectbox("Resolution", ["720p", "480p"], help="720p = better quality | 480p = faster & cheaper for testing")

estimated_cost = round(duration * 0.022, 3)
st.info(f"Estimated cost for this test: **${estimated_cost}** (Seedance v1.5 Fast, $0.022/sec)")

generate_clicked = st.button("🎬 Generate Test Video", type="primary", disabled=not api_key_present)

# ---------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------
if generate_clicked:
    if not uploaded_files and not description.strip():
        st.error("Please upload at least one photo or write a description.")
        st.stop()

    # NOTE: fal.ai needs public image URLs. For local testing, we upload
    # each file to fal's own temporary storage so you don't need your own
    # hosting (Cloudflare R2 / S3) yet. This keeps testing free and simple.
    image_urls = []
    if uploaded_files:
        with st.spinner("Uploading photos..."):
            import fal_client
            for f in uploaded_files:
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(f.name)[1]) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                url = fal_client.upload_file(tmp_path)
                image_urls.append(url)
                os.remove(tmp_path)

    request = VideoRequest(
        image_urls=image_urls,
        description=description.strip(),
        total_duration=duration,
        resolution=resolution,
    )

    engine = CarVideoEngine()

    with st.spinner(f"Generating {duration}s video... this can take 30–90 seconds depending on length."):
        try:
            result = engine.generate(request)
        except Exception as e:
            st.error(f"Generation failed: {e}")
            st.stop()

    st.success("Done! Here's your test video:")
    st.video(result.output_path)

    st.markdown("### Result details")
    c1, c2, c3 = st.columns(3)
    c1.metric("Duration", f"{result.duration_seconds}s")
    c2.metric("Time taken", f"{result.generation_time_seconds}s")
    c3.metric("Cost", f"${result.estimated_cost_usd}")
    st.caption(f"Job ID: {result.job_id} · Clips stitched: {result.clip_count} · Saved at: {result.output_path}")