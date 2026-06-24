import streamlit as st
import os
import io
import uuid
import asyncio
import concurrent.futures
import PyPDF2
import docx
from PIL import Image
from openai import OpenAI
import base64
import pandas as pd
from litellm import acompletion, aembedding
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc
from database.db_utils import get_chat_history, save_chat_message, get_document_markdown, archive_document
import numpy as np
import time

VLLM_API_BASE = os.getenv("VLLM_API_BASE", "http://localhost:8700/v1")
VLLM_DEFAULT_MODEL = os.getenv("VLLM_DEFAULT_MODEL", "openai/qwen2.5-vl-7b")

# --- SAFE ASYNC RUNNER ---
# Runs a coroutine in an isolated thread with its own event loop.
# This prevents Streamlit's script interruption from leaving coroutines
# dangling with the 'coroutine was never awaited' RuntimeWarning.
def run_safely(coroutine):
    """Runs an async coroutine safely in a dedicated background thread."""
    def _runner(coro):
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_runner, coroutine)
        return future.result()
# -----------------------------------------------------------

# --- CUSTOM LITELLM WRAPPERS FOR LOCAL OLLAMA ---
async def local_llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history_messages:
        messages.extend(history_messages)
    messages.append({"role": "user", "content": prompt})
    
    model_to_use = kwargs.get("model", VLLM_DEFAULT_MODEL)
    if "ollama/" in model_to_use:
        model_to_use = "openai/qwen2.5-vl-7b"
        
    llm_kwargs = {
        "model": model_to_use,
        "messages": messages,
    }
    if VLLM_API_BASE:
        llm_kwargs["api_base"] = VLLM_API_BASE

    response = await acompletion(**llm_kwargs)
    return response.choices[0].message.content

async def local_embedding_func(texts, **kwargs):
    emb_kwargs = {
        "model": "openai/nomic-embed-text",
        "input": texts,
    }
    if VLLM_API_BASE:
        emb_kwargs["api_base"] = VLLM_API_BASE

    response = await aembedding(**emb_kwargs)
    return np.array([data['embedding'] for data in response.data])
# -----------------------------------------------------------

def pil_to_bytes(img):
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return buffered.getvalue()

def extract_text_from_file(uploaded_file):
    filename = uploaded_file.name.lower()
    text_content = ""

    if filename.endswith(".pdf"):
        reader = PyPDF2.PdfReader(uploaded_file)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text_content += extracted + "\n"
                
    elif filename.endswith(".docx"):
        doc = docx.Document(uploaded_file)
        text_content = "\n".join([para.text for para in doc.paragraphs])
        
    elif filename.endswith((".txt", ".md", ".csv")):
        text_content = uploaded_file.getvalue().decode("utf-8")
        
    elif filename.endswith((".png", ".jpg", ".jpeg")):
        # Use vLLM Vision for fallback extraction
        img = Image.open(uploaded_file)
        img_bytes = pil_to_bytes(img)
        base64_img = base64.b64encode(img_bytes).decode('utf-8')
        client = OpenAI(base_url=VLLM_API_BASE, api_key="EMPTY")
        response = client.chat.completions.create(
            model='qwen2.5-vl-7b',
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'Extract all text and data from this image exactly.'},
                    {'type': 'image_url', 'image_url': {'url': f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }]
        )
        text_content = response.choices[0].message.content

    return text_content


