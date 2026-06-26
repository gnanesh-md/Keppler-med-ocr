import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

class ImageEnhancementService:
    """
    Layer 2: Enhances document images prior to Layout Detection and OCR.
    Handles contrast normalization, denoising, resizing, and deskewing.
    """
    
    @staticmethod
    def optimize_for_ocr(image_path: str, max_dimension: int = 2048) -> np.ndarray:
        """Runs the complete enhancement pipeline on an image."""
        img = cv2.imread(image_path)
        if img is None:
            logger.error(f"Image read failure: {image_path}")
            raise ValueError(f"Could not read image: {image_path}")
            
        img = ImageEnhancementService.resize_oversized(img, max_dimension)
        img = ImageEnhancementService.deskew(img)
        img = ImageEnhancementService.normalize_contrast_and_denoise(img)
        
        return img

    @staticmethod
    def resize_oversized(img: np.ndarray, max_dim: int) -> np.ndarray:
        """Downscales insanely massive images to prevent GPU RAM exhaustion."""
        h, w = img.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            logger.info(f"Resizing image from {w}x{h} to {new_w}x{new_h}")
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        return img

    @staticmethod
    def normalize_contrast_and_denoise(img: np.ndarray) -> np.ndarray:
        """Applies CLAHE and Non-Local Means Denoising to sharpen text."""
        # Convert to LAB color space to safely enhance luminance without distorting colors
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) to L-channel
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        cl = clahe.apply(l)
        
        # Merge back
        limg = cv2.merge((cl,a,b))
        enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        
        # Fast Denoise
        denoised = cv2.fastNlMeansDenoisingColored(enhanced, None, 10, 10, 7, 21)
        return denoised

    @staticmethod
    def deskew(img: np.ndarray) -> np.ndarray:
        """Detects text orientation and auto-rotates the document."""
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, 100, minLineLength=100, maxLineGap=10)
        
        if lines is not None:
            angles = []
            for line in lines:
                x1, y1, x2, y2 = line[0]
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                angles.append(angle)
            
            if angles:
                median_angle = np.median(angles)
                # Only correct if skew is noticeable but not a completely 90-deg rotated image (which requires different handling)
                if 0.5 < abs(median_angle) < 15:
                    logger.info(f"Deskewing image by {median_angle:.2f} degrees")
                    (h, w) = img.shape[:2]
                    center = (w // 2, h // 2)
                    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
                    img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return img
