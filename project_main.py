import gc
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



def retrieve_relevant_chunks(resume_text, job_description, top_k=100):

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

            Evaluate the candidate's answer against the expected answer points.

            QUESTION:
            {question}

            EXPECTED ANSWER POINTS:
            {json.dumps(expected_points, ensure_ascii=False)}

            CANDIDATE ANSWER:
            {answer}

            Generate only 3–4 lines of plain text feedback. Focus on what was missing or incorrectly explained in the candidate's answer and how it could be improved. Keep the feedback concise, specific, technically accurate, and constructive. Do not generate scores, structured output, headings, or lengthy explanations.
            """

            # Invoke LangChain model
            response = client.invoke(
                prompt
            )
            feedback=(response.content)[0]["text"]
            
            feedback = feedback.strip()
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




import math
from collections import Counter


# ---------------------------------------------------------------------------
# Algorithmic multi-chunk compressor (Extractive & Lexical Salience Scoring)
# ---------------------------------------------------------------------------
_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't",
    "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had", "hadn't",
    "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm",
    "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's", "me", "more",
    "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than", "that",
    "that's", "the", "their", "theirs", "them", "themselves", "then", "there", "there's", "these",
    "they", "they'd", "they'll", "they're", "they've", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which", "while", "who",
    "who's", "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll",
    "you're", "you've", "your", "yours", "yourself", "yourselves"
}

_FILLER_PATTERNS = [
    re.compile(r'\b(?:as\s+mentioned\s+(?:above|earlier|previously|before))\b', re.IGNORECASE),
    re.compile(r'\b(?:it\s+is\s+(?:important|worth\s+noting|evident|clear)\s+that)\b', re.IGNORECASE),
    re.compile(r'\b(?:it\s+should\s+be\s+(?:noted|remembered|pointed\s+out)\s+that)\b', re.IGNORECASE),
    re.compile(r'\b(?:in\s+order\s+to)\b', re.IGNORECASE),
    re.compile(r'\b(?:for\s+the\s+purpose\s+of)\b', re.IGNORECASE),
    re.compile(r'\b(?:with\s+respect\s+to|in\s+terms\s+of)\b', re.IGNORECASE),
    re.compile(r'\b(?:as\s+a\s+matter\s+of\s+fact|needless\s+to\s+say)\b', re.IGNORECASE),
    re.compile(r'\b(?:as\s+we\s+can\s+see|as\s+can\s+be\s+seen)\b', re.IGNORECASE),
    re.compile(r'\b(?:due\s+to\s+the\s+fact\s+that)\b', re.IGNORECASE),
    re.compile(r'\b(?:basically|essentially|literally)\b', re.IGNORECASE),
]


def _clean_filler_phrases(text: str) -> str:
    """Strip rhetorical filler phrases and normalize spacing."""
    res = text
    for pat in _FILLER_PATTERNS:
        res = pat.sub("", res)
    return re.sub(r'\s+', ' ', res).strip()


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences while respecting common boundaries and bullet lines."""
    raw = re.split(r'(?<=[.!?])\s+|\n+|(?:^|\s)[•\-\*]\s+', text)
    sentences = []
    for s in raw:
        s = s.strip(' \t\r\n•-*')
        if len(s) > 10:
            sentences.append(s)
    return sentences


def compress_text(text: str, target_ratio: float = 0.6) -> str:
    """
    Algorithmic compression of a single text chunk:
    - Prunes filler phrases and noise.
    - Scores sentences by information density, technical terms, keywords, and metrics.
    - Selects top salient sentences to achieve meaningful token reduction (~35-50%)
      while maintaining high semantic fidelity and readability.
    """
    if not isinstance(text, str) or not text.strip():
        return ""

    cleaned_text = _clean_filler_phrases(text.strip())
    sentences = _split_into_sentences(cleaned_text)

    # For 1 sentence, prune filler words / parentheticals
    if len(sentences) <= 1:
        res = re.sub(r'\s*\([^)]*\)', '', cleaned_text)
        return re.sub(r'\s+', ' ', res).strip() if res else cleaned_text

    # Extract content words for salience scoring
    words = re.findall(r'\b[a-zA-Z0-9_\-\+\#\.]+\b', cleaned_text.lower())
    content_words = [w for w in words if w not in _STOPWORDS and len(w) > 1]

    if not content_words:
        return " ".join(sentences[:1])

    word_freq = Counter(content_words)
    max_freq = max(word_freq.values()) if word_freq else 1

    scored = []
    for idx, sent in enumerate(sentences):
        sent_words = re.findall(r'\b[a-zA-Z0-9_\-\+\#\.]+\b', sent.lower())
        if not sent_words:
            scored.append((0.0, idx, sent))
            continue

        raw_score = sum(word_freq.get(w, 0) / max_freq for w in sent_words if w not in _STOPWORDS)
        norm_score = raw_score / (math.sqrt(len(sent_words)) if len(sent_words) > 0 else 1.0)

        # Technical/numeric bonuses: technical metrics, versions, numbers, acronyms
        if re.search(r'\d+', sent):
            norm_score *= 1.2
        if re.search(r'\b[A-Z]{2,}\b', sent):
            norm_score *= 1.15
        if idx == 0:
            norm_score *= 1.2

        scored.append((norm_score, idx, sent))

    # Keep top sentences according to target_ratio
    target_count = max(1, min(len(sentences) - 1, round(len(sentences) * target_ratio)))
    top_items = sorted(
        sorted(scored, key=lambda x: x[0], reverse=True)[:target_count],
        key=lambda x: x[1]  # Preserve chronological/narrative order
    )

    compressed = " ".join(s[2] for s in top_items)
    return compressed.strip() if compressed else cleaned_text


async def compress_text_batch(texts: list[str], batch_size: int = 10) -> list[str]:
    """
    Algorithmic multi-chunk compressor:
    Compresses chunks locally in parallel/fast synchronous execution.
    Requires no external LLM API calls, avoids rate limits, and guarantees fast compression.
    """
    if not texts:
        return []

    return [compress_text(t) if isinstance(t, str) else "" for t in texts]




async def main(pdf_path: str, job_description: str | None = None):

    # 1. Extract resume text
    path = extract_text_from_pdf(pdf_path)

    with open(path, encoding="utf-8") as f:
        resume_text = f.read()

    # 2. Parse resume
    resume_sections = parse_resume(resume_text)

    # 3. Retrieve relevant chunks
    chunks = retrieve_relevant_chunks(
        resume_sections,
        job_description,
        top_k=100
    )

    if not chunks:
        raise ValueError("No relevant resume chunks found.")

    # 4. Extract original texts
    originals = [
        chunk["chunk_text"] for chunk in chunks
    ]

    # 5. Compress all chunks using algorithmic compressor
    compressed_summaries = await compress_text_batch(
        originals,
        batch_size=8
    )

    # 6. Prepare compression report
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

    # 7. Generate compression report
    compression_report = build_report(
        compressed_pairs,
        embeddings
    )

    # 8. Generate interview questions
    parsed_output = await run_interview_prep_agent(
        resume_sections,
        job_description,
        compressed_pairs
    )

    # 9. Generate interview ID
    interview_id = str(uuid.uuid4())

    candidate_name = resume_sections.get(
        "Name", "Unknown Candidate"
    )

    # 10. Store questions in MySQL
    inserted_count = send_to_db(
        question_bank=parsed_output,
        interview_id=interview_id,
        candidate_name=candidate_name,
    )

    return {
        "interview_id": interview_id,
        "total_questions": inserted_count,
        "compression_report": compression_report
    }