def generate_documents_from_excel(freq_path, item_path, services_path):
    """Read three Excel files and generate natural-language documents per LightRAG ingestion prompt."""
    docs = []

    # Frequency
    try:
        df = pd.read_excel(freq_path).fillna("NIL")
        for _, row in df.iterrows():
            docs.append(
                f"The frequency code {row.get('Frequency','NIL')} means {row.get('Meaning','NIL')}. "
                f"It is administered at {row.get('Administration Timing','NIL')}. "
                f"Patient instruction: {row.get('Example Instruction','NIL')}."
            )
    except Exception:
        pass

    # Item Master
    # NOTE: IL2_NAME is intentionally skipped because it is empty in most rows and adds noise.
    try:
        if isinstance(item_path, str) and item_path.lower().endswith(".jsonl"):
            df = pd.read_json(item_path, lines=True).fillna("NIL")
        else:
            df = pd.read_excel(item_path).fillna("NIL")
        for _, row in df.iterrows():
            docs.append(
                f"Item {row.get('ITEM_CD','NIL')} is named {row.get('ITEM_NAME','NIL')}. "
                f"It belongs to category {row.get('IL1_NAME','NIL')} and type {row.get('IL3_NAME','NIL')}. "
                f"The manufacturer is {row.get('MNF_NAME','NIL')}.")
    except Exception:
        pass

    # Tenet Services
    try:
        df = pd.read_excel(services_path).fillna("NIL")
        for _, row in df.iterrows():
            docs.append(
                f"Service {row.get('SERVICE_CD','NIL')} is named {row.get('SERVICE_NAME','NIL')}. "
                f"It is priced at {row.get('PRICE','NIL')}. "
                f"Specimen required: {row.get('SPECIMEN','NIL')}. "
                f"Method: {row.get('METHOD','NIL')}. "
                f"Sample type: {row.get('SampleType','NIL')}. "
                f"Patient instruction: {row.get('PatInstruction','NIL')}. "
                f"Specialization: {row.get('SPECIALIZATION','NIL')}. "
                f"Category: {row.get('SERVICE_CATEGEORY','NIL')}."
            )
    except Exception:
        pass

    return docs

# --- LIGHTRAG EXECUTION BLOCKS ---
async def _async_insert_text(user_id, documents):
    if isinstance(documents, str):
        documents = [documents]

    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    workspace_dir = os.path.join(BASE_DIR, "database", f"rag_workspace_user_{user_id}")
    os.makedirs(workspace_dir, exist_ok=True)

    rag = LightRAG(
        working_dir=workspace_dir,
        llm_model_func=local_llm_func,
        embedding_func=EmbeddingFunc(
            embedding_dim=768, # IMPORTANT: Nomic-embed-text uses 768 dimensions
            max_token_size=8192,
            func=local_embedding_func
        )
    )
    await rag.initialize_storages()
    await rag.ainsert(documents)
    return True


async def _async_query_graph(user_id, prompt, target_language, llm_model="openai/qwen2.5-vl-7b"):
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    workspace_dir = os.path.join(BASE_DIR, "database", f"rag_workspace_user_{user_id}")

    rag = LightRAG(
        working_dir=workspace_dir,
        llm_model_func=local_llm_func,
        llm_model_kwargs={"model": llm_model},
        embedding_func=EmbeddingFunc(
            embedding_dim=768,
            max_token_size=8192,
            func=local_embedding_func
        )
    )

    await rag.initialize_storages()

    query_prompt = f"User Query: {prompt}\nSystem Instructions: Answer using ONLY the provided context. Provide final response translated into: {target_language}."

    response = await rag.aquery(query_prompt, param=QueryParam(mode="hybrid"))

    # Normalize return type to string for Streamlit display
    try:
        if isinstance(response, dict) and 'content' in response:
            return response['content']
        return str(response)
    except Exception:
        return str(response)
# -----------------------------------------------------------

