import os
import base64
import json
import fitz  # Import do PyMuPDF
from openai import OpenAI
from app.schemas.boleto import BoletoSchema
from app.utils.confidence import calcular_confidencia

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def processar_boleto(caminho_pdf: str) -> dict:
    temp_img = caminho_pdf.replace(".pdf", ".png")
    
    # 1. Converter PDF para imagem usando PyMuPDF (Sem Poppler!)
    doc = fitz.open(caminho_pdf)
    page = doc.load_page(0)  # Primeira página
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # Aumenta a qualidade (2x)
    pix.save(temp_img)
    doc.close()

    # 2. Codificar para Base64 para a OpenAI
    with open(temp_img, "rb") as img_file:
        img_b64 = base64.b64encode(img_file.read()).decode("utf-8")

    # 3. Prompt para a IA
    prompt = """
    Você é um especialista em boletos brasileiros. Extraia os dados deste boleto e retorne um JSON:
    - banco (nome do banco)
    - linha_digitavel (apenas números)
    - codigo_barras (apenas números)
    - valor (float)
    - vencimento (YYYY-MM-DD)
    - beneficiario (nome da empresa)
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}
                ]
            }
        ],
        response_format={"type": "json_object"}
    )

    # 4. Limpeza e Retorno
    if os.path.exists(temp_img):
        os.remove(temp_img)
        
    dados_extraidos = json.loads(response.choices[0].message.content)
    
    # Validação com seu Schema Pydantic
    boleto_valido = BoletoSchema(**dados_extraidos)
    boleto_valido.confidence_score = calcular_confidencia(boleto_valido)

    return boleto_valido.model_dump()