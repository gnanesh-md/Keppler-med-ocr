from modules.summarizer.timeline import TimelineBuilder

class MasterAggregator:
    """
    Stage 4 of Map-Reduce Pipeline.
    Takes the deeply consolidated clinical JSON schema and deterministically formats it 
    into the Master Clinical Summary Markdown report. This bypasses LLM context limits entirely
    during the final generation phase, ensuring zero data truncation.
    """
    
    @staticmethod
    def build_markdown_report(master_data: dict) -> str:
        md = ""
        section_idx = 1
        
        def _is_valid(text: str) -> bool:
            if not isinstance(text, str):
                return True
            t = text.lower().strip()
            invalid_phrases = ["not documented", "none", "n/a", "no data extracted", "not mentioned"]
            for phrase in invalid_phrases:
                if phrase in t and len(t) < 30: # If it's a short string saying "Not documented"
                    return False
            if t in ["none", "n/a", "-", ""]:
                return False
            return True

        overall = master_data.get("overall_summary", "")
        if overall:
            md += f"## {section_idx}. OVERALL CLINICAL SUMMARY\n"
            md += f"{overall}\n\n"
            section_idx += 1

        admissions = [i for i in master_data.get("admissions", []) if _is_valid(i)]
        if admissions:
            md += f"## {section_idx}. PATIENT IDENTIFICATION & ADMISSIONS\n"
            for item in admissions:
                md += f"- {item}\n"
            section_idx += 1
            
        diagnoses = [i for i in master_data.get("diagnoses", []) if _is_valid(i)]
        if diagnoses:
            md += f"\n## {section_idx}. DIAGNOSES\n"
            for item in diagnoses:
                md += f"- {item}\n"
            section_idx += 1
            
        procedures = [i for i in master_data.get("procedures", []) if _is_valid(i)]
        if procedures:
            md += f"\n## {section_idx}. PROCEDURES\n"
            for item in procedures:
                md += f"- {item}\n"
            section_idx += 1
            
        medications = [i for i in master_data.get("medications", []) if _is_valid(i)]
        if medications:
            md += f"\n## {section_idx}. MEDICATIONS\n"
            for item in medications:
                md += f"- {item}\n"
            section_idx += 1
            
        allergies = [i for i in master_data.get("allergies", []) if _is_valid(i)]
        if allergies:
            md += f"\n## {section_idx}. ALLERGIES\n"
            for item in allergies:
                md += f"- {item}\n"
            section_idx += 1
            
        lab_results = [i for i in master_data.get("lab_results", []) if _is_valid(i)]
        if lab_results:
            md += f"\n## {section_idx}. LAB RESULTS\n"
            for item in lab_results:
                md += f"- {item}\n"
            section_idx += 1
            
        recommendations = [i for i in master_data.get("recommendations", []) if _is_valid(i)]
        if recommendations:
            md += f"\n## {section_idx}. CLINICAL RECOMMENDATIONS & NURSING NOTES\n"
            for item in recommendations:
                md += f"- {item}\n"
            section_idx += 1
            
        timeline = TimelineBuilder.build_chronological_timeline(master_data)
        if timeline and "No timeline events extracted." not in timeline:
            md += f"\n## {section_idx}. CHRONOLOGICAL CLINICAL TIMELINE\n"
            md += timeline
            
        return md.strip()
