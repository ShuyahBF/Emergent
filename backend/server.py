from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
from jose import JWTError, jwt
import PyPDF2
import pytesseract
from pdf2image import convert_from_bytes
import re
import io
import httpx

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

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
    role: str = "consultation"
    created_at: str

class UserRoleUpdate(BaseModel):
    role: str

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    nom: str
    role: str = "consultation"

class UserPasswordUpdate(BaseModel):
    password: str

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
    calculated_total: float = 0.0
    line_number: int

class AccountingLineUpdate(BaseModel):
    label: Optional[str] = None
    debit: Optional[float] = None
    credit: Optional[float] = None

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

class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = "site_settings"
    site_title: str = "Justification Comptable"
    company_name: str = "Mon Entreprise"
    company_logo: str = ""
    webhooks: Dict[str, str] = {
        "login": "",
        "logout": "",
        "line_modified": "",
        "justification_added": "",
        "justification_updated": "",
        "pdf_imported": "",
        "pdf_exported": ""
    }

class SettingsUpdate(BaseModel):
    site_title: Optional[str] = None
    company_name: Optional[str] = None
    company_logo: Optional[str] = None
    webhooks: Optional[Dict[str, str]] = None

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

def require_role(required_roles: List[str]):
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in required_roles:
            raise HTTPException(status_code=403, detail="Permission refusée")
        return current_user
    return role_checker

# Webhook Function
async def trigger_webhook(event: str, data: dict):
    try:
        settings_doc = await db.settings.find_one({"id": "site_settings"}, {"_id": 0})
        if not settings_doc:
            return
        
        webhook_url = settings_doc.get("webhooks", {}).get(event, "")
        if not webhook_url:
            return
        
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(webhook_url, json=data)
            logging.info(f"Webhook {event} triggered successfully")
    except Exception as e:
        logging.error(f"Webhook {event} failed: {e}")

# PDF Processing Functions
def extract_text_from_pdf(pdf_bytes: bytes) -> str:
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
    """Parse accounting lines from extracted PDF text - Multiple formats supported"""
    lines = []
    text_lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Enlever les headers communs (mais pas les lignes avec N° de compte)
    filtered_lines = []
    for line in text_lines:
        # Si la ligne commence par un numéro de compte, la garder
        if re.match(r'^[0-9]{3,15}\s', line):
            filtered_lines.append(line)
        # Sinon, vérifier si ce n'est pas un header
        elif not any(header in line.lower() for header in 
                    ['n° compte', 'n° cpte', 'numero compte', 'intitule', 'intitulé', 
                     'libelle', 'libellé', 'debit', 'débit', 'credit', 'crédit', 'solde']):
            filtered_lines.append(line)
    
    text_lines = filtered_lines
    line_number = 0
    
    for current_line in text_lines:
        # Format principal : une ligne avec N° compte + libellé + débit + crédit
        # Exemple: 701109 VENTE M/SES /BBBOUTIC OUAG 15 000 15 000
        
        if re.match(r'^[0-9]{3,15}\s', current_line):
            parts = current_line.split()
            
            # Doit avoir au moins : compte + 1 mot libellé + 2 nombres (débit) + 2 nombres (crédit) = 6 parties minimum
            if len(parts) >= 5 and re.match(r'^[0-9]{3,15}$', parts[0]):
                try:
                    account_number = parts[0]
                    
                    # Stratégie : les montants sont à la fin, en format "15 000" (2 parties)
                    # Les 4 dernières parties sont : débit1 débit2 crédit1 crédit2
                    # Exemple: [..., '15', '000', '15', '000']
                    
                    if len(parts) >= 5:
                        # Le libellé est entre le compte et les 4 derniers éléments
                        label_parts = parts[1:-4]
                        debit_parts = parts[-4:-2]
                        credit_parts = parts[-2:]
                        
                        label = ' '.join(label_parts)
                        debit_str = ''.join(debit_parts).replace(' ', '')
                        credit_str = ''.join(credit_parts).replace(' ', '')
                        
                        debit = float(debit_str) if debit_str else 0.0
                        credit = float(credit_str) if credit_str else 0.0
                        
                        line_number += 1
                        total = debit if debit != 0 else credit
                        
                        lines.append({
                            "account_number": account_number,
                            "label": label,
                            "debit": debit,
                            "credit": credit,
                            "total": total,
                            "calculated_total": 0.0,
                            "line_number": line_number
                        })
                        continue
                except (ValueError, IndexError):
                    pass
            
            # Format alternatif : colonnes séparées par espaces multiples
            parts_multi = re.split(r'\s{2,}', current_line.strip())
            
            if len(parts_multi) >= 3:
                try:
                    account_number = parts_multi[0].strip()
                    label = parts_multi[1].strip()
                    
                    amounts = [p.strip() for p in parts_multi[2:]]
                    debit_str = amounts[0] if len(amounts) > 0 else "0"
                    credit_str = amounts[1] if len(amounts) > 1 else "0"
                    
                    debit_str_clean = debit_str.replace(' ', '').replace(',', '.').replace('−', '-')
                    credit_str_clean = credit_str.replace(' ', '').replace(',', '.').replace('−', '-')
                    
                    debit = float(debit_str_clean) if debit_str_clean and debit_str_clean not in ['-', ''] else 0.0
                    credit = float(credit_str_clean) if credit_str_clean and credit_str_clean not in ['-', ''] else 0.0
                    
                    line_number += 1
                    total = debit if debit != 0 else credit
                    
                    lines.append({
                        "account_number": account_number,
                        "label": label,
                        "debit": debit,
                        "credit": credit,
                        "total": total,
                        "calculated_total": 0.0,
                        "line_number": line_number
                    })
                except (ValueError, IndexError):
                    pass
    
    return lines

