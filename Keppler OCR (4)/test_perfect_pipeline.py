import asyncio
from PIL import Image
import numpy as np
import logging
import sys

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

from modules.precision_ocr import process_single_page, BLUEPRINTS

def create_dummy_image():
    # Create a simple white image
    img = np.ones((1000, 1000, 3), dtype=np.uint8) * 255
    return Image.fromarray(img)

def test_pipeline():
    print("Creating dummy image...")
    img = create_dummy_image()
    
    print("Running process_single_page...")
    # Use Universal OCR blueprint
    result = process_single_page(
        raw_img=img,
        label="Test Page",
        idx=0,
        total_pages=1,
        client="Universal OCR (Any Text)",
        progress_cb=lambda p: print(f"Progress: {p*100:.0f}%")
    )
    
    print("\n--- Result ---")
    print("Label:", result["label"])
    print("Text:", result["text"])
    print("Predictions count:", len(result["predictions"]))
    
if __name__ == "__main__":
    test_pipeline()