def render_rag_app():
    st.header("🕸️ Multi-lingual Context Graph Chatbot (Local)")
    st.info("Knowledge graph is securely stored on your local disk. 0 bytes are sent to the cloud.")

    if 'rag_doc_session_id' not in st.session_state:
        st.session_state.rag_doc_session_id = str(uuid.uuid4())
        
    user_id = st.session_state.get("user_id", 1)
    session_id = st.session_state.rag_doc_session_id

    if 'graph_built' not in st.session_state:
        workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "database", f"rag_workspace_user_{user_id}"))
        if os.path.exists(workspace_dir) and len(os.listdir(workspace_dir)) > 0:
            st.session_state.graph_built = True
        else:
            st.session_state.graph_built = False

    # --- VAULT INTERCEPTION LOGIC ---
    if "docs_to_rag" in st.session_state and st.session_state.docs_to_rag:
        docs = st.session_state.docs_to_rag
        
        with st.spinner(f"Loading {len(docs)} documents directly from Vault into local Knowledge Graph..."):
            combined_text = ""
            for doc_id, filename in docs:
                md_text = get_document_markdown(doc_id, user_id)
                if md_text:
                    combined_text += f"\n\n--- Document: {filename} ---\n{md_text}"
            
            if combined_text:
                try:
                    success = run_safely(_async_insert_text(user_id, combined_text))
                    if success:
                        st.session_state.graph_built = True
                        st.success(f"Successfully injected {len(docs)} vaulted documents into the Graph without uploading!")
                except Exception as e:
                    st.error(f"Failed to load from vault: {str(e)}")
        
        st.session_state.docs_to_rag = []

    with st.sidebar:
        st.subheader("🗣️ Language Options")
        target_language = st.selectbox("Output Language", ["English", "Hindi", "Spanish", "Telugu", "French", "German"])
        
        st.divider()
        st.subheader("🧠 Engine Info")
        st.caption("Active Model: `qwen2.5vl:32b` (Fixed)")
        
        st.divider()
        st.subheader("📤 Upload Context")
        uploaded_files = st.file_uploader("Upload files", type=["pdf", "docx", "txt", "png", "jpg", "jpeg"], accept_multiple_files=True)
        with st.expander("📥 Ingest Excel Datasets (Frequency / ItemMaster / Services)"):
            freq_default = os.path.join(os.path.dirname(__file__), "..", "datasets", "Frequency.xlsx")
            item_default = os.path.join(os.path.dirname(__file__), "..", "datasets", "itemmaster_sri_sri.xlsx")
            services_default = os.path.join(os.path.dirname(__file__), "..", "datasets", "TenetServices.xlsx")

            freq_path = st.text_input("Frequency Excel Path", value=freq_default)
            item_path = st.text_input("ItemMaster Excel Path", value=item_default)
            services_path = st.text_input("Services Excel Path", value=services_default)

            if st.button("Ingest Excel Datasets", key="ingest_excel_btn"):
                docs = generate_documents_from_excel(freq_path, item_path, services_path)
                if not docs:
                    st.warning("No documents generated from the provided Excel files.")
                else:
                    try:
                        success = run_safely(_async_insert_text(user_id, docs))
                        if success:
                            st.success(f"Ingested {len(docs)} rows into the local RAG workspace.")
                            st.session_state.graph_built = True
                    except Exception as e:
                        st.error(f"Excel ingestion failed: {e}")
        
        if st.button("Process Documents", width='stretch'):
            if not uploaded_files:
                st.warning("Please upload at least one document.")
            else:
                with st.spinner("Vectorizing locally via Nomic-Embed..."):
                    start_time = time.time()
                    combined_text = ""
                    for file in uploaded_files:
                        extracted = extract_text_from_file(file)
                        combined_text += f"\n\n--- Document: {file.name} ---\n{extracted}"
                        
                        if extracted.strip():
                            archive_document(
                                user_id=user_id, 
                                filename=file.name, 
                                category="RAG_CONTEXT", 
                                markdown=extracted, 
                                confidence=100.0 
                            )
                    
                    if combined_text.strip():
                        try:
                            success = run_safely(_async_insert_text(user_id, combined_text))
                            if success:
                                st.session_state.graph_built = True
                                elapsed_time = time.time() - start_time
                                st.success(f"Documents processed in {elapsed_time:.2f}s & Saved to Vault!")
                                time.sleep(2)
                                st.rerun()

                        except Exception as e:
                            st.error(f"Failed to build graph: {str(e)}")
                    else:
                        st.error("Could not extract any text from the uploaded documents.")
        
        st.divider()
        if st.button("🧹 Clear Chat History", width='stretch'):
            st.session_state.rag_doc_session_id = str(uuid.uuid4())
            st.rerun()

    chat_history = get_chat_history(user_id, "LightRAG", session_id)
    
    for message in chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("Ask a question about your documents..."):
        if not st.session_state.graph_built:
            st.warning("Please upload and process documents first before asking questions.")
            return

        with st.chat_message("user"):
            st.markdown(prompt)
        save_chat_message(user_id, "LightRAG", session_id, "user", prompt)

        with st.chat_message("assistant"):
            with st.spinner(f"reasoning via {selected_llm}..."):
                start_time = time.time()
                try:
                    response = run_safely(_async_query_graph(user_id, prompt, target_language, llm_model="openai/qwen2.5-vl-7b"))
                    
                    # Clean up <|think|> tags if they bleed into chat output
                    if "<channel|>" in response:
                        response = response.split("<channel|>")[-1].strip()
                    end_time = time.time() # ⏱️ END TIMER
                    elapsed_time = end_time - start_time
                        
                    # Append the time to the bottom of the assistant's response visually
                    visual_response = response + f"\n\n*⏱️ Generated locally in {elapsed_time:.2f}s*"
                    
                    st.markdown(visual_response)
                    save_chat_message(user_id, "LightRAG", session_id, "assistant", response)
                except Exception as e:
                    st.error(f"Error querying graph: {str(e)}")
        
        st.rerun()