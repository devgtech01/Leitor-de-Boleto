from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.security import require_admin
from app.database import get_db
from app.models.boleto_history import BoletoHistory
from app.models.user import User
from app.users.plans import PLANOS, plano_creditos

router = APIRouter(prefix="/admin", tags=["Admin"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    usuarios = db.query(User).order_by(User.id.asc()).all()
    historico = (
        db.query(BoletoHistory)
        .order_by(BoletoHistory.data_processamento.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": admin_user,
            "usuarios": usuarios,
            "historico": historico,
            "planos": list(PLANOS.keys()),
        },
    )


@router.get("/detalhes/{boleto_id}")
async def admin_obter_detalhes(
    boleto_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    boleto = db.query(BoletoHistory).filter(BoletoHistory.id == boleto_id).first()
    if not boleto:
        raise HTTPException(status_code=404, detail="Boleto não encontrado")
    return boleto.dados_completos


@router.post("/users/{user_id}/plan")
async def admin_definir_plano(
    user_id: int,
    plano: str = Form(...),
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    plano = plano.strip().lower()
    if plano not in PLANOS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plano inválido")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    user.plano = plano
    user.creditos = plano_creditos(plano)
    user.creditos_renovam_em = datetime.now(timezone.utc) + timedelta(days=30)
    db.commit()

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/plan/approve-pending")
async def admin_aprovar_plano_pendente(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    if not user.plano_pendente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Usuário não tem plano pendente")

    plano = user.plano_pendente.strip().lower()
    if plano not in PLANOS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plano pendente inválido")

    user.plano = plano
    user.creditos = plano_creditos(plano)
    user.creditos_renovam_em = datetime.now(timezone.utc) + timedelta(days=30)
    user.plano_pendente = None
    user.plano_pendente_em = None
    db.commit()

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/users/{user_id}/credits")
async def admin_adicionar_creditos(
    user_id: int,
    creditos: int = Form(...),
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin),
):
    if creditos <= 0 or creditos > 1_000_000:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quantidade inválida")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    user.creditos = (user.creditos or 0) + creditos
    db.commit()

    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
