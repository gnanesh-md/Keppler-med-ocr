from services.summarizer.timeline import TimelineBuilder

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
        
        md += "## 1. PATIENT IDENTIFICATION & ADMISSIONS\n"
        if not master_data.get("admissions"):
            md += "- No admission data extracted.\n"
        for item in master_data.get("admissions", []):
            md += f"- {item}\n"
            
        md += "\n## 2. DIAGNOSES\n"
        if not master_data.get("diagnoses"):
            md += "- No diagnoses extracted.\n"
        for item in master_data.get("diagnoses", []):
            md += f"- {item}\n"
            
        md += "\n## 3. PROCEDURES\n"
        if not master_data.get("procedures"):
            md += "- No procedures extracted.\n"
        for item in master_data.get("procedures", []):
            md += f"- {item}\n"
            
        md += "\n## 4. MEDICATIONS\n"
        if not master_data.get("medications"):
            md += "- No medications extracted.\n"
        for item in master_data.get("medications", []):
            md += f"- {item}\n"
            
        md += "\n## 5. ALLERGIES\n"
        if not master_data.get("allergies"):
            md += "- No allergies extracted.\n"
        for item in master_data.get("allergies", []):
            md += f"- {item}\n"
            
        md += "\n## 6. LAB RESULTS\n"
        if not master_data.get("lab_results"):
            md += "- No lab results extracted.\n"
        for item in master_data.get("lab_results", []):
            md += f"- {item}\n"
            
        md += "\n## 7. CLINICAL RECOMMENDATIONS & NURSING NOTES\n"
        if not master_data.get("recommendations"):
            md += "- No recommendations extracted.\n"
        for item in master_data.get("recommendations", []):
            md += f"- {item}\n"
            
        md += "\n## 8. CHRONOLOGICAL CLINICAL TIMELINE\n"
        md += TimelineBuilder.build_chronological_timeline(master_data)
            
        return md
