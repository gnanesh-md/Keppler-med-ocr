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
            "Keys:\n"
            '- "diagnoses": list of strings (e.g. primary, secondary diagnoses)\n'
            '- "medications": list of strings (drug name, dose, frequency)\n'
            '- "allergies": list of strings\n'
            '- "procedures": list of strings (surgery, procedures, dates)\n'
            '- "lab_results": list of strings (test name, result, units)\n'
            '- "admissions": list of strings (dates, vitals, scores, patient info)\n'
            '- "recommendations": list of strings (discharge instructions, education, nursing plans)\n'
            '- "timeline_events": list of objects [{"date": "YYYY-MM-DD", "event": "description"}] (normalize all found dates)\n\n'
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
                "procedures": [], "lab_results": [], "admissions": [], "recommendations": [], "timeline_events": []
            }

    def process_chunks(self, chunker, progress_callback=None) -> dict:
        """
        Iterates sequentially over all chunks. Utilizes local caching if available.
        Merges results into a master structured dictionary.
        """
        chunks = chunker.get_chunks()
        total = len(chunks)
        
        master_data = {
            "diagnoses": [], "medications": [], "allergies": [], 
            "procedures": [], "lab_results": [], "admissions": [], "recommendations": [], "timeline_events": []
        }
        
        for i, chunk_text in enumerate(chunks):
            # Attempt to load from cache first
            data = chunker.load_cached_chunk(i)
            
            if not data:
                # Cache miss, process via LLM
                data = self._extract_chunk_data(chunk_text)
                chunker.save_chunk_cache(i, data)
                
            # Merge into master (exact match deduplication)
            for key in master_data.keys():
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        # Avoid pure duplicates
                        if item not in master_data[key]:
                            master_data[key].append(item)
                            
            # Update UI state
            if progress_callback:
                progress_callback(i + 1, total)
                
        return master_data