# Auth Routes
@api_router.post("/auth/register", response_model=Token)
async def register(user_data: UserRegister):
    existing_user = await db.users.find_one({"email": user_data.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Email déjà enregistré")
    
    # Liste des emails superviseurs
    superviseur_emails = ["jfrancois.ouoba@gmail.com", "admin.test@comptable.fr"]
    role = "superviseur" if user_data.email in superviseur_emails else "consultation"
    
    user_dict = {
        "id": str(uuid.uuid4()),
        "email": user_data.email,
        "password_hash": hash_password(user_data.password),
        "nom": user_data.nom,
        "role": role,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.users.insert_one(user_dict)
    access_token = create_access_token({"sub": user_dict["id"]})
    
    user = User(
        id=user_dict["id"],
        email=user_dict["email"],
        nom=user_dict["nom"],
        role=user_dict["role"],
        created_at=user_dict["created_at"]
    )
    
    await trigger_webhook("login", {
        "event": "user_registered",
        "user_email": user.email,
        "user_name": user.nom,
        "user_role": user.role,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
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
        role=user.get("role", "consultation"),
        created_at=user["created_at"]
    )
    
    await trigger_webhook("login", {
        "event": "user_login",
        "user_email": user_obj.email,
        "user_name": user_obj.nom,
        "user_role": user_obj.role,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return Token(access_token=access_token, token_type="bearer", user=user_obj)

@api_router.post("/auth/logout")
async def logout(current_user: User = Depends(get_current_user)):
    await trigger_webhook("logout", {
        "event": "user_logout",
        "user_email": current_user.email,
        "user_name": current_user.nom,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    return {"message": "Déconnexion réussie"}

@api_router.get("/auth/me", response_model=User)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

# User Management Routes
@api_router.get("/users", response_model=List[User])
async def get_users(current_user: User = Depends(require_role(["superviseur"]))):
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(1000)
    return [User(**user) for user in users]

@api_router.put("/users/{user_id}/role", response_model=User)
async def update_user_role(
    user_id: str,
    role_update: UserRoleUpdate,
    current_user: User = Depends(require_role(["superviseur"]))
):
    if role_update.role not in ["consultation", "modification", "superviseur"]:
        raise HTTPException(status_code=400, detail="Rôle invalide")
    
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"role": role_update.role}}
    )
    
    updated_user = await db.users.find_one({"id": user_id}, {"_id": 0})
    return User(**updated_user)

@api_router.post("/users/{user_id}/activate")
async def activate_user(
    user_id: str,
    current_user: User = Depends(require_role(["superviseur"]))
):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"is_active": True}}
    )
    
    return {"message": "Compte activé avec succès", "user_id": user_id}

@api_router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    current_user: User = Depends(require_role(["superviseur"]))
):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"is_active": False}}
    )
    
    return {"message": "Compte désactivé avec succès", "user_id": user_id}

