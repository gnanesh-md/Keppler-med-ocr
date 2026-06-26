import streamlit as st
import requests
import time
import os

st.set_page_config(
    page_title="Keppler Medical Document Intelligence",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API Configuration
# In production, this would be an environment variable pointing to the FastAPI Gateway
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")

st.title("⚕️ Keppler Medical Intelligence Platform")
st.markdown("### Next-Generation Asynchronous Document Processing")

st.info(
    "**Architecture Upgrade:** This UI is now a 'Thin Client'. "
    "All document processing is offloaded to highly scalable Celery background workers and FastAPI microservices. "
    "Uploading a 1000-page PDF will no longer freeze your browser."
)

st.sidebar.header("Document Intake")
uploaded_file = st.sidebar.file_uploader(
    "Upload Clinical Record", 
    type=["pdf", "png", "jpg", "jpeg", "tiff"]
)

if uploaded_file is not None:
    if st.sidebar.button("Initiate Extraction", type="primary"):
        
        st.markdown("### Extraction Telemetry")
        
        with st.spinner("Uploading binary securely to API Gateway..."):
            # 1. Dispatch file via REST API (Layer 1 Intake)
            files = {"file": (uploaded_file.name, uploaded_file, uploaded_file.type)}
            
            try:
                response = requests.post(f"{API_BASE_URL}/document/upload", files=files)
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                st.error(f"API Gateway Unreachable: Ensure FastAPI is running on port 8000. \n\nDetails: {e}")
                st.stop()
                
            data = response.json()
            job_id = data["job_id"]
            doc_hash = data["document_hash"]
            
            st.success(f"**Document Fingerprint:** `{doc_hash}` | **Tracking ID:** `{job_id}`")
            st.markdown("---")
            
            # 2. Setup Non-Blocking Polling UI
            col1, col2 = st.columns([3, 1])
            with col1:
                progress_bar = st.progress(0)
            with col2:
                status_badge = st.empty()
                
            log_container = st.empty()
            
            # 3. Asynchronous Polling Loop
            state = "PENDING"
            while True:
                try:
                    status_res = requests.get(f"{API_BASE_URL}/job/{job_id}")
                    if status_res.status_code == 200:
                        status_data = status_res.json()
                        progress = status_data["progress"]
                        state = status_data["status"]
                        
                        # Update Telemetry UI
                        progress_bar.progress(int(progress))
                        
                        if state == "PROCESSING":
                            status_badge.info(f"⚙️ {state} ({progress}%)")
                        elif state == "COMPLETED":
                            status_badge.success(f"✅ {state}")
                        elif state == "FAILED":
                            status_badge.error(f"❌ {state}")
                        else:
                            status_badge.warning(f"⏳ {state}")
                            
                        # Simulated granular log tailing (In production, route via WebSockets)
                        if progress < 10:
                            log_container.code("[Worker] Securing document payload...")
                        elif progress < 30:
                            log_container.code("[Worker] Executing OpenCV enhancement & YOLO Layout constraints...")
                        elif progress < 70:
                            log_container.code("[Worker] Executing batched asynchronous Region OCR via vLLM...")
                        elif progress < 85:
                            log_container.code("[Worker] Running zero-temperature NLP Medical Corrections...")
                        elif progress < 100:
                            log_container.code("[Worker] Compiling master JSON schemas & Map-Reduce Summaries...")
                            
                        if state in ["COMPLETED", "FAILED"]:
                            break
                except requests.exceptions.RequestException:
                    st.warning("Lost connection to API Gateway. Retrying...")
                    
                # Poll every 2 seconds to prevent API hammering
                time.sleep(2)
                
            if state == "COMPLETED":
                st.balloons()
                st.markdown("### Master Clinical Summary")
                st.success("Extraction Complete! The background worker has securely compiled the final clinical report.")
                
                # Fetch and render the final report
                # In full implementation, we'd GET /api/v1/job/{job_id}/results
                st.code("JSON Extraction Schemas and Timeline available in backend cache.")
            else:
                st.error("Extraction failed critically in the background worker. Check Celery logs.")
else:
    st.markdown("### Welcome to the Next Generation Architecture.")
    st.markdown("⬅️ Please upload a document via the sidebar to trigger the asynchronous distributed pipeline.")
