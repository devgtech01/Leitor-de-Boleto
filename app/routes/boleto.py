from fastapi import APIRouter, UploadFile, File, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import io
import os
import time
from typing import List

# Importações do novo ecossistema SaaS
from app.database import get_db
from app.services.boleto_service import processar_boleto
from app.models.user import User
from app.models.boleto_history import BoletoHistory
from app.auth.security import get_current_user

router = APIRouter(tags=["Boletos"])
templates = Jinja2Templates(directory="app/templates")


def _require_pandas():
    try:
        import pandas as pd  # type: ignore
    except ModuleNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail="Dependência ausente: instale `pandas` para exportar CSV/Excel.",
        ) from e
    return pd

@router.post("/upload")
async def upload_boleto(
    request: Request, 
    files: List[UploadFile] = File(...), 
    formato: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user) # Protegido!
):
    # 2. Verificação de Créditos antes de começar (admin não tem limite)
    if (not user.is_admin) and user.creditos < len(files):
        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": user,
            "erro": f"Créditos insuficientes! Você possui {user.creditos} créditos."
        })

    os.makedirs("temp", exist_ok=True)
    resultados = []

    for file in files:
        caminho = f"temp/{file.filename}"
        with open(caminho, "wb") as f:
            f.write(await file.read())

        # Processamento via IA + telemetria básica
        start = time.perf_counter()
        try:
            dados, telemetria = processar_boleto(caminho)
            sucesso = True
            erro_msg = None
        except Exception as e:
            dados = {}
            telemetria = {
                "modelo_ia": None,
                "paginas_total": None,
                "paginas_processadas": None,
                "processamento_ms": int((time.perf_counter() - start) * 1000),
                "render_ms": None,
                "encode_ms": None,
                "openai_ms": None,
                "parse_ms": None,
                "validate_ms": None,
            }
            sucesso = False
            erro_msg = str(e)

        # 3. Salva no Banco de Dados (Histórico)
        novo_historico = BoletoHistory(
            user_id=user.id,
            filename=file.filename,
            banco=dados.get("banco"),
            valor=dados.get("valor"),
            vencimento=dados.get("vencimento"),
            linha_digitavel=dados.get("linha_digitavel"),
            dados_completos=dados if sucesso else {"erro": erro_msg},
            sucesso=sucesso,
            erro=erro_msg,
            modelo_ia=telemetria.get("modelo_ia"),
            paginas_total=telemetria.get("paginas_total"),
            paginas_processadas=telemetria.get("paginas_processadas"),
            processamento_ms=telemetria.get("processamento_ms"),
            telemetria=telemetria,
        )
        db.add(novo_historico)

        # 4. Debita o crédito
        if sucesso and (not user.is_admin):
            user.creditos -= 1

        # Prepara resultado para a resposta imediata (Excel/CSV/Tela)
        resultados.append({
            "arquivo": file.filename,
            **dados,
            "sucesso": sucesso,
            "erro": erro_msg,
        })
        
        # Limpeza do arquivo temporário
        if os.path.exists(caminho):
            os.remove(caminho)

    # Confirma todas as alterações no banco (Créditos e Histórico)
    db.commit()

    # --- Lógica de Resposta (Mantida a original) ---

    if formato == "json":
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "user": user,
            "resultado": {"total": len(resultados), "resultados": resultados},
            "creditos_restantes": user.creditos
        })

    pd = _require_pandas()
    df = pd.DataFrame(resultados)

    if formato == "csv":
        stream = io.StringIO()
        df.to_csv(stream, index=False, sep=";", encoding="utf-8-sig")
        response = StreamingResponse(
            iter([stream.getvalue()]),
            media_type="text/csv"
        )
        response.headers["Content-Disposition"] = "attachment; filename=boletos_extraidos.csv"
        return response

    if formato == "excel":
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Boletos')
        output.seek(0)
        
        response = StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response.headers["Content-Disposition"] = "attachment; filename=boletos_extraidos.xlsx"
        return response
    

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request, 
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user) # Agora o FastAPI garante que o usuário está logado!
):
    # O filtro agora usa o ID real do usuário logado
    historico = db.query(BoletoHistory).filter(BoletoHistory.user_id == user.id).order_by(BoletoHistory.data_processamento.desc()).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "historico": historico
    })

@router.get("/dashboard/export/excel")
async def exportar_dashboard_excel(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    historico = (
        db.query(BoletoHistory)
        .filter(BoletoHistory.user_id == user.id)
        .order_by(BoletoHistory.data_processamento.desc())
        .all()
    )

    linhas = []
    for item in historico:
        linhas.append(
            {
                "data_processamento": item.data_processamento.isoformat() if item.data_processamento else None,
                "arquivo": item.filename,
                "banco": item.banco,
                "valor": item.valor,
                "vencimento": item.vencimento,
                "linha_digitavel": item.linha_digitavel,
                "sucesso": getattr(item, "sucesso", None),
                "processamento_ms": getattr(item, "processamento_ms", None),
            }
        )

    pd = _require_pandas()
    df = pd.DataFrame(linhas)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Historico")
    output.seek(0)

    response = StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response.headers["Content-Disposition"] = "attachment; filename=dashboard_historico.xlsx"
    return response

@router.get("/detalhes/{boleto_id}")
async def obter_detalhes(
    boleto_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Busca o boleto específico no banco
    boleto = db.query(BoletoHistory).filter(BoletoHistory.id == boleto_id).first()
    
    if not boleto:
        raise HTTPException(status_code=404, detail="Boleto não encontrado")

    if boleto.user_id != user.id:
        raise HTTPException(status_code=403, detail="Acesso negado")
    
    return boleto.dados_completos # Retorna o JSON que a IA extraiu

@router.post("/excluir/{boleto_id}")
async def excluir_boleto(
    boleto_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    boleto = db.query(BoletoHistory).filter(BoletoHistory.id == boleto_id).first()
    if not boleto:
        raise HTTPException(status_code=404, detail="Boleto não encontrado")

    if (not user.is_admin) and boleto.user_id != user.id:
        raise HTTPException(status_code=403, detail="Acesso negado")

    db.delete(boleto)
    db.commit()
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

@router.get("/logout")
async def logout():
    # Redireciona para o login e limpa o cookie de acesso
    response = RedirectResponse(url="/auth/login-page", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response
