from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.security import get_current_user
from app.database import get_db
from app.models.user import User
from app.users.plans import PLANOS

router = APIRouter(tags=["Planos"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/planos", response_class=HTMLResponse)
async def planos_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse(
        "planos.html",
        {
            "request": request,
            "user": user,
            "planos": list(PLANOS.values()),
        },
    )


@router.post("/planos/escolher")
async def escolher_plano(
    plano: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.is_admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Admin não precisa de plano.")

    plano = plano.strip().lower()
    if plano not in PLANOS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plano inválido")

    user.plano_pendente = plano
    user.plano_pendente_em = datetime.now(timezone.utc)
    db.commit()

    return RedirectResponse(url="/planos", status_code=status.HTTP_303_SEE_OTHER)

