import logging
from typing import List
from core.schemas import RegionPrediction

logger = logging.getLogger(__name__)

class ReadingOrderEngine:
    """
    Layer 4: Spatial Reading Order Engine.
    Takes unordered YOLO bounding boxes and reconstructs human-readable semantic order.
    Explicitly handles multi-column layouts by detecting spanning headers and vertical columns.
    """
    
    def __init__(self, spanning_threshold: float = 0.6, column_gap_threshold: float = 0.03):
        self.spanning_threshold = spanning_threshold
        self.column_gap_threshold = column_gap_threshold

    def reconstruct(self, regions: List[RegionPrediction], page_width: float, page_height: float) -> List[RegionPrediction]:
        if not regions:
            return []
            
        spanning_elements = []
        regular_elements = []
        
        for r in regions:
            x1, y1, x2, y2 = r.bbox
            width = x2 - x1
            if width >= (page_width * self.spanning_threshold):
                spanning_elements.append(r)
            else:
                regular_elements.append(r)
                
        spanning_elements.sort(key=lambda r: r.bbox[1])
        
        # Slicing the page vertically based on spanning elements (Headers/Footers/Wide Tables)
        band_y_limits = [0.0]
        for s in spanning_elements:
            band_y_limits.append(s.bbox[1])
            band_y_limits.append(s.bbox[3])
        band_y_limits.append(page_height)
        band_y_limits.sort()
        
        bands = []
        for i in range(len(band_y_limits) - 1):
            y_start = band_y_limits[i]
            y_end = band_y_limits[i+1]
            if y_end > y_start:
                bands.append({"y_start": y_start, "y_end": y_end, "regions": [], "spanning": None})
                
        for s in spanning_elements:
            y1, y3 = s.bbox[1], s.bbox[3]
            for b in bands:
                if abs(b["y_start"] - y1) < 1.0 and abs(b["y_end"] - y3) < 1.0:
                    b["spanning"] = s
                    break

        for r in regular_elements:
            y1, y2 = r.bbox[1], r.bbox[3]
            cy = (y1 + y2) / 2.0
            placed = False
            for b in bands:
                if b["y_start"] <= cy <= b["y_end"]:
                    b["regions"].append(r)
                    placed = True
                    break
            if not placed:
                bands[0]["regions"].append(r)
                
        ordered_regions = []
        
        for b in bands:
            if b["spanning"] is not None:
                ordered_regions.append(b["spanning"])
            
            if not b["regions"]:
                continue
                
            band_regions = b["regions"]
            band_regions.sort(key=lambda r: r.bbox[0])
            
            columns = []
            current_col = [band_regions[0]]
            
            # Detect multi-column gaps dynamically
            for i in range(1, len(band_regions)):
                r_prev = current_col[-1]
                r_curr = band_regions[i]
                gap = r_curr.bbox[0] - r_prev.bbox[2]
                
                if gap > (page_width * self.column_gap_threshold):
                    columns.append(current_col)
                    current_col = [r_curr]
                else:
                    current_col.append(r_curr)
                    
            if current_col:
                columns.append(current_col)
                
            for col in columns:
                col.sort(key=lambda r: r.bbox[1])
                ordered_regions.extend(col)
                
        # Final step: Enforce strict reading order sequence mapping
        for index, region in enumerate(ordered_regions):
            region.reading_order = index + 1
                
        return ordered_regions
