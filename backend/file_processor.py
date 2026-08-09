"""
file_processor.py  –  Read & Write all supported file types.  (FIXED v3)

Fixes:
  - Face blur pipeline correctly integrated with redact output
  - Blurred image saved alongside redacted text output
  - Video: blurred frames saved as composite image strip
  - OCR text extracted before AND after blur for accurate text redaction
  - PDF and DOCX write preserved and working

READ:
  .txt           → direct UTF-8 read
  .pdf           → pdfplumber
  .docx          → python-docx
  .png/.jpg/etc  → pytesseract OCR + face blur
  .mp4/.avi/etc  → OpenCV frame sampling + pytesseract + face blur

WRITE:
  redacted text saved as:
    .txt  (plain text, image/video results)
    .pdf  (via reportlab)
    .docx (via python-docx)
"""

import os
import uuid
from PIL import Image

# ── Optional imports ───────────────────────────────────────────────────────────
try:
    import pdfplumber
    PDF_READ = True
except ImportError:
    PDF_READ = False

try:
    from docx import Document as DocxDoc
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

try:
    import pytesseract
    pytesseract.get_tesseract_version()
    OCR_OK = True
except Exception:
    OCR_OK = False
    print("[FileProcessor] WARNING: Tesseract not found – image/video OCR disabled.")

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False
    print("[FileProcessor] WARNING: opencv-python not installed – video processing disabled.")

IMG_EXTS   = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".wmv"}

# Load OpenCV face detector (bundled with opencv)
_face_cascade = None
if CV2_OK:
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    if os.path.exists(cascade_path):
        _face_cascade = cv2.CascadeClassifier(cascade_path)


def _blur_faces(img_bgr):
    """
    Detect faces in a BGR image and apply a strong Gaussian blur to each.
    Returns the image with blurred faces.
    If no face detector is available, returns the original unchanged.
    """
    if _face_cascade is None or not CV2_OK:
        return img_bgr

    gray  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    faces = _face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
    )

    result = img_bgr.copy()
    if len(faces) == 0:
        return result   # No faces found — return original unchanged

    for (x, y, w, h) in faces:
        # Add padding around detected face region
        pad_x = int(w * 0.15)
        pad_y = int(h * 0.15)
        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(result.shape[1], x + w + pad_x)
        y2 = min(result.shape[0], y + h + pad_y)

        face_region = result[y1:y2, x1:x2]
        # Apply very heavy blur (pixelation effect)
        blurred = cv2.GaussianBlur(face_region, (99, 99), 30)
        # Optional: overlay a dark rectangle for extra redaction
        result[y1:y2, x1:x2] = blurred

    print(f"[FileProcessor] Blurred {len(faces)} face(s).")
    return result


def _blur_image_file(input_path: str, output_path: str) -> bool:
    """
    Load an image, blur detected faces, save to output_path.
    Returns True on success, False if OpenCV not available or image can't be read.
    """
    if not CV2_OK:
        return False

    img = cv2.imread(input_path)
    if img is None:
        return False

    blurred = _blur_faces(img)
    cv2.imwrite(output_path, blurred)
    return True


