from fastapi import APIRouter, UploadFile, File, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import io
import os
import time
from typing import List

from app.database import get_db
from app.services.nota_fiscal_service import processar_nota_fiscal
from app.models.user import User
from app.models.boleto_history import BoletoHistory
from app.auth.security import get_current_user

router = APIRouter(tags=["Notas Fiscais"])
templates = Jinja2Templates(directory="app/templates")


def _require_pandas():
    try:
        import pandas as pd  # type: ignore
    except ModuleNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail="Dependencia ausente: instale `pandas` para exportar CSV/Excel.",
        ) from e
    return pd


@router.get("/notas", response_class=HTMLResponse)
async def notas_dashboard(
    request: Request,
    user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("notas.html", {"request": request, "user": user})


@router.post("/notas/upload")
async def upload_notas(
    request: Request,
    files: List[UploadFile] = File(...),
    formato: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    max_files_raw = os.getenv("BOLETO_MAX_FILES_PER_UPLOAD", "200").strip()
    try:
        max_files = int(max_files_raw)
    except Exception:
        max_files = 200

    if len(files) > max_files:
        return templates.TemplateResponse(
            "notas.html",
            {
                "request": request,
                "user": user,
                "erro": f"Limite por envio: {max_files} notas fiscais. Envie em lotes menores.",
            },
        )

    high_volume_threshold_raw = os.getenv("BOLETO_HIGH_VOLUME_THRESHOLD", "20").strip()
    try:
        high_volume_threshold = int(high_volume_threshold_raw)
    except Exception:
        high_volume_threshold = 20
    high_volume = len(files) >= high_volume_threshold

    if (not user.is_admin) and user.creditos < len(files):
        return templates.TemplateResponse(
            "notas.html",
            {
                "request": request,
                "user": user,
                "erro": f"Creditos insuficientes! Voce possui {user.creditos} creditos.",
            },
        )

    os.makedirs("temp", exist_ok=True)
    resultados = []

    for file in files:
        filename = file.filename or "documento"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".pdf", ".xml"):
            return templates.TemplateResponse(
                "notas.html",
                {
                    "request": request,
                    "user": user,
                    "erro": "Formato invalido. Envie PDF ou XML.",
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        caminho = f"temp/{filename}"
        with open(caminho, "wb") as f:
            f.write(await file.read())

        start = time.perf_counter()
        try:
            dados, telemetria = processar_nota_fiscal(caminho, high_volume=high_volume)
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

        pagamento = dados.get("pagamento") or {}
        vencimentos = pagamento.get("vencimentos_parcelas") or []
        vencimento = vencimentos[0] if isinstance(vencimentos, list) and vencimentos else None

        novo_historico = BoletoHistory(
            user_id=user.id,
            filename=filename,
            banco=dados.get("emitente_razao_social") or dados.get("emitente_cnpj_cpf"),
            valor=dados.get("valor_total_nota"),
            vencimento=vencimento,
            linha_digitavel=pagamento.get("linha_digitavel"),
            dados_completos=dados if sucesso else {"erro": erro_msg},
            sucesso=sucesso,
            erro=erro_msg,
            modelo_ia=telemetria.get("modelo_ia"),
            paginas_total=telemetria.get("paginas_total"),
            paginas_processadas=telemetria.get("paginas_processadas"),
            processamento_ms=telemetria.get("processamento_ms"),
            telemetria=telemetria,
            tipo_documento="nota_fiscal",
        )
        db.add(novo_historico)

        if sucesso and (not user.is_admin):
            user.creditos -= 1

        resultados.append(
            {
                "arquivo": filename,
                **dados,
                "sucesso": sucesso,
                "erro": erro_msg,
            }
        )

        if os.path.exists(caminho):
            os.remove(caminho)

    db.commit()

    if formato == "json":
        return templates.TemplateResponse(
            "notas.html",
            {
                "request": request,
                "user": user,
                "resultado": {"total": len(resultados), "resultados": resultados},
                "creditos_restantes": user.creditos,
            },
        )

    pd = _require_pandas()
    df = pd.DataFrame(resultados)

    if formato == "csv":
        stream = io.StringIO()
        df.to_csv(stream, index=False, sep=";", encoding="utf-8-sig")
        response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
        response.headers["Content-Disposition"] = "attachment; filename=notas_fiscais.csv"
        return response

    if formato == "excel":
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Notas Fiscais")
        output.seek(0)

        response = StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response.headers["Content-Disposition"] = "attachment; filename=notas_fiscais.xlsx"
        return response

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
