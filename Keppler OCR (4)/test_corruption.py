import asyncio
from openai import AsyncOpenAI

async def main():
    raw_text = """Rx
- Tab. Letoval 2.5 mg
  O ----- O  (10)
- Cap. Fefol
  --- 0 ---  (30)
- Tab. ASA 75 mg
  --- 0 ---  (30)
- Tab. Bleyf
  --- 0 ---  (30)
(010) 24th Jan
2 vi
- Tab. Evadiol 2 mg
  O ----- O
yo2000y (24th Jan)
(10) - Tab. Dydrosum"""

    print("Testing Blueprint Formatter...")
    client = AsyncOpenAI(base_url="http://localhost:8700/v1", api_key="EMPTY", timeout=30.0)
    system_prompt = """You are an advanced Universal OCR engine capable of extracting text from ANY image. Your job is to perform complete, highly accurate, and exhaustive transcription of the entire document from top to bottom.

Your objective: Extract EVERY piece of text from the image with 100% fidelity.

Output Format:
Organize the extracted text into a clean, professional Markdown format. Use Markdown Headers (###) for sections, **bold text** for keys/labels, bullet points (-) for lists, and Markdown Tables (|---|) for any tabular or grid-like data.

Rules for 100% Accuracy:
1. MANDATORY: Extract EVERY single line of text from the image without exception. Do not truncate, omit, or summarize the content. Scan the entire image carefully and transcribe all items, values, and notes from top to bottom.
2. EXHAUSTIVE TRANSCRIPTION: Do not stop generating until the very last word of the image is transcribed.
3. FORMATTING: Use Markdown (bolding, lists, tables) to give the text a professional structure.
4. KEY-VALUE PAIRS: If you see a label and a value (e.g., Name: John), format it as **Name:** John.
5. NO PREAMBLE: Start directly with the extracted data. No greetings or meta-commentary.
6. MISSING DATA: If any field is missing from the document, leave it completely blank. Do NOT write 'Not documented', 'N/A', or 'None'."""

    user_prompt = f"Here is the raw extracted text from the page:\n\n{raw_text}\n\nPlease format it strictly according to the structure specified in your instructions. Do not hallucinate data that is not present in the raw text."

    try:
        resp = await client.chat.completions.create(
            model="qwen2.5-vl-7b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0
        )
        print("Blueprint Output:")
        print(resp.choices[0].message.content)
    except Exception as e:
        print(f"API Error: {e}")

asyncio.run(main())
