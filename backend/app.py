"""
app.py — Redactify Flask Backend  (FIXED v3)

Fixes:
  - Download route: correct headers, Content-Disposition, file serving
  - CORS fully configured for Live Server + all origins
  - /api/redact returns redacted_full for client-side save fallback
  - /api/download serves file as binary blob with forced download headers
  - Blurred image path returned in redact response for images
  - Port 5001 to avoid macOS AirPlay conflict on 5000
  - Auto-delete extended to 15 minutes for comfort

Run: python app.py
URL: http://127.0.0.1:5001
"""
import os, uuid, threading, time, traceback
from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS
from werkzeug.utils import secure_filename
from redactor import Redactor
from file_processor import FileProcessor
from security_manager import SecurityManager

# ── App ────────────────────────────────────────────────────────────────────────
app = Flask(__name__)

# Full CORS — allow everything so Live Server (port 5500) can call port 5001
CORS(app,
     resources={r"/*": {"origins": "*"}},
     allow_headers=["Content-Type", "Accept", "Authorization"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     expose_headers=["Content-Disposition", "Content-Type", "Content-Length"])

# ── Folders ────────────────────────────────────────────────────────────────────
BASE     = os.path.dirname(os.path.abspath(__file__))
ROOT     = os.path.dirname(BASE)          # one level above /backend
UPLOADS  = os.path.join(ROOT, "uploads")
REDACTED = os.path.join(ROOT, "redacted")
TEMP     = os.path.join(ROOT, "temp")

# If running app.py directly from the project root, adjust paths
if not os.path.exists(os.path.join(ROOT, "uploads")):
    ROOT     = BASE
    UPLOADS  = os.path.join(BASE, "uploads")
    REDACTED = os.path.join(BASE, "redacted")
    TEMP     = os.path.join(BASE, "temp")

for d in (UPLOADS, REDACTED, TEMP):
    os.makedirs(d, exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024   # 200 MB

ALLOWED = {"txt","pdf","docx","doc","png","jpg","jpeg","bmp","tiff","mp4","avi","mov","mkv"}

# ── Services ───────────────────────────────────────────────────────────────────
redactor  = Redactor()
processor = FileProcessor()
security  = SecurityManager()

# ── Helpers ────────────────────────────────────────────────────────────────────
def allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED

def save_upload(f):
    name = secure_filename(f.filename)
    uid  = uuid.uuid4().hex
    path = os.path.join(UPLOADS, f"{uid}_{name}")
    f.save(path)
    _auto_delete(path, 900)   # 15 minutes
    return path, name

def _auto_delete(path, delay=900):
    def _del():
        time.sleep(delay)
        try:
            if os.path.exists(path):
                os.remove(path)
                print(f"[auto-delete] {os.path.basename(path)}")
        except Exception as e:
            print(f"[auto-delete error] {e}")
    threading.Thread(target=_del, daemon=True).start()

# ── CORS preflight & headers on every response ─────────────────────────────────
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"]   = "*"
    resp.headers["Access-Control-Allow-Headers"]  = "Content-Type, Accept, Authorization"
    resp.headers["Access-Control-Allow-Methods"]  = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition, Content-Type, Content-Length"
    return resp

@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options_handler(_path=""):
    resp = make_response("", 200)
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Accept, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    return jsonify({"status": "ok", "message": "Redactify backend is running on port 5001"})

@app.route("/api/detect", methods=["POST"])
def detect():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename or not allowed(f.filename):
        return jsonify({"error": f"Unsupported file type: {f.filename}"}), 400
    path, name = save_upload(f)
    try:
        text, ftype = processor.extract_text(path)
        entities    = redactor.detect_entities(text)
        return jsonify({
            "filename"    : name,
            "file_type"   : ftype,
            "text_preview": text[:3000],
            "entities"    : entities,
            "entity_count": len(entities),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/redact", methods=["POST"])
def redact():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f      = request.files["file"]
    level  = int(request.form.get("level", 1))
    custom = request.form.get("custom_entities", "")

    if not f.filename or not allowed(f.filename):
        return jsonify({"error": f"Unsupported file type: {f.filename}"}), 400
    if level not in (1, 2, 3):
        return jsonify({"error": "level must be 1, 2, or 3"}), 400

    path, name = save_upload(f)
    ext = name.rsplit(".", 1)[-1].lower()

    try:
        text, ftype = processor.extract_text(path)
        extra = [x.strip() for x in custom.split(",") if x.strip()]
        redacted_text, stats = redactor.redact(text, level=level, extra=extra)

        # Determine output filename and path
        out_name = f"redacted_L{level}_{name}"
        if ftype in ("image", "video"):
            # For image/video, output is always .txt (the redacted OCR text)
            out_name = out_name.rsplit(".", 1)[0] + ".txt"

        out_path = os.path.join(REDACTED, out_name)
        processor.write_output(out_path, redacted_text, ftype)
        _auto_delete(out_path, 900)

        response_data = {
            "original_preview" : text[:5000],
            "redacted_preview" : redacted_text[:5000],
            "redacted_full"    : redacted_text,     # Full text for client-side download
            "download_name"    : out_name,
            "stats"            : stats,
            "level"            : level,
            "file_type"        : ftype,
        }

        # Include blurred image path info if available
        if processor.blurred_image_path and os.path.exists(processor.blurred_image_path):
            blur_basename = os.path.basename(processor.blurred_image_path)
            response_data["blurred_image"] = blur_basename

        return jsonify(response_data)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/download/<path:filename>")
def download(filename):
    """
    Serve a redacted file as a forced browser download.
    Uses make_response with explicit Content-Disposition: attachment
    so the browser opens Save As dialog instead of displaying.
    """
    safe = secure_filename(filename)
    fp   = os.path.join(REDACTED, safe)

    if not os.path.exists(fp):
        # Try uploads folder too (for blurred images)
        fp2 = os.path.join(UPLOADS, safe)
        if os.path.exists(fp2):
            fp = fp2
        else:
            return jsonify({
                "error": (
                    "File not found — it may have been auto-deleted (15 min window). "
                    "Please redact again, or use 'Save as .txt' for instant download."
                )
            }), 404

    try:
        with open(fp, "rb") as fh:
            data = fh.read()
    except Exception as e:
        return jsonify({"error": f"Could not read file: {e}"}), 500

    # Determine content type
    lower = safe.lower()
    if lower.endswith(".pdf"):
        ctype = "application/pdf"
    elif lower.endswith(".docx"):
        ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif lower.endswith(".doc"):
        ctype = "application/msword"
    elif lower.endswith(".png"):
        ctype = "image/png"
    elif lower.endswith((".jpg", ".jpeg")):
        ctype = "image/jpeg"
    else:
        ctype = "text/plain; charset=utf-8"

    resp = make_response(data)
    resp.headers["Content-Type"]        = ctype
    resp.headers["Content-Disposition"] = f'attachment; filename="{safe}"'
    resp.headers["Content-Length"]      = str(len(data))
    resp.headers["Cache-Control"]       = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"]              = "no-cache"
    resp.headers["Expires"]             = "0"
    return resp

@app.route("/api/download-upload/<path:filename>")
def download_upload(filename):
    """Serve a file from the uploads folder (e.g. blurred images)."""
    safe = secure_filename(filename)
    fp   = os.path.join(UPLOADS, safe)
    if not os.path.exists(fp):
        return jsonify({"error": "File not found"}), 404

    with open(fp, "rb") as fh:
        data = fh.read()

    lower = safe.lower()
    ctype = "image/jpeg" if lower.endswith((".jpg",".jpeg")) else "image/png"
    resp  = make_response(data)
    resp.headers["Content-Type"]        = ctype
    resp.headers["Content-Disposition"] = f'attachment; filename="blurred_{safe}"'
    resp.headers["Content-Length"]      = str(len(data))
    return resp

@app.route("/api/live-preview", methods=["POST"])
def live_preview():
    """
    Live text redaction preview — no file upload, just JSON body.
    Used by the live preview textarea in the frontend.
    """
    data  = request.get_json(silent=True) or {}
    text  = data.get("text", "")
    level = int(data.get("level", 1))
    if not text:
        return jsonify({"error": "No text provided"}), 400
    try:
        entities        = redactor.detect_entities(text)
        redacted, stats = redactor.redact(text, level=level)
        return jsonify({
            "original" : text,
            "redacted" : redacted,
            "entities" : entities,
            "stats"    : stats,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/security-status")
def sec_status():
    return jsonify(security.status(UPLOADS, REDACTED, TEMP))

@app.route("/api/cleanup", methods=["POST"])
def cleanup():
    return jsonify(security.cleanup(UPLOADS, REDACTED, TEMP))

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 58)
    print("  REDACTIFY — Smart Document Redaction Tool  (v3)")
    print(f"  Backend  : http://127.0.0.1:5001")
    print(f"  Uploads  : {UPLOADS}")
    print(f"  Redacted : {REDACTED}")
    print("  Frontend : open frontend/index.html with Live Server")
    print("=" * 58 + "\n")
    app.run(debug=True, host="127.0.0.1", port=5001, use_reloader=False)