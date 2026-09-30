"""
OCR Engine for Expo Design AI (Phase 5).

Dedicated OCR — does NOT use the LLM as the primary OCR engine.
Supports multiple OCR backends:
- PaddleOCR (preferred, local)
- Tesseract (fallback)
- Vision model (last resort, for complex layouts)

OCR output preserves: text, confidence, bounding boxes, page number, coordinates.
"""
import os
import base64
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


@dataclass
class OCRResult:
    """A single OCR result."""
    text: str
    confidence: float
    bounding_box: Dict[str, float] = field(default_factory=dict)  # {x, y, w, h}
    page: Optional[int] = None
    source_doc: str = ""
    source_version: str = ""


@dataclass
class OCRPageResult:
    """OCR results for a single page."""
    page_number: int
    results: List[OCRResult] = field(default_factory=list)
    full_text: str = ""
    average_confidence: float = 0.0


class OCREngine:
    """
    OCR engine with multiple backends.
    Priority: PaddleOCR → Tesseract → Vision model
    """

    def __init__(self):
        self._paddle_available = False
        self._tesseract_available = False
        self._vision_available = False
        self._paddle_ocr = None
        self._check_backends()

    def _check_backends(self):
        """Check which OCR backends are available."""
        # Check PaddleOCR
        try:
            import paddleocr  # noqa: F401
            self._paddle_available = True
            logger.info("PaddleOCR available")
        except ImportError:
            logger.info("PaddleOCR not available")

        # Check Tesseract
        try:
            import pytesseract  # noqa: F401
            self._tesseract_available = True
            logger.info("Tesseract available")
        except ImportError:
            logger.info("Tesseract not available")

        # Check vision model (always available via Ollama)
        self._vision_available = True
        logger.info("Vision model OCR available (via Ollama)")

    def is_available(self) -> bool:
        """Check if any OCR backend is available."""
        return self._paddle_available or self._tesseract_available or self._vision_available

    def get_backend(self) -> str:
        """Get the best available backend name."""
        if self._paddle_available:
            return "paddleocr"
        elif self._tesseract_available:
            return "tesseract"
        elif self._vision_available:
            return "vision"
        return "none"

    def recognize(self, image_path: str, page: int = None,
                  source_doc: str = "", source_version: str = "") -> OCRPageResult:
        """
        Recognize text in an image.
        Returns OCRPageResult with text, confidence, and bounding boxes.
        """
        if self._paddle_available:
            return self._recognize_paddle(image_path, page, source_doc, source_version)
        elif self._tesseract_available:
            return self._recognize_tesseract(image_path, page, source_doc, source_version)
        elif self._vision_available:
            return self._recognize_vision(image_path, page, source_doc, source_version)
        else:
            logger.error("No OCR backend available")
            return OCRPageResult(page_number=page or 0)

    def _recognize_paddle(self, image_path: str, page: int,
                          source_doc: str, source_version: str) -> OCRPageResult:
        """Recognize using PaddleOCR."""
        try:
            if self._paddle_ocr is None:
                from paddleocr import PaddleOCR
                self._paddle_ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)

            result = self._paddle_ocr.ocr(image_path, cls=True)
            results = []
            texts = []

            if result and result[0]:
                for line in result[0]:
                    if line:
                        bbox = line[0]
                        text = line[1][0]
                        conf = line[1][1]
                        # Convert bbox to {x, y, w, h}
                        xs = [p[0] for p in bbox]
                        ys = [p[1] for p in bbox]
                        bounding_box = {
                            "x": min(xs),
                            "y": min(ys),
                            "w": max(xs) - min(xs),
                            "h": max(ys) - min(ys),
                        }
                        results.append(OCRResult(
                            text=text,
                            confidence=conf,
                            bounding_box=bounding_box,
                            page=page,
                            source_doc=source_doc,
                            source_version=source_version,
                        ))
                        texts.append(text)

            avg_conf = sum(r.confidence for r in results) / len(results) if results else 0.0
            return OCRPageResult(
                page_number=page or 0,
                results=results,
                full_text="\n".join(texts),
                average_confidence=avg_conf,
            )

        except Exception as e:
            logger.warning("PaddleOCR failed: {}, falling back", e)
            return self._recognize_tesseract(image_path, page, source_doc, source_version)

    def _recognize_tesseract(self, image_path: str, page: int,
                             source_doc: str, source_version: str) -> OCRPageResult:
        """Recognize using Tesseract."""
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

            results = []
            texts = []
            n_boxes = len(data['text'])
            for i in range(n_boxes):
                text = data['text'][i].strip()
                conf = int(data['conf'][i])
                if text and conf > 30:  # Filter low confidence
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    results.append(OCRResult(
                        text=text,
                        confidence=conf / 100.0,
                        bounding_box={"x": x, "y": y, "w": w, "h": h},
                        page=page,
                        source_doc=source_doc,
                        source_version=source_version,
                    ))
                    texts.append(text)

            avg_conf = sum(r.confidence for r in results) / len(results) if results else 0.0
            return OCRPageResult(
                page_number=page or 0,
                results=results,
                full_text="\n".join(texts),
                average_confidence=avg_conf,
            )

        except Exception as e:
            logger.warning("Tesseract failed: {}, falling back to vision", e)
            return self._recognize_vision(image_path, page, source_doc, source_version)

    def _recognize_vision(self, image_path: str, page: int,
                          source_doc: str, source_version: str) -> OCRPageResult:
        """Recognize using vision model (last resort)."""
        try:
            import vision
            text = vision.describe_image(image_path, instruction=(
                "Transcribe ALL text visible in this image exactly as shown. "
                "Preserve numbers, units, and symbols. "
                "If any character is unclear, write [illegible]. "
                "Return ONLY the transcribed text, nothing else."
            ))
            return OCRPageResult(
                page_number=page or 0,
                results=[OCRResult(
                    text=text or "",
                    confidence=0.7,  # Vision model confidence is estimated
                    page=page,
                    source_doc=source_doc,
                    source_version=source_version,
                )],
                full_text=text or "",
                average_confidence=0.7,
            )
        except Exception as e:
            logger.error("Vision OCR failed: {}", e)
            return OCRPageResult(page_number=page or 0)

    def recognize_batch(self, image_paths: List[str], source_doc: str = "",
                        source_version: str = "") -> List[OCRPageResult]:
        """Recognize text in multiple images."""
        results = []
        for i, path in enumerate(image_paths):
            result = self.recognize(path, page=i + 1, source_doc=source_doc,
                                    source_version=source_version)
            results.append(result)
        return results


# Singleton instance
_ocr_engine = OCREngine()


def get_ocr_engine() -> OCREngine:
    """Get the global OCR engine instance."""
    return _ocr_engine