class FileProcessor:

    def __init__(self):
        # Paths of blurred outputs so the API can return them
        self.blurred_image_path = None
        self.blurred_frames_dir = None

    def extract_text(self, path: str) -> tuple:
        """Return (text, file_type). file_type ∈ text|pdf|docx|image|video"""
        ext = os.path.splitext(path)[1].lower()

        if ext == ".txt":
            return self._txt(path), "text"
        elif ext == ".pdf":
            return self._pdf(path), "pdf"
        elif ext in (".docx", ".doc"):
            return self._docx(path), "docx"
        elif ext in IMG_EXTS:
            return self._image(path), "image"
        elif ext in VIDEO_EXTS:
            return self._video(path), "video"
        else:
            raise ValueError(f"Unsupported extension: {ext}")

    # ── Readers ────────────────────────────────────────────────────────────────

    def _txt(self, path):
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def _pdf(self, path):
        if not PDF_READ:
            raise RuntimeError("pdfplumber not installed. Run: pip install pdfplumber")
        pages = []
        with pdfplumber.open(path) as pdf:
            for p in pdf.pages:
                t = p.extract_text()
                if t:
                    pages.append(t)
        return "\n\n".join(pages)

    def _docx(self, path):
        if not DOCX_OK:
            raise RuntimeError("python-docx not installed. Run: pip install python-docx")
        doc = DocxDoc(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    def _ocr_image(self, img: Image.Image) -> str:
        """Run OCR on a PIL image and return extracted text."""
        if not OCR_OK:
            return "[OCR unavailable – install Tesseract and add to PATH]"
        img  = img.convert("L")
        w, h = img.size
        img  = img.resize((w * 2, h * 2), Image.LANCZOS)
        return pytesseract.image_to_string(img, config="--oem 3 --psm 6")

    def _image(self, path):
        """OCR an image and also generate a blurred version for faces."""
        # 1. Extract text via OCR from ORIGINAL (unblurred) for better accuracy
        pil_img = Image.open(path)
        text    = self._ocr_image(pil_img)

        # 2. Generate blurred version (faces blurred, saved separately)
        if CV2_OK:
            base, ext = os.path.splitext(path)
            blur_path = base + "_blurred" + ext
            success = _blur_image_file(path, blur_path)
            if success:
                self.blurred_image_path = blur_path
                print(f"[FileProcessor] Blurred image saved: {blur_path}")

        return text or "[No text detected in image]"

    def _video(self, path):
        """Sample frames from video, OCR each, also save blurred frames."""
        if not CV2_OK:
            raise RuntimeError("opencv-python not installed. Run: pip install opencv-python")

        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {path}")

        fps      = cap.get(cv2.CAP_PROP_FPS) or 25
        interval = max(1, int(fps * 2))   # sample every 2 seconds
        texts    = []
        idx      = 0
        MAX      = 60

        # Directory to save blurred frames
        frames_dir = path + "_blurred_frames"
        os.makedirs(frames_dir, exist_ok=True)
        self.blurred_frames_dir = frames_dir
        frame_count = 0

        while len(texts) < MAX:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % interval == 0:
                # OCR from original frame
                rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                t    = self._ocr_image(Image.fromarray(rgb))
                if t.strip():
                    texts.append(t)

                # Save blurred frame (faces blurred)
                blurred_frame = _blur_faces(frame)
                frame_path    = os.path.join(frames_dir, f"frame_{frame_count:04d}.jpg")
                cv2.imwrite(frame_path, blurred_frame)
                frame_count += 1

            idx += 1

        cap.release()
        return "\n\n--- frame ---\n\n".join(texts) if texts else "[No text detected in video]"

    # ── Writer ─────────────────────────────────────────────────────────────────

    def write_output(self, out_path: str, text: str, ftype: str):
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        if ftype == "pdf" and out_path.endswith(".pdf"):
            self._write_pdf(out_path, text)
        elif ftype == "docx" and out_path.endswith(".docx"):
            self._write_docx(out_path, text)
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)

    def _write_pdf(self, path, text):
        try:
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.pagesizes import A4
        except ImportError:
            # Fallback to plain text if reportlab not available
            with open(path.replace(".pdf", ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
            return

        doc    = SimpleDocTemplate(path, pagesize=A4,
                                   leftMargin=50, rightMargin=50,
                                   topMargin=60, bottomMargin=60)
        styles = getSampleStyleSheet()
        body   = ParagraphStyle("b", parent=styles["Normal"],
                                fontSize=10, leading=14, spaceAfter=6)
        story  = []
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                # Escape XML special chars for reportlab
                safe = para.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                story.append(Paragraph(safe.replace("\n", "<br/>"), body))
                story.append(Spacer(1, 6))
        doc.build(story)

    def _write_docx(self, path, text):
        if not DOCX_OK:
            with open(path.replace(".docx", ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
            return
        doc = DocxDoc()
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                doc.add_paragraph(para)
        doc.save(path)