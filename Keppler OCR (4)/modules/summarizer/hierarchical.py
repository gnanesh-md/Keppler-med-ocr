import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

class HierarchicalSummarizer:
    """
    Executes the Map-Reduce summarization strategy.
    Maps extraction prompts across all chunks and reduces them into a single structured schema.
    """
    def __init__(self, model_name: str = "qwen2.5-vl-7b", base_url: str = "http://localhost:8700/v1"):
        self.model_name = model_name
        # Using synchronous client since this is run in a standard Streamlit thread with sequential progress
        self.client = OpenAI(base_url=base_url, api_key="EMPTY")
        
    def _extract_chunk_data(self, chunk_text: str) -> dict:
        from .blueprint_summary import load_blueprint, build_extraction_prompt
        BP = load_blueprint()
        prompt = build_extraction_prompt(BP, chunk_text)
        
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=8192
            )
            raw = resp.choices[0].message.content.strip()
            
            # Robust JSON extraction
            import re
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                raw = match.group(0)
            
            data = json.loads(raw)
            return data
        except Exception as e:
            logger.error(f"Chunk extraction failed: {e}")
            # Return empty skeleton to prevent pipeline crash
            return {}

    def process_chunks(self, chunker, progress_callback=None) -> dict:
        """
        Processes chunks concurrently. Utilizes local caching if available.
        Merges results into a master structured dictionary.
        """
        import concurrent.futures
        from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

        chunks = chunker.get_chunks()
        total = len(chunks)
        ctx = get_script_run_ctx()
        
        master_data = {}
        
        def _process_single_chunk(i, chunk_text, ctx):
            if ctx:
                add_script_run_ctx(ctx=ctx)
            data = chunker.load_cached_chunk(i)
            if not data:
                data = self._extract_chunk_data(chunk_text)
                chunker.save_chunk_cache(i, data)
            return i, data

        results = [None] * total
        completed = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {}
            for i, chunk_text in enumerate(chunks):
                future = executor.submit(_process_single_chunk, i, chunk_text, ctx)
                futures[future] = i
                
            for future in concurrent.futures.as_completed(futures):
                idx, data = future.result()
                results[idx] = data
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)
                    
        # Deep merge sections from each chunk into master_data
        for data in results:
            if not data or not isinstance(data, dict):
                continue
            for sec_id, sec_dict in data.items():
                if not isinstance(sec_dict, dict):
                    continue
                if sec_id not in master_data:
                    master_data[sec_id] = {}
                for key, val in sec_dict.items():
                    if val is not None:
                        # For lists (tables), concatenate to avoid losing earlier rows
                        if isinstance(val, list):
                            if key not in master_data[sec_id]:
                                master_data[sec_id][key] = []
                            if isinstance(master_data[sec_id][key], list):
                                for item in val:
                                    if item and item not in master_data[sec_id][key]:
                                        master_data[sec_id][key].append(item)
                        elif isinstance(val, dict):
                            if key not in master_data[sec_id] or not isinstance(master_data[sec_id][key], dict):
                                master_data[sec_id][key] = {}
                            for k, v in val.items():
                                if v is not None:
                                    master_data[sec_id][key][k] = v
                        else:
                            # Scalar: later non-null wins
                            if str(val).strip().lower() not in ("", "null", "none", "n/a", "na", "—"):
                                master_data[sec_id][key] = val
                            
        return master_data

    def generate_overall_summary(self, page_summaries: list) -> str:
        """Generates a cohesive overall clinical narrative from individual page summaries."""
        if not page_summaries:
            return "No clinical narrative could be generated due to lack of extracted page summaries."
            
        combined = "\n".join([f"Page {i+1} Summary: {s}" for i, s in enumerate(page_summaries)])
        prompt = (
            "You are an expert clinical summarizer. Read the following page-by-page summaries "
            "of a patient's medical case file, and write a cohesive, comprehensive 'Overall Clinical Summary' "
            "in 5-8 sentences. This should read as a single continuous clinical narrative, summarizing the "
            "entire hospital admission, diagnosis, procedures, and outcome without explicitly referencing 'Page X'.\n\n"
            f"{combined}"
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1024
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Overall summary failed: {e}")
            return "Error generating overall clinical summary."
