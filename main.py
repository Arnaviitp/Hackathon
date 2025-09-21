from pydantic import BaseModel
from dotenv import load_dotenv
import os
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from docx import Document
import pdfplumber
import google.generativeai as genai

load_dotenv()  # Load .env

# =======================
# Configure Google Gemini
# =======================
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    raise RuntimeError("❌ GOOGLE_API_KEY not set in environment variables")

genai.configure(api_key=API_KEY)

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "✅ FastAPI with Gemini is running!"}

# Store last uploaded text
last_uploaded_text = ""


# =======================
# Helpers
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


def safe_extract(response) -> str:
    """Safely extract Gemini response text."""
    try:
        if hasattr(response, "text") and response.text:
            return response.text.strip()
        return str(response)
    except Exception as e:
        return f"⚠️ Failed to parse Gemini response: {e}"


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

        if file.filename.lower().endswith(".pdf"):
            text = extract_text_from_pdf(file_path)
        elif file.filename.lower().endswith(".docx"):
            text = extract_text_from_docx(file_path)
        else:
            return {"summary": "❌ Only PDF or DOCX allowed."}

        if not text:
            return {"summary": "❌ No text found in document."}

        last_uploaded_text = text

        # Summarize
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(
            f"Summarize this legal document in clear, simple language:\n\n{text[:4000]}"
        )

        return {"summary": safe_extract(response)}

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


class Question(BaseModel):
    question: str


@app.post("/ask")
async def ask_question(payload: Question):
    global last_uploaded_text
    question = payload.question.strip()

    if not question:
        return {"answer": "❌ Please provide a valid question."}

    context = last_uploaded_text or "No document uploaded."

    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(
        f"Document:\n{context[:4000]}\n\nQuestion: {question}\nAnswer clearly:"
    )

    return {"answer": safe_extract(response)}


# =======================
# Deployment Entry Point
# =======================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))



