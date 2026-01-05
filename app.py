import os
import re
import shutil
import tempfile
from dotenv import load_dotenv

import pdfplumber
import pytesseract
from PIL import Image

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel, Field
from openai import OpenAI

# =====================
# CONFIG
# =====================

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()
templates = Jinja2Templates(directory="templates")


# =====================
# SCHEMA
# =====================

class BoletoSchema(BaseModel):
    banco: str = ""
    beneficiario: str = ""
    cnpj_beneficiario: str = ""
    valor: str = ""
    data_vencimento: str = ""
    linha_digitavel: str = ""
    codigo_barras: str = ""
    nosso_numero: str = ""


# =====================
# TEXT EXTRACTION
# =====================

def extrair_texto(caminho: str) -> str:
    ext = os.path.splitext(caminho)[1].lower()

    # PDF
    if ext == ".pdf":
        texto = ""

        with pdfplumber.open(caminho) as pdf:
            for pagina in pdf.pages:
                t = pagina.extract_text()
                if t:
                    texto += t + "\n"

        if texto.strip():
            return texto.strip()

        raise RuntimeError("PDF sem texto (OCR em PDF não implementado)")

    # IMAGEM
    elif ext in [".png", ".jpg", ".jpeg"]:
        imagem = Image.open(caminho)
        return pytesseract.image_to_string(imagem, lang="por")

    else:
        raise RuntimeError("Formato de arquivo não suportado")
    
def extrair_dados(texto):
    prompt = f"""
Responda APENAS com JSON válido.
NÃO use markdown.
NÃO use ```json.

Campos:
- banco
- beneficiario
- cnpj_beneficiario
- valor
- data_vencimento
- linha_digitavel
- codigo_barras
- nosso_numero

Texto do boleto:
{texto}
"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        temperature=0,
        messages=[
            {"role": "system", "content": "Extração estruturada de boletos bancários brasileiros"},
            {"role": "user", "content": prompt},
        ],
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json|```$", "", raw, flags=re.MULTILINE).strip()

    return BoletoSchema.model_validate_json(raw)


# =====================
# ROUTES
# =====================

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    sufixo = os.path.splitext(file.filename)[1]

    with tempfile.NamedTemporaryFile(delete=False, suffix=sufixo) as tmp:
        shutil.copyfileobj(file.file, tmp)
        caminho = tmp.name

    texto = extrair_texto(caminho)
    dados = extrair_dados(texto)

    return {"resultado": dados.model_dump()}