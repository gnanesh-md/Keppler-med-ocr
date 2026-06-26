from PIL import Image, ImageDraw

class VisualGrounder:
    """
    Handles drawing visual grounding overlays directly onto source document images.
    """
    
    @staticmethod
    def draw_highlight(image: Image.Image, bbox: list, label: str = "") -> Image.Image:
        """
        Overlays a translucent bounding box onto the image for visual verification.
        
        Args:
            image: Original PIL Image.
            bbox: [x1, y1, x2, y2]
            label: Optional text label to place above the box.
            
        Returns:
            A new PIL Image with the grounding box drawn.
        """
        if not bbox or len(bbox) != 4:
            return image
            
        # Convert base image to RGBA for alpha compositing
        base_img = image.convert("RGBA")
        
        # Create a transparent overlay
        overlay = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        
        x1, y1, x2, y2 = bbox
        
        # Styling: Translucent amber/red fill with a strong red border
        fill_color = (243, 156, 18, 60)     # Translucent amber
        outline_color = (231, 76, 60, 255)  # Solid bright red
        
        # Draw the rectangle
        draw.rectangle([x1, y1, x2, y2], fill=fill_color, outline=outline_color, width=5)
        
        # If a label is provided, try drawing it slightly above the box
        if label:
            # We don't rely on complex fonts here to avoid system font path issues,
            # but default font is usually visible enough.
            text_x = x1
            text_y = max(0, y1 - 20)
            
            # Simple text backdrop
            draw.rectangle([text_x, text_y, text_x + len(label)*7, text_y + 15], fill=outline_color)
            draw.text((text_x + 2, text_y), label, fill=(255, 255, 255, 255))
            
        # Alpha composite the overlay onto the original image
        final_img = Image.alpha_composite(base_img, overlay)
        
        # Return as RGB for standard Streamlit rendering
        return final_img.convert("RGB")
