
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from pydantic import BaseModel, Field
from pypdf import PdfReader


# --------------------------------------------------
# 1. Configuration
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
RESUME_PATH = BASE_DIR / "my_resume.pdf"

# Load .env from the project root
load_dotenv(BASE_DIR.parent / ".env")

MODEL = "openai/gpt-oss-120b"

client = None
resume_data = None
resume_error = None


# --------------------------------------------------
# 2. Resume data models
# --------------------------------------------------

class Experience(BaseModel):
    company: str | None = None
    role: str | None = None
    duration: str | None = None
    description: str | None = None
    skills_used: list[str] = Field(default_factory=list)


class Resume(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None

    total_experience_years: float | None = None

    skills: list[str] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    question: str


# --------------------------------------------------
# 3. Extract text from PDF
# --------------------------------------------------

def read_pdf(file_path: Path) -> str:
    if not file_path.exists():
        raise FileNotFoundError(
            f"Resume PDF not found: {file_path}"
        )

    reader = PdfReader(str(file_path))
    pages = []

    for page in reader.pages:
        text = page.extract_text()

        if text:
            pages.append(text)

    resume_text = "\n".join(pages).strip()

    if not resume_text:
        raise ValueError(
            "No readable text found in the PDF. "
            "The file may be scanned or image-based."
        )

    return resume_text


# --------------------------------------------------
# 4. Parse resume using Groq
# --------------------------------------------------

def parse_resume(resume_text: str) -> Resume:
    schema = Resume.model_json_schema()

    system_prompt = f"""
You are an expert resume parser.

Extract information from the supplied resume and return
ONLY valid JSON matching this schema:

{json.dumps(schema)}

Rules:
1. Never invent information.
2. Use null for missing single values.
3. Use empty lists for missing list values.
4. Include internships in experiences when relevant.
5. Extract skills from the entire resume.
6. Keep project descriptions concise and accurate.
7. Return valid JSON without Markdown fences.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": (
                    "Parse this resume:\n\n" + resume_text
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    raw_output = response.choices[0].message.content

    if not raw_output:
        raise ValueError("The AI returned an empty response.")

    data = json.loads(raw_output)

    return Resume.model_validate(data)


# --------------------------------------------------
# 5. Ask questions using resume information only
# --------------------------------------------------

def ask_candidate(question: str, resume: Resume) -> str:
    system_prompt = f"""
You are HireMeAI, an assistant representing a job candidate
during HR interviews.

Candidate resume data:
{resume.model_dump_json(indent=2)}

Rules:
1. Answer only using the supplied resume data.
2. Never invent skills, projects, qualifications, or experience.
3. If information is unavailable, say:
   "I don't have enough information to answer that."
4. Answer professionally in clear, simple English.
5. Answer the actual question directly.
6. Do not claim to be the candidate; assist the person
   asking about the candidate.
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": question,
            },
        ],
        temperature=0.2,
    )

    answer = response.choices[0].message.content

    if not answer:
        raise ValueError("The AI returned an empty answer.")

    return answer


# --------------------------------------------------
# 6. Load resume once when the application starts
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global client, resume_data, resume_error

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        resume_error = "GROQ_API_KEY is missing from .env."
        print(f"Startup warning: {resume_error}")
    else:
        client = Groq(api_key=api_key)

        try:
            resume_text = read_pdf(RESUME_PATH)
            resume_data = parse_resume(resume_text)
            resume_error = None

            print("Resume loaded and parsed successfully.")

        except Exception as exc:
            resume_data = None
            resume_error = str(exc)
            print(f"Resume loading error: {resume_error}")

    yield

    # Release references when the application shuts down
    client = None
    resume_data = None


# --------------------------------------------------
# 7. Create FastAPI application
# --------------------------------------------------

app = FastAPI(
    title="HireMeAI",
    description="AI assistant that answers questions from a resume.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5000",
        "http://localhost:5000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# --------------------------------------------------
# 8. Home endpoint
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "HireMeAI backend is running",
        "docs": "/docs",
    }


# --------------------------------------------------
# 9. Health endpoint
# --------------------------------------------------

@app.get("/health")
def health():
    return {
        "status": "running",
        "resume_loaded": resume_data is not None,
        "ready": (
            client is not None
            and resume_data is not None
        ),
    }


# --------------------------------------------------
# 10. Resume information endpoint
# --------------------------------------------------

@app.get("/resume")
def get_resume():
    if resume_data is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Resume is not available. "
                "Check the PDF file and GROQ_API_KEY."
            ),
        )

    return resume_data.model_dump()


# --------------------------------------------------
# 11. Chat endpoint
# --------------------------------------------------

@app.post("/chat")
def chat(request: ChatRequest):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    if len(question) > 2000:
        raise HTTPException(
            status_code=400,
            detail="Question must be 2000 characters or fewer.",
        )

    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Groq is not configured. Check GROQ_API_KEY.",
        )

    if resume_data is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Resume could not be loaded. "
                "Check backend/my_resume.pdf and server logs."
            ),
        )

    try:
        answer = ask_candidate(question, resume_data)

        return {
            "question": question,
            "answer": answer,
        }

    except Exception as exc:
        print(f"Chat error: {exc}")

        raise HTTPException(
            status_code=502,
            detail="Unable to generate an answer. Please try again.",
        ) from exc
