import os
import io
import PyPDF2
import docx
from PIL import Image
from openai import OpenAI
import base64
import pandas as pd
from litellm import acompletion, aembedding
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc
import numpy as np

VLLM_API_BASE = os.getenv("VLLM_API_BASE", "http://localhost:8700/v1")
VLLM_DEFAULT_MODEL = os.getenv("VLLM_DEFAULT_MODEL", "openai/qwen2.5-vl-7b")

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

    # Normalize return type to a plain string for the API response
    try:
        if isinstance(response, dict) and 'content' in response:
            return response['content']
        return str(response)
    except Exception:
        return str(response)
# -----------------------------------------------------------
