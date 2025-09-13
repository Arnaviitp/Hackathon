import os
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from docx import Document
import pdfplumber
import google.generativeai as genai
import json

# =======================
# Configure Google Gemini
# =======================
API_KEY = os.getenv("give your api key")  # Make sure to set this in your environment
if not API_KEY:
    raise RuntimeError("❌ GOOGLE_API_KEY not set in environment variables")
genai.configure(api_key=API_KEY)

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all for dev, restrict in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store last uploaded text for Q&A
last_uploaded_text = ""


# =======================
# Helper Functions
# =======================
def extract_text_from_pdf(file_path: str) -> str:
    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


def extract_text_from_docx(file_path: str) -> str:
    doc = Document(file_path)
    return " ".join([p.text.strip() for p in doc.paragraphs if p.text.strip()])


def extract_from_gemini_response(response) -> str:
    """Extract text from Gemini response robustly."""
    try:
        # Direct text attribute
        if hasattr(response, "text") and response.text:
            return response.text.strip()

        # Fallback: JSON parsing
        resp_json = json.loads(response.to_json())
        if "candidates" in resp_json:
            for cand in resp_json["candidates"]:
                if "content" in cand and "parts" in cand["content"]:
                    for part in cand["content"]["parts"]:
                        if "text" in part:
                            return part["text"].strip()

        return "⚠️ No usable text found in Gemini response."
    except Exception as e:
        return f"⚠️ Error parsing Gemini response: {str(e)}"


# =======================
# Routes
# =======================
@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    global last_uploaded_text
    file_path = f"temp_{file.filename}"
    try:
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        # Extract text
        if file.filename.lower().endswith(".pdf"):
            text = extract_text_from_pdf(file_path)
        elif file.filename.lower().endswith(".docx"):
            text = extract_text_from_docx(file_path)
        else:
            return {"summary": "❌ Unsupported format. Upload PDF or DOCX."}

        if not text:
            return {"summary": "❌ No text found in document."}

        last_uploaded_text = text  # Save for Q&A

        # Summarize with Gemini (trim to 4000 chars to stay under limit)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(
            f"Summarize this legal document in simple, clear language:\n\n{text[:4000]}"
        )

        summary_text = extract_from_gemini_response(response)
        return {"summary": summary_text}

    except Exception as e:
        return {"summary": f"❌ Error: {str(e)}"}

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.post("/ask")
async def ask_question(request: Request):
    global last_uploaded_text
    try:
        data = await request.json()
        question = data.get("question", "").strip()

        if not question:
            return {"answer": "❌ Please provide a valid question."}

        context = last_uploaded_text or "No document uploaded. Answer generally."

        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(
            f"Based on this legal document:\n\n{context[:4000]}\n\nQuestion: {question}\nAnswer clearly:"
        )

        answer_text = extract_from_gemini_response(response)
        return {"answer": answer_text}

    except Exception as e:
        return {"answer": f"❌ Error: {str(e)}"}

