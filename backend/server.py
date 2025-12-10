from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
from jose import JWTError, jwt
import PyPDF2
import pytesseract
from pdf2image import convert_from_bytes
import re
import io

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'votre-cle-secrete-tres-securisee-changez-moi-en-production')
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 10080

security = HTTPBearer()

app = FastAPI()
api_router = APIRouter(prefix="/api")

# Models
class UserRegister(BaseModel):
    email: EmailStr
    password: str
    nom: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    nom: str
    created_at: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: User

class Document(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    filename: str
    upload_date: str
    status: str
    total_lines: int = 0

class AccountingLine(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str
    account_number: str
    label: str
    debit: float
    credit: float
    total: float
    line_number: int

class JustificationDetail(BaseModel):
    label: str
    debit: float
    credit: float

class Justification(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    line_id: str
    details: List[JustificationDetail]
    total_debit: float
    total_credit: float
    is_validated: bool
    created_at: str

class JustificationCreate(BaseModel):
    details: List[JustificationDetail]

# Auth Functions
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")
        
        return User(**user)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# PDF Processing Functions
def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF using PyPDF2"""
    try:
        pdf_file = io.BytesIO(pdf_bytes)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        logging.error(f"Error extracting text from PDF: {e}")
        return ""

def extract_text_with_ocr(pdf_bytes: bytes) -> str:
    """Extract text using OCR for scanned PDFs"""
    try:
        images = convert_from_bytes(pdf_bytes)
        text = ""
        for image in images:
            text += pytesseract.image_to_string(image, lang='fra') + "\n"
        return text
    except Exception as e:
        logging.error(f"Error with OCR: {e}")
        return ""

def parse_accounting_lines(text: str) -> List[dict]:
    """Parse accounting lines from extracted text"""
    lines = []
    line_number = 0
    
    # Pattern pour détecter les lignes comptables
    # Format attendu: N° compte (jusqu'à 15 chiffres), Intitulé, Débit ou Crédit
    pattern = r'([0-9]{1,15})\s+([^\d\n]+?)\s+(\d+[.,]\d+)\s*(\d+[.,]\d+)?'
    
    for match in re.finditer(pattern, text):
        line_number += 1
        account_number = match.group(1)
        label = match.group(2).strip()
        
        # Débit et crédit
        amount1 = float(match.group(3).replace(',', '.').replace(' ', ''))
        amount2 = float(match.group(4).replace(',', '.').replace(' ', '')) if match.group(4) else 0.0
        
        # Déterminer si c'est débit ou crédit
        if amount2 > 0:
            debit = amount1
            credit = amount2
        else:
            # Si un seul montant, on suppose que c'est un débit
            debit = amount1
            credit = 0.0
        
        total = debit if debit > 0 else credit
        
        lines.append({
            "account_number": account_number,
            "label": label,
            "debit": debit,
            "credit": credit,
            "total": total,
            "line_number": line_number
        })
    
    return lines

# Auth Routes
@api_router.post("/auth/register", response_model=Token)
async def register(user_data: UserRegister):
    # Check if user exists
    existing_user = await db.users.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email déjà enregistré")
    
    # Create user
    user_dict = {
        "id": str(uuid.uuid4()),
        "email": user_data.email,
        "password_hash": hash_password(user_data.password),
        "nom": user_data.nom,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.users.insert_one(user_dict)
    
    # Create token
    access_token = create_access_token({"sub": user_dict["id"]})
    
    user = User(
        id=user_dict["id"],
        email=user_dict["email"],
        nom=user_dict["nom"],
        created_at=user_dict["created_at"]
    )
    
    return Token(access_token=access_token, token_type="bearer", user=user)

@api_router.post("/auth/login", response_model=Token)
async def login(user_data: UserLogin):
    user = await db.users.find_one({"email": user_data.email})
    if not user or not verify_password(user_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    
    access_token = create_access_token({"sub": user["id"]})
    
    user_obj = User(
        id=user["id"],
        email=user["email"],
        nom=user["nom"],
        created_at=user["created_at"]
    )
    
    return Token(access_token=access_token, token_type="bearer", user=user_obj)

@api_router.get("/auth/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

# Document Routes
@api_router.post("/documents", response_model=Document)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")
    
    # Read file
    pdf_bytes = await file.read()
    
    # Extract text (try both methods)
    text = extract_text_from_pdf(pdf_bytes)
    if not text.strip():
        text = extract_text_with_ocr(pdf_bytes)
    
    # Parse lines
    lines = parse_accounting_lines(text)
    
    # Create document
    doc_dict = {
        "id": str(uuid.uuid4()),
        "user_id": current_user.id,
        "filename": file.filename,
        "upload_date": datetime.now(timezone.utc).isoformat(),
        "status": "processed",
        "total_lines": len(lines)
    }
    
    await db.documents.insert_one(doc_dict)
    
    # Save lines
    for line_data in lines:
        line_dict = {
            "id": str(uuid.uuid4()),
            "document_id": doc_dict["id"],
            **line_data
        }
        await db.accounting_lines.insert_one(line_dict)
    
    return Document(**doc_dict)

@api_router.get("/documents", response_model=List[Document])
async def get_documents(current_user: User = Depends(get_current_user)):
    docs = await db.documents.find(
        {"user_id": current_user.id},
        {"_id": 0}
    ).sort("upload_date", -1).to_list(100)
    return [Document(**doc) for doc in docs]

@api_router.get("/documents/{document_id}", response_model=Document)
async def get_document(
    document_id: str,
    current_user: User = Depends(get_current_user)
):
    doc = await db.documents.find_one(
        {"id": document_id, "user_id": current_user.id},
        {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    return Document(**doc)

@api_router.get("/documents/{document_id}/lines", response_model=List[AccountingLine])
async def get_document_lines(
    document_id: str,
    current_user: User = Depends(get_current_user)
):
    # Verify document ownership
    doc = await db.documents.find_one({"id": document_id, "user_id": current_user.id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    
    lines = await db.accounting_lines.find(
        {"document_id": document_id},
        {"_id": 0}
    ).sort("line_number", 1).to_list(1000)
    
    return [AccountingLine(**line) for line in lines]

# Justification Routes
@api_router.post("/lines/{line_id}/justifications", response_model=Justification)
async def create_justification(
    line_id: str,
    justification_data: JustificationCreate,
    current_user: User = Depends(get_current_user)
):
    # Verify line exists and user owns it
    line = await db.accounting_lines.find_one({"id": line_id}, {"_id": 0})
    if not line:
        raise HTTPException(status_code=404, detail="Ligne non trouvée")
    
    doc = await db.documents.find_one({"id": line["document_id"], "user_id": current_user.id})
    if not doc:
        raise HTTPException(status_code=403, detail="Accès refusé")
    
    # Calculate totals
    total_debit = sum(d.debit for d in justification_data.details)
    total_credit = sum(d.credit for d in justification_data.details)
    
    # Check if totals match
    is_validated = (total_debit == line["debit"] and total_credit == line["credit"])
    
    just_dict = {
        "id": str(uuid.uuid4()),
        "line_id": line_id,
        "details": [d.model_dump() for d in justification_data.details],
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_validated": is_validated,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.justifications.insert_one(just_dict)
    
    return Justification(**just_dict)

@api_router.get("/lines/{line_id}/justifications", response_model=Optional[Justification])
async def get_justification(
    line_id: str,
    current_user: User = Depends(get_current_user)
):
    # Verify access
    line = await db.accounting_lines.find_one({"id": line_id}, {"_id": 0})
    if not line:
        raise HTTPException(status_code=404, detail="Ligne non trouvée")
    
    doc = await db.documents.find_one({"id": line["document_id"], "user_id": current_user.id})
    if not doc:
        raise HTTPException(status_code=403, detail="Accès refusé")
    
    just = await db.justifications.find_one({"line_id": line_id}, {"_id": 0})
    
    if just:
        return Justification(**just)
    return None

@api_router.put("/justifications/{justification_id}", response_model=Justification)
async def update_justification(
    justification_id: str,
    justification_data: JustificationCreate,
    current_user: User = Depends(get_current_user)
):
    just = await db.justifications.find_one({"id": justification_id}, {"_id": 0})
    if not just:
        raise HTTPException(status_code=404, detail="Justification non trouvée")
    
    # Verify access
    line = await db.accounting_lines.find_one({"id": just["line_id"]}, {"_id": 0})
    doc = await db.documents.find_one({"id": line["document_id"], "user_id": current_user.id})
    if not doc:
        raise HTTPException(status_code=403, detail="Accès refusé")
    
    # Calculate totals
    total_debit = sum(d.debit for d in justification_data.details)
    total_credit = sum(d.credit for d in justification_data.details)
    
    # Check if totals match
    is_validated = (total_debit == line["debit"] and total_credit == line["credit"])
    
    update_data = {
        "details": [d.model_dump() for d in justification_data.details],
        "total_debit": total_debit,
        "total_credit": total_credit,
        "is_validated": is_validated
    }
    
    await db.justifications.update_one(
        {"id": justification_id},
        {"$set": update_data}
    )
    
    updated_just = await db.justifications.find_one({"id": justification_id}, {"_id": 0})
    return Justification(**updated_just)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()