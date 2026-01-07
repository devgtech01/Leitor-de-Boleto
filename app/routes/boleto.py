from fastapi import APIRouter, UploadFile, File, Request, Form # Adicionado Form
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import pandas as pd
import io
import os
from typing import List
from app.services.boleto_service import processar_boleto

router = APIRouter(prefix="/boleto", tags=["Boleto"])
templates = Jinja2Templates(directory="app/templates")

@router.post("/upload")
async def upload_boleto(
    request: Request, 
    files: List[UploadFile] = File(...), 
    formato: str = Form(...) # Captura o valor do <select>
):
    os.makedirs("temp", exist_ok=True)
    resultados = []

    for file in files:
        caminho = f"temp/{file.filename}"
        with open(caminho, "wb") as f:
            f.write(await file.read())

        dados = processar_boleto(caminho)
        # Achata a estrutura para facilitar a criação da planilha
        resultados.append({
            "arquivo": file.filename,
            **dados # Espalha os campos (banco, valor, etc) na raiz do dicionário
        })

    # 1. Se o formato for JSON, renderiza na tela como antes
    if formato == "json":
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "resultado": {"total": len(resultados), "resultados": resultados}
        })

    # 2. Se for CSV ou Excel, usa o Pandas
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