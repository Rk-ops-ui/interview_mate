from fastapi import FastAPI,File,UploadFile,status,HTTPException,Form
import os,shutil
import uuid
from project_main import get_next_question,save_candidate_response,speech_to_text,main,evaluate_candidate_response,clear_database
from fastapi.middleware.cors import CORSMiddleware
import json
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
app = FastAPI(title='Ai based interview agent')

import tempfile
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","https://lgjwfg86-5173.inc1.devtunnels.ms"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploaded_pdfs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class GenerateRequest(BaseModel):
    resume_sections: dict
    job_description: str
    summaries: list
    
    
# Frontend build directory
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIST = BASE_DIR / "careercoach-frontend" / "dist"

# Serve static assets
app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIST / "assets"),
    name="assets"
)

# Serve React frontend
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    requested_file = FRONTEND_DIST / full_path

    if requested_file.is_file():
        return FileResponse(requested_file)

    return FileResponse(FRONTEND_DIST / "index.html")



@app.get("/")
def get_health():
    return {'status':'healthy'}


@app.post("/upload-resume/")
async def upload(
    file: UploadFile = File(...),
    job_description: str = Form(...)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed."
        )

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    cleaned_jd = job_description.strip() or None

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not save file: {str(e)}"
        )

    finally:
        await file.close()

    try:
        result=await main(file_path,cleaned_jd)
    
        
            
        return {
            "success": True,
            "result":result,
            "job_description": cleaned_jd
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Resume processing failed: {str(e)}"
        )

    finally:
        await file.close()
    
    
@app.get("/interview/{interview_id}/next-question")
def next_question(interview_id: str):


    try:
        result = get_next_question(interview_id)

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
        
AUDIO_DIR = "uploaded_audio"
os.makedirs(AUDIO_DIR, exist_ok=True)


@app.post("/interview/{interview_id}/submit-audio")
async def submit_audio(
    interview_id: str,
    question_id: int = Form(...),
    audio: UploadFile = File(...)
):

    audio_path = os.path.join(
        AUDIO_DIR,
        f"{uuid.uuid4().hex}_{audio.filename}"
    )

    try:
        with open(audio_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)

        answer = speech_to_text(audio_path)

        if not answer.strip():
            raise HTTPException(
                status_code=400,
                detail="No speech detected."
            )

        result = save_candidate_response(
            interview_id=interview_id,
            question_id=question_id,
            answer=answer
        )

        return {
            "question_id": question_id,
            "transcribed_answer": answer,
            "saved": result["success"]
        }

    finally:
        await audio.close()

        if os.path.exists(audio_path):
            os.remove(audio_path)
            
            
@app.get("/evaluate/interview/{interview_id}")
async def evaluate_candidate(interview_id:str):
    try:
        evals=evaluate_candidate_response(interview_id)
        out=clear_database(interview_id)
        return evals
    
    except Exception as e:
        raise HTTPException(
                    status_code=500,
                    detail=str(e)
                )
                
        
        
            



            

