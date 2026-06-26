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
        prompt = (
            "You are a clinical data extraction engine. Analyze the following chunk of medical "
            "records and extract all relevant data into a strict JSON structure.\n"
            "Return ONLY a JSON object with the following keys. If a field has no data, return an empty list [].\n"
            "Do NOT include phrases like 'Not documented', 'N/A', 'None', or 'Not mentioned'. Only extract real data.\n"
            "Keys:\n"
            '- "diagnoses": list of strings (e.g. primary, secondary diagnoses)\n'
            '- "medications": list of strings (drug name, dose, frequency)\n'
            '- "allergies": list of strings\n'
            '- "procedures": list of strings (surgery, procedures, dates)\n'
            '- "lab_results": list of strings (test name, result, units)\n'
            '- "admissions": list of strings (dates, vitals, scores, patient info)\n'
            '- "recommendations": list of strings (discharge instructions, education, nursing plans)\n'
            '- "timeline_events": list of objects [{"date": "YYYY-MM-DD", "event": "description"}] (normalize all found dates)\n'
            '- "page_summary": string (a concise 1-2 sentence narrative summary of this chunk)\n\n'
            f"TEXT CHUNK:\n{chunk_text}\n\n"
            "IMPORTANT: Output ONLY valid JSON."
        )
        
        try:
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2048
            )
            raw = resp.choices[0].message.content.strip()
            
            # Clean markdown formatting if present
            if raw.startswith("```json"): raw = raw[7:]
            if raw.startswith("```"): raw = raw[3:]
            if raw.endswith("```"): raw = raw[:-3]
            
            data = json.loads(raw.strip())
            return data
        except Exception as e:
            logger.error(f"Chunk extraction failed: {e}")
            # Return empty skeleton to prevent pipeline crash
            return {
                "diagnoses": [], "medications": [], "allergies": [], 
                "procedures": [], "lab_results": [], "admissions": [], "recommendations": [], "timeline_events": [], "page_summary": ""
            }

    def process_chunks(self, chunker, progress_callback=None) -> dict:
        """
        Processes chunks concurrently. Utilizes local caching if available.
        Merges results into a master structured dictionary.
        """
        import concurrent.futures
        from streamlit.runtime.scriptrunner import add_script_run_ctx

        chunks = chunker.get_chunks()
        total = len(chunks)
        
        master_data = {
            "diagnoses": [], "medications": [], "allergies": [], 
            "procedures": [], "lab_results": [], "admissions": [], "recommendations": [], "timeline_events": [], "page_summaries": []
        }
        
        def _process_single_chunk(i, chunk_text):
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
                future = executor.submit(_process_single_chunk, i, chunk_text)
                add_script_run_ctx(future)
                futures[future] = i
                
            for future in concurrent.futures.as_completed(futures):
                idx, data = future.result()
                results[idx] = data
                completed += 1
                if progress_callback:
                    progress_callback(completed, total)
                    
        # Merge sequentially to preserve page_summaries order
        for data in results:
            if not data:
                continue
            for key in master_data.keys():
                if key == "page_summaries":
                    if "page_summary" in data and isinstance(data["page_summary"], str) and data["page_summary"].strip():
                        master_data["page_summaries"].append(data["page_summary"].strip())
                elif key in data and isinstance(data[key], list):
                    for item in data[key]:
                        # Avoid pure duplicates
                        if item not in master_data[key]:
                            master_data[key].append(item)
                            
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
