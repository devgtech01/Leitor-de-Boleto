from fastapi import APIRouter, Depends, HTTPException, Form, status, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import re
from app.database import get_db
from app.models.user import User
from app.auth.security import get_password_hash, verify_password, create_access_token
from fastapi.templating import Jinja2Templates
from app.users.plans import ensure_plano_fields

router = APIRouter(prefix="/auth", tags=["Autenticação"])

@router.post("/signup")
async def signup(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    nome_clean = nome.strip()
    email_clean = str(email).strip().lower()

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_clean):
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "erro": "Informe um e-mail válido.", "nome": nome_clean, "email": email},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(nome_clean) < 2:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "erro": "Informe seu nome.", "nome": nome, "email": email_clean},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(password) < 6:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "erro": "A senha deve ter no mínimo 6 caracteres.",
                "nome": nome_clean,
                "email": email_clean,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "erro": "As senhas não conferem.",
                "nome": nome_clean,
                "email": email_clean,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Verifica se usuário já existe
    if db.query(User).filter(User.email == email_clean).first():
        return templates.TemplateResponse(
            "signup.html",
            {
                "request": request,
                "erro": "Email já cadastrado.",
                "nome": nome_clean,
                "email": email_clean,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    
    # Cria novo usuário com senha protegida e 10 créditos grátis
    novo_usuario = User(
        nome=nome_clean,
        email=email_clean,
        hashed_password=get_password_hash(password),
        creditos=10,
        plano="trial",
        creditos_renovam_em=datetime.now(timezone.utc) + timedelta(days=30),
    )
    ensure_plano_fields(novo_usuario)
    db.add(novo_usuario)
    db.commit()
    return RedirectResponse(url="/auth/login-page", status_code=status.HTTP_302_FOUND)

@router.post("/login")
async def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")
    
    # Gera o Token
    access_token = create_access_token(data={"sub": user.email})
    
    # Salva o token num Cookie seguro para o navegador usar automaticamente
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response

templates = Jinja2Templates(directory="app/templates")

@router.get("/signup-page")
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@router.get("/login-page")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})
