import pymupdf
import re
import json
import os
import uuid
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage
from pinecone import Pinecone
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
import mysql.connector
from mysql.connector import Error
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from faster_whisper import WhisperModel
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import json
from pathlib import Path
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from pinecone import EmbedQuery
from compression_report import build_report

INDEX_NAME="interview-mate"

# Initialize once, not on every request
whisper_model = WhisperModel(
    "small.en",
    device="cpu",
    compute_type="int8"
)
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True}
)


class InterviewQuestion(BaseModel):
    question_id: str
    question: str
    category: str
    difficulty: Literal["Easy", "Medium", "Hard"]
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    resume_relevance: str
    expected_answer_points: List[str] = Field(
        description="Important points expected in a good candidate answer"
    )


class InterviewQuestionBank(BaseModel):
    questions: List[InterviewQuestion]
    

class AnswerRequest(BaseModel):
    question_id: int
    answer: str = Field(min_length=1)

load_dotenv()

api_key=os.getenv("GEMINI_API_KEY")
api_key_eval=os.getenv("GEMINI_API_KEY_EVAL")
pinecone_api_key=os.getenv("PINECONE_API_KEY")
pc = Pinecone(api_key=pinecone_api_key)
index=pc.Index(INDEX_NAME)
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",

    api_key=api_key,
    temperature=0
)

client = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash",

    api_key=api_key_eval,
    temperature=0
)

def send_to_db(question_bank: dict, interview_id: str, candidate_name: str) -> int:
    """Insert generated interview questions into MySQL."""
    
    # required_vars = [
    #     "MYSQL_HOST",
    #     "MYSQL_USER",
    #     "MYSQL_PASSWORD",
    #     "MYSQL_DATABASE"
    # ]

    # missing = [name for name in required_vars if not os.getenv(name)]

    # if missing:
    #     raise RuntimeError(
    #         "Missing MySQL configuration: " + ", ".join(missing)
    #     )

    questions = question_bank.get("questions")

    if not isinstance(questions, list) or not questions:
        raise ValueError("No valid questions list found.")

    connection = None

    try:
        connection = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            database=os.getenv("MYSQL_DATABASE")
        )

        cursor = connection.cursor()

        insert_query = """
            INSERT INTO interview_questions (
                interview_id,
                candidate_name,
                question_text,
                category,
                source_type,
                resume_relevance,
                expected_answer_points,
                question_order
                
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """

        rows = []

        for index, item in enumerate(questions, start=1):

            if not isinstance(item, dict) or not item.get("question"):
                continue

            expected_points = item.get("expected_answer_points", [])

            if not isinstance(expected_points, list):
                expected_points = [str(expected_points)]

            rows.append((
                interview_id,
                candidate_name,
                item["question"],
                item.get("category"),
                item.get("source_type"),
                item.get("resume_relevance"),
                json.dumps(expected_points, ensure_ascii=False),
                index,
                
            ))

        if not rows:
            raise ValueError("No valid question records found.")

        cursor.executemany(insert_query, rows)
        connection.commit()

        return cursor.rowcount

    except Error as e:
        if connection and connection.is_connected():
            connection.rollback()

        raise RuntimeError(f"MySQL insertion failed: {e}") from e

    finally:
        if connection and connection.is_connected():
            cursor.close()
            connection.close()
            
            
            
            
def get_next_question(interview_id: str):

    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=os.getenv("MYSQL_PORT")
    )

    cursor = connection.cursor(dictionary=True)

    try:
        # Fetch the first question that has not been answered
        cursor.execute("""
            SELECT id, question_text, category, difficulty, status
            FROM interview_questions
            WHERE interview_id = %s
              AND status IN ('pending')
            ORDER BY question_order ASC
            LIMIT 1
        """, (interview_id,))

        question = cursor.fetchone()
        

        if not question:
            return {
                "completed": True,
                "message": "All interview questions completed."
            }
        # Mark it as asked
        if question["status"] == "pending":
            cursor.execute("""
                UPDATE interview_questions
                SET status = 'asked'
                WHERE id = %s
            """, (question["id"],))

            connection.commit()       
            return {
            "question_id": question["id"],
            "question": question["question_text"],
            
        }   
            
    finally:
        cursor.close()
        connection.close()


# Check your index

def do_chunking():

    folder = Path(r"E:\interview_mate\train_data")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100
    )

    all_chunks = []

    # 1. Extract text and create chunks
    for document in folder.iterdir():

        if document.suffix.lower() != ".pdf":
            continue

        reader = PdfReader(str(document))

        full_text = "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )

        if not full_text.strip():
            continue

        doc = Document(
            page_content=full_text,
            metadata={"source": document.name}
        )

        all_chunks.extend(
            splitter.split_documents([doc])
        )

    if not all_chunks:
        print("No chunks found")
        return

    # 2. Generate embeddings
    vectors = embeddings.embed_documents(
        [chunk.page_content for chunk in all_chunks]
    )

    print("Embedding type:", type(vectors[0]))
    print("Embedding dimensions:", len(vectors[0]))

    # 3. Prepare documents
    documents = [
        {
            "_id": f"chunk-{i}",
            "chunk_text": chunk.page_content,
            "source": chunk.metadata["source"]
        }
        for i, chunk in enumerate(all_chunks)
    ]

    # 4. Upload documents
    index = pc.Index(INDEX_NAME)

    response = index.documents.batch_upsert(
        namespace="interview",
        documents=documents
    )

    print("Upload response:", response)
    print("Total chunks submitted:", len(documents))



    

def extract_text_from_pdf(pdf_path):
    doc = pymupdf.open(pdf_path) # open a document
    path="output.txt"
    out = open(path, "wb") # create a text output
    for page in doc: # iterate the document pages
        text = page.get_text().encode("utf8") 
        out.write(text) 
        out.write(bytes((12,))) 
    out.close()
    doc.close()
    return path


def normalize_heading(line):
        # Ignore surrounding whitespace, case, and common punctuation
        return re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()

     
        
def clear_database(interview_id: str):

    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=int(os.getenv("MYSQL_PORT", "3306"))
    )

    cursor = connection.cursor()

    try:
        cursor.execute("""
            DELETE FROM interview_questions
            WHERE interview_id = %s
        """, (interview_id,))

        deleted_count = cursor.rowcount

        connection.commit()

        return {
            "success": True,
            "message": "Successfully cleared interview records.",
            "interview_id": interview_id,
            "deleted_records": deleted_count
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()
         
        
            

    
    



def parse_resume(text):
    names = re.findall(
        r"\b[A-Z][a-z]+\s+\b[A-Z][a-z]+",
        text,
        re.IGNORECASE
    )
    name = names[0]

    heading_aliases = {
        "Professional Summary": [
            "professional summary", "summary", "profile",
            "career objective", "objective", "about me"
        ],
        "Education": [
            "education", "academic background",
            "educational qualifications"
        ],
        "Technical Skills": [
            "technical skills", "skills", "core competencies",
            "technical expertise"
        ],
        "Experience": [
            "experience", "work experience",
            "professional experience", "internship", "internships"
        ],
        "Projects": [
            "projects", "academic projects", "personal projects"
        ],
        "Certifications": [
            "certifications", "certificates",
            "licenses and certifications"
        ],
        "Extra-Curricular Activities": [
            "extra-curricular activities", "extracurricular activities",
            "positions of responsibility", "leadership", "activities"
        ]
    }

    heading_lookup = {}

    for canonical, aliases in heading_aliases.items():
        for alias in aliases:
            heading_lookup[normalize_heading(alias)] = canonical

    sections = {}
    current_section = None

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        normalized = normalize_heading(line)

        if normalized in heading_lookup:
            current_section = heading_lookup[normalized]
            sections.setdefault(current_section, [])
            continue

        if current_section is not None:
            sections[current_section].append(line)

    sections = {
        heading: " ".join(lines)
        for heading, lines in sections.items()
    }

    sections = {"Name": name, **sections}

    return sections



def retrieve_relevant_chunks(resume_text, job_description, top_k=20):

    index = pc.Index(INDEX_NAME)

    search_query = f"""
    Candidate Resume:
    {resume_text}

    Job Description:
    {job_description}

    Retrieve technical knowledge relevant to the
    candidate's skills, projects, experience and
    job responsibilities.
    """

    response = index.documents.search(
        namespace="interview",
        top_k=top_k,
        score_by=[
            EmbedQuery(
                field="chunk_text",
                query=search_query
            )
        ],
        include_fields=["chunk_text", "source"]
    )

    chunks = []

    for doc in response.matches:
        data = doc.to_dict()

        chunks.append({
            "chunk_text": data.get("chunk_text"),
            "source": data.get("source"),
            "score": data.get("_score")
        })
        


    return chunks

async def run_interview_prep_agent(sections: dict,job_description:str,summarized_context=None):
    """Generate the interview question bank and return it at once."""

    resume_json = json.dumps(
        sections,
        indent=4,
        ensure_ascii=False
    )
    context = ""
    print("Summarized context type:", type(summarized_context))
    if summarized_context:
        context = "\n".join([
            f"""
            Source: {item.get('source', '')}
            Summary: {item.get('summary', '')}
            """
            for item in summarized_context
        ])
    

    
    agent = create_agent(
        model=llm,
        response_format=ToolStrategy(InterviewQuestionBank),
        
        system_prompt = """
        You are an autonomous technical and professional interview question-generation agent.

Your task is to generate a comprehensive technical interview question bank based on the candidate's resume, job description, and retrieved technical knowledge.

## CORE INSTRUCTION — VECTOR DATABASE KNOWLEDGE BANK

The retrieved vector database knowledge bank MUST be the PRIMARY technical knowledge source for generating interview questions and expected answer points.

- Use the retrieved chunks extensively to formulate relevant technical questions.
- Analyze the complete supplied retrieved context.
- Connect related concepts to generate deeper conceptual and practical questions.
- Ground expected answer points in the retrieved technical knowledge.
- Use the resume and JD to determine which knowledge-bank topics are relevant.
- Do not treat retrieved knowledge as proof of the candidate's experience.
- Do not generate irrelevant questions or fabricate information absent from the retrieved context.

The JD determines WHAT should be tested, the resume provides candidate-specific context, and the vector database provides the technical foundation.

## MANDATORY EXECUTION ORDER

### STEP 1: ANALYZE THE JOB DESCRIPTION

Identify:

- Job role and responsibilities.
- Required technical and functional skills.
- Required qualifications and experience.
- Tools, technologies, frameworks and platforms.
- Practical competencies expected from the candidate.

The job description MUST be the PRIMARY basis for interview question relevance.

Generate questions covering important job requirements even when those skills are absent from the candidate's resume.

### STEP 2: ANALYZE THE CANDIDATE'S RESUME

Identify:

- Technical and functional skills.
- Programming languages and tools.
- Projects and internships.
- Work experience.
- Academic achievements.
- Technologies and frameworks used.

Use the resume to generate personalized questions about the candidate's actual experience, projects and claimed skills.

Do not restrict the interview to skills already mentioned in the candidate's resume.

Never invent candidate experience or achievements.

### STEP 3: ANALYZE RETRIEVED TECHNICAL KNOWLEDGE

Use the retrieved vector database knowledge to:

- Identify technical concepts relevant to the JD and resume.
- Generate conceptual, practical and scenario-based questions.
- Improve technical accuracy and depth.
- Prepare meaningful expected answer points grounded in retrieved content.
- Connect related concepts to generate deeper interview questions.

Prioritize relevant retrieved knowledge when generating technical questions. Do not rely primarily on general pretrained knowledge when the required information is available in the knowledge bank.

### STEP 4: CATEGORIZE QUESTIONS

Choose categories dynamically according to the actual job description and candidate's background.

Possible categories include:

1. Programming and Technical Fundamentals
2. Data Structures and Algorithms
3. Databases and SQL
4. Machine Learning and Deep Learning
5. Natural Language Processing and Generative AI
6. Software Engineering and System Design
7. Tools, Frameworks and Technologies
8. Resume and Project-Based Questions
9. Practical Implementation and Scenarios
10. Behavioral and Situational Questions
11. Domain-Specific Knowledge

These categories are examples, not mandatory categories.

Do not generate irrelevant categories for a particular job role.

### STEP 5: QUESTION GENERATION

Every question must contain:

- id
- question
- category
- difficulty
- source_type
- resume_relevance
- expected_answer_points

**DIFFICULTY:**

Use exactly one of:

- Easy
- Medium
- Hard

**SOURCE TYPE:**

Clearly distinguish between:

- AI-generated question based on job description
- AI-generated question based on resume
- AI-generated question based on both resume and job description
- AI-generated question based on retrieved technical knowledge

**QUESTION GENERATION RULES:**

1. Prioritize job description requirements.
2. Use the resume for candidate-specific questions.
3. Use retrieved knowledge extensively to construct technical questions.
4. Include important job requirements missing from the resume.
5. Include practical, conceptual, technical, scenario-based and experience-based questions as relevant to the role.
6. Avoid repetitive and irrelevant questions.
7. Do not invent candidate experience.
8. Generate exacly 2 questions
9. Provide meaningful expected answer points for every question.
12. Ensure questions are relevant to the target job role.

### STEP 6: QUESTION QUALITY

Ensure the generated question bank:

- Covers important technical requirements of the JD.
- Makes extensive use of relevant retrieved knowledge.
- Tests theoretical and practical understanding.
- Evaluates the candidate's actual projects and experience.
- Includes questions about technologies claimed in the resume.
- Tests important missing skills required by the JD.
- Progresses from foundational to advanced concepts.
- Avoids duplicate questions with different wording.
- Includes meaningful expected answer points grounded in retrieved knowledge.

Do not confuse retrieved technical knowledge with the candidate's actual skills.

## FINAL OUTPUT FORMAT — MANDATORY

Return ONLY one valid JSON object matching the InterviewQuestionBank schema.

Do not include Markdown fences, headings, explanations or additional text.

Use this structure:

{
  "questions": [
    {
      "id": "Q001",
      "question": "Question text",
      "category": "Relevant category",
      "difficulty": "Easy",
      "source_type": "AI-generated question based on retrieved technical knowledge",
      "resume_relevance": "Explanation of relevance to the candidate",
      "expected_answer_points": [
        "Point 1",
        "Point 2"
      ]
    }
  ]
}

Ensure every question contains all required fields with valid JSON types.

Follow the actual InterviewQuestionBank schema if its field definitions impose additional validation requirements.

## FINAL PRIORITY

JOB DESCRIPTION ANALYSIS
→ RESUME ANALYSIS
→ RETRIEVED VECTOR DATABASE KNOWLEDGE
→ QUESTION GENERATION
→ STRUCTURED JSON OUTPUT
        """
    )

    
    user_prompt = f"""
    CANDIDATE RESUME JSON:

    {resume_json}

    JOB DESCRIPTION:

    {job_description}

    RETRIEVED TECHNICAL KNOWLEDGE FROM VECTOR DATABASE:

    {context}

    Analyze the candidate's resume, job description,
    and retrieved technical knowledge.

    Generate a comprehensive, personalized and categorized
    technical interview question bank.

    Requirements:

    1. Prioritize the job description.
    2. Personalize questions using the candidate's resume.
    3. Use retrieved knowledge to improve technical depth.
    4. Include questions about projects, internships and
    claimed technical skills.
    5. Include important JD requirements even if absent
    from the resume.
    6. Generate meaningful expected answer points.
    7. Avoid duplicate and irrelevant questions.
    8. Dynamically select relevant categories.
    9. Do not invent candidate experience.
    10. Return the complete question bank using ONLY
        the exact JSON structure required by the system prompt.
    """
        
        
        # Invoke runs the agent to completion and returns the final state.
    result = await agent.ainvoke({
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        })
    
    question_bank = result["structured_response"]   
        

        # Return a standard Python dictionary
    return question_bank.model_dump()

    
def speech_to_text(audio_path: str):

    segments, info = whisper_model.transcribe(
        audio_path,
        beam_size=5
    )

    transcription = " ".join(
        segment.text.strip()
        for segment in segments
    )

    return transcription



def save_candidate_response(
    interview_id: str,
    question_id: int,
    answer: str
):
    answer = answer.strip()

    if not answer:
        raise ValueError("Candidate answer cannot be empty.")

    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=int(os.getenv("MYSQL_PORT", "3306"))
    )

    cursor = connection.cursor()

    try:
        cursor.execute("""
            UPDATE interview_questions
            SET candidate_response = %s,
                status = 'answered',
                answered_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND interview_id = %s
              AND status = 'asked'
              AND candidate_response IS NULL
        """, (answer, question_id, interview_id))

        if cursor.rowcount == 0:
            raise ValueError(
                "Question not found, already answered, "
                "or not currently active."
            )

        connection.commit()

        return {
            "success": True,
            "message": "Candidate response saved successfully.",
            "question_id": question_id
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()



def evaluate_candidate_response(interview_id: str):

    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=int(os.getenv("MYSQL_PORT", "3306"))
    )

    cursor = connection.cursor(dictionary=True)

    try:
        # Fetch all answered questions for this interview
        cursor.execute("""
            SELECT
                id,
                question_text,
                expected_answer_points,
                candidate_response
            FROM interview_questions
            WHERE interview_id = %s
              AND status = 'answered'
              AND candidate_response IS NOT NULL
            ORDER BY question_order ASC
        """, (interview_id,))

        results = cursor.fetchall()

        if not results:
            raise ValueError("No candidate answers found.")

        evaluations = []

        # Evaluate each answer
        for result in results:

            question = result["question_text"]
            expected_points = result["expected_answer_points"]
            answer = result["candidate_response"]

            if isinstance(expected_points, str):
                expected_points = json.loads(expected_points)

            prompt = f"""
You are an expert technical interview evaluator.

Evaluate the candidate's answer against the expected
answer points.

QUESTION:
{question}

EXPECTED ANSWER POINTS:
{json.dumps(expected_points, ensure_ascii=False)}

CANDIDATE ANSWER:
{answer}

Identify:
1. Concepts correctly covered.
2. Important concepts that are missing.
3. Technically incorrect statements.
4. What the candidate should improve.
5. Relevant concepts to study further.

Be fair and constructive.
Evaluate conceptual understanding, not exact wording.
Do not invent missing requirements.

Return clear, detailed plain-text feedback.
Do not return JSON or a numerical score.
"""

            # Invoke LangChain model
            response = llm.invoke(prompt)

            feedback = response.content.strip()

            evaluations.append({
                "question_id": result["id"],
                "question": question,
                "candidate_answer": answer,
                "feedback": feedback
            })

        # Return complete interview evaluation
        return {
            "interview_id": interview_id,
            "total_evaluated": len(evaluations),
            "evaluations": evaluations
        }

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


from transformers import pipeline

compressor = pipeline(
    "summarization",
    model="facebook/bart-large-cnn"
)

def compress_text_batch(texts, max_length=120, batch_size=8):

    results = compressor(
        texts,
        max_length=max_length,
        min_length=30,
        do_sample=False,
        truncation=True,
        batch_size=batch_size
    )

    return [result["summary_text"] for result in results]
        
        
async def main(pdf_path:str , job_description:str|None= None):
    

    path = extract_text_from_pdf(pdf_path)

    with open(path, encoding="utf-8") as f:
        resume_text = f.read()

    resume_sections = parse_resume(resume_text)
    chunks = retrieve_relevant_chunks(
                        resume_sections,
                        job_description,
                        top_k=20
                    )
    
    
    
    compressed_summaries = []

    # Extract original texts
    originals = [chunk["chunk_text"] for chunk in chunks]

    # Batch compression
    batch_size = 8
    compressed_summaries = []

    import torch

    for start in range(0, len(originals), batch_size):

        batch = originals[start:start + batch_size]

        with torch.inference_mode():
            results = compressor(
                batch,
                max_length=100,
                min_length=30,
                do_sample=False,
                truncation=True,
                batch_size=len(batch)
            )

        compressed_summaries.extend(
            result["summary_text"] for result in results
        )


        # Prepare pairs for compression report
        compressed_pairs = []

        for i, (chunk, original, summary) in enumerate(
            zip(chunks, originals, compressed_summaries)
        ):
            compressed_pairs.append({
                "chunk_id": i,
                "source": chunk["source"],
                "original": original,
                "summary": summary
            })


        # Generate compression report
        compression_report = build_report(
            compressed_pairs,
            embeddings
        )
        
        
    parsed_output = await run_interview_prep_agent(resume_sections,job_description,compressed_pairs)

    # Parse the agent's final JSON response before inserting it into MySQL.
    

    interview_id = str(uuid.uuid4())
    candidate_name = resume_sections.get("Name", "Unknown Candidate")
    

    inserted_count = send_to_db(
        question_bank=parsed_output,
        interview_id=interview_id,
        candidate_name=candidate_name,
    )

    
    return {"interview_id":interview_id,"total_questions":inserted_count,"compression_report":compression_report}
    
    
        

    
    
        
        
    
    