@api_router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_role(["superviseur"]))
):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    
    # Désactiver le compte au lieu de le supprimer
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"is_active": False}}
    )
    
    return {"message": "Compte désactivé avec succès", "user_id": user_id}

@api_router.post("/users/create")
async def create_user_manual(
    user_data: UserCreate,
    current_user: User = Depends(require_role(["superviseur"]))
):
    existing = await db.users.find_one({"email": user_data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
    
    user_dict = {
        "id": str(uuid.uuid4()),
        "email": user_data.email,
        "password_hash": hash_password(user_data.password),
        "nom": user_data.nom,
        "role": user_data.role,
        "is_active": True,
        "email_verified": True,
        "email_verified_at": datetime.now(timezone.utc).isoformat(),
        "last_login": None,
        "verification_token": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.users.insert_one(user_dict)
    
    return {"message": "Utilisateur créé avec succès", "user_id": user_dict["id"]}

@api_router.put("/users/{user_id}/password")
async def update_user_password(
    user_id: str,
    password_data: UserPasswordUpdate,
    current_user: User = Depends(require_role(["superviseur"]))
):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"password_hash": hash_password(password_data.password)}}
    )
    
    return {"message": "Mot de passe mis à jour avec succès", "user_id": user_id}

# Document Routes
@api_router.post("/documents", response_model=Document)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")
    
    pdf_bytes = await file.read()
    text = extract_text_from_pdf(pdf_bytes)
    if not text.strip():
        text = extract_text_with_ocr(pdf_bytes)
    
    lines = parse_accounting_lines(text)
    
    doc_dict = {
        "id": str(uuid.uuid4()),
        "user_id": current_user.id,
        "filename": file.filename,
        "upload_date": datetime.now(timezone.utc).isoformat(),
        "status": "processed",
        "total_lines": len(lines)
    }
    
    await db.documents.insert_one(doc_dict)
    
    for line_data in lines:
        line_dict = {
            "id": str(uuid.uuid4()),
            "document_id": doc_dict["id"],
            **line_data
        }
        await db.accounting_lines.insert_one(line_dict)
    
    await trigger_webhook("pdf_imported", {
        "event": "pdf_imported",
        "user_email": current_user.email,
        "user_name": current_user.nom,
        "document_id": doc_dict["id"],
        "filename": file.filename,
        "lines_count": len(lines),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
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
    # Base de données partagée : tous les utilisateurs peuvent voir toutes les lignes
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    
    lines = await db.accounting_lines.find(
        {"document_id": document_id},
        {"_id": 0}
    ).sort("line_number", 1).to_list(1000)
    
    return [AccountingLine(**line) for line in lines]

@api_router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    current_user: User = Depends(require_role(["modification", "superviseur"]))
):
    """Supprimer définitivement un document PDF et ses lignes associées"""
    doc = await db.documents.find_one({"id": document_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    
    # Supprimer les lignes comptables associées
    await db.accounting_lines.delete_many({"document_id": document_id})
    
    # Supprimer les justifications associées aux lignes
    lines = await db.accounting_lines.find({"document_id": document_id}).to_list(1000)
    for line in lines:
        await db.justifications.delete_many({"line_id": line["id"]})
    
    # Supprimer le document
    await db.documents.delete_one({"id": document_id})
    
    return {"message": "Document supprimé avec succès", "document_id": document_id}

# Accounting Line Routes
@api_router.put("/lines/{line_id}", response_model=AccountingLine)
async def update_line(
    line_id: str,
    line_update: AccountingLineUpdate,
    current_user: User = Depends(require_role(["modification", "superviseur"]))
):
    line = await db.accounting_lines.find_one({"id": line_id}, {"_id": 0})
    if not line:
        raise HTTPException(status_code=404, detail="Ligne non trouvée")
    
    doc = await db.documents.find_one({"id": line["document_id"], "user_id": current_user.id})
    if not doc:
        raise HTTPException(status_code=403, detail="Accès refusé")
    
    line_before = line.copy()
    update_data = {}
    
    if line_update.label is not None:
        update_data["label"] = line_update.label
    
    if line_update.debit is not None:
        update_data["debit"] = line_update.debit
        update_data["credit"] = 0.0
        update_data["total"] = line_update.debit
    
    if line_update.credit is not None:
        update_data["credit"] = line_update.credit
        update_data["debit"] = 0.0
        update_data["total"] = line_update.credit
    
    if update_data:
        await db.accounting_lines.update_one(
            {"id": line_id},
            {"$set": update_data}
        )
    
    updated_line = await db.accounting_lines.find_one({"id": line_id}, {"_id": 0})
    
    await trigger_webhook("line_modified", {
        "event": "line_modified",
        "user_email": current_user.email,
        "user_name": current_user.nom,
        "line_id": line_id,
        "before": line_before,
        "after": updated_line,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return AccountingLine(**updated_line)

# Justification Routes
@api_router.post("/lines/{line_id}/justifications", response_model=Justification)
async def create_justification(
    line_id: str,
    justification_data: JustificationCreate,
    current_user: User = Depends(require_role(["modification", "superviseur"]))
):
    line = await db.accounting_lines.find_one({"id": line_id}, {"_id": 0})
    if not line:
        raise HTTPException(status_code=404, detail="Ligne non trouvée")
    
    doc = await db.documents.find_one({"id": line["document_id"], "user_id": current_user.id})
    if not doc:
        raise HTTPException(status_code=403, detail="Accès refusé")
    
    total_debit = sum(d.debit for d in justification_data.details)
    total_credit = sum(d.credit for d in justification_data.details)
    is_validated = (
        abs(total_debit - line["debit"]) < 0.01 and
        abs(total_credit - line["credit"]) < 0.01
    )
    
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
    
    calculated_total = total_debit + total_credit
    await db.accounting_lines.update_one(
        {"id": line_id},
        {"$set": {"calculated_total": calculated_total}}
    )
    
    await trigger_webhook("justification_added", {
        "event": "justification_added",
        "user_email": current_user.email,
        "user_name": current_user.nom,
        "line_id": line_id,
        "justification": just_dict,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return Justification(**just_dict)

@api_router.get("/lines/{line_id}/justifications", response_model=Optional[Justification])
async def get_justification(
    line_id: str,
    current_user: User = Depends(get_current_user)
):
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
    current_user: User = Depends(require_role(["modification", "superviseur"]))
):
    just = await db.justifications.find_one({"id": justification_id}, {"_id": 0})
    if not just:
        raise HTTPException(status_code=404, detail="Justification non trouvée")
    
    just_before = just.copy()
    line = await db.accounting_lines.find_one({"id": just["line_id"]}, {"_id": 0})
    doc = await db.documents.find_one({"id": line["document_id"], "user_id": current_user.id})
    if not doc:
        raise HTTPException(status_code=403, detail="Accès refusé")
    
    total_debit = sum(d.debit for d in justification_data.details)
    total_credit = sum(d.credit for d in justification_data.details)
    is_validated = (
        abs(total_debit - line["debit"]) < 0.01 and
        abs(total_credit - line["credit"]) < 0.01
    )
    
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
    
    calculated_total = total_debit + total_credit
    await db.accounting_lines.update_one(
        {"id": just["line_id"]},
        {"$set": {"calculated_total": calculated_total}}
    )
    
    updated_just = await db.justifications.find_one({"id": justification_id}, {"_id": 0})
    
    await trigger_webhook("justification_updated", {
        "event": "justification_updated",
        "user_email": current_user.email,
        "user_name": current_user.nom,
        "justification_id": justification_id,
        "before": just_before,
        "after": updated_just,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    
    return Justification(**updated_just)

# Settings Routes
@api_router.get("/settings", response_model=Settings)
async def get_settings(current_user: User = Depends(require_role(["superviseur"]))):
    settings = await db.settings.find_one({"id": "site_settings"}, {"_id": 0})
    if not settings:
        default_settings = Settings().model_dump()
        await db.settings.insert_one(default_settings)
        return Settings(**default_settings)
    return Settings(**settings)

@api_router.put("/settings", response_model=Settings)
async def update_settings(
    settings_update: SettingsUpdate,
    current_user: User = Depends(require_role(["superviseur"]))
):
    settings = await db.settings.find_one({"id": "site_settings"}, {"_id": 0})
    if not settings:
        settings = Settings().model_dump()
        await db.settings.insert_one(settings)
    
    update_data = {}
    if settings_update.site_title is not None:
        update_data["site_title"] = settings_update.site_title
    if settings_update.company_name is not None:
        update_data["company_name"] = settings_update.company_name
    if settings_update.company_logo is not None:
        update_data["company_logo"] = settings_update.company_logo
    if settings_update.webhooks is not None:
        update_data["webhooks"] = settings_update.webhooks
    
    if update_data:
        await db.settings.update_one(
            {"id": "site_settings"},
            {"$set": update_data}
        )
    
    updated_settings = await db.settings.find_one({"id": "site_settings"}, {"_id": 0})
    return Settings(**updated_settings)

@api_router.get("/settings/public")
async def get_public_settings():
    """Endpoint public pour récupérer le logo et le titre sans authentification"""
    settings = await db.settings.find_one({"id": "site_settings"}, {"_id": 0})
    if not settings:
        return {
            "site_title": "Justification Comptable",
            "company_name": "Mon Entreprise",
            "company_logo": ""
        }
    return {
        "site_title": settings.get("site_title", "Justification Comptable"),
        "company_name": settings.get("company_name", "Mon Entreprise"),
        "company_logo": settings.get("company_logo", "")
    }

@api_router.post("/documents/debug-pdf")
async def debug_pdf_extraction(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """Endpoint de diagnostic pour voir le texte extrait du PDF"""
    pdf_bytes = await file.read()
    
    # Extraction texte
    text = extract_text_from_pdf(pdf_bytes)
    text_length = len(text)
    
    # Extraction OCR si le texte est vide
    ocr_text = ""
    if not text.strip():
        ocr_text = extract_text_with_ocr(pdf_bytes)
    
    # Parsing
    lines = parse_accounting_lines(text if text.strip() else ocr_text)
    
    return {
        "filename": file.filename,
        "text_extraction": {
            "method": "PyPDF2",
            "length": text_length,
            "preview": text[:500] if text else "Aucun texte extrait",
            "lines_count": len(text.split('\n'))
        },
        "ocr_extraction": {
            "used": not text.strip(),
            "preview": ocr_text[:500] if ocr_text else "Non utilisé"
        },
        "parsed_lines": len(lines),
        "sample_lines": lines[:3] if lines else []
    }

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