import os
import base64
import json
import fitz  # Import do PyMuPDF
import time
import io
from openai import OpenAI
from app.schemas.boleto import BoletoSchema
from app.utils.confidence import calcular_confidencia

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def processar_boleto(caminho_pdf: str) -> tuple[dict, dict]:
    start_total = time.perf_counter()
    
    paginas_total = None
    modelo_ia = "gpt-4o-mini"
    render_ms = None
    encode_ms = None
    openai_ms = None
    parse_ms = None
    validate_ms = None
    image_format = os.getenv("BOLETO_IMAGE_FORMAT", "jpeg").strip().lower()
    render_scale_raw = os.getenv("BOLETO_RENDER_SCALE", "2.0").strip()
    jpeg_quality_raw = os.getenv("BOLETO_JPEG_QUALITY", "70").strip()

    try:
        try:
            render_scale = float(render_scale_raw)
        except Exception:
            render_scale = 2.0

        try:
            jpeg_quality = int(jpeg_quality_raw)
        except Exception:
            jpeg_quality = 70
        jpeg_quality = max(30, min(95, jpeg_quality))

        if image_format in ("jpg", "jpeg"):
            image_format = "jpeg"
            image_mime = "image/jpeg"
        else:
            image_format = "png"
            image_mime = "image/png"

        # 1. Converter PDF para imagem usando PyMuPDF (Sem Poppler!)
        t0 = time.perf_counter()
        doc = fitz.open(caminho_pdf)
        try:
            paginas_total = doc.page_count
            page = doc.load_page(0)  # Primeira página
            pix = page.get_pixmap(
                matrix=fitz.Matrix(render_scale, render_scale),
                colorspace=fitz.csRGB,
                alpha=False,
            )
        finally:
            doc.close()
        render_ms = int((time.perf_counter() - t0) * 1000)

        # 2. Codificar para Base64 para a OpenAI (in-memory)
        t0 = time.perf_counter()
        from PIL import Image

        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        buf = io.BytesIO()
        if image_format == "jpeg":
            image.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
        else:
            image.save(buf, format="PNG", optimize=True)
        image_bytes = buf.getvalue()
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        encode_ms = int((time.perf_counter() - t0) * 1000)
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

        t0 = time.perf_counter()
        response = client.chat.completions.create(
            model=modelo_ia,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{img_b64}"}}
                    ]
                }
            ],
            response_format={"type": "json_object"}
        )
        openai_ms = int((time.perf_counter() - t0) * 1000)
        
        t0 = time.perf_counter()
        dados_extraidos = json.loads(response.choices[0].message.content)
        parse_ms = int((time.perf_counter() - t0) * 1000)
    
        # Validação com seu Schema Pydantic
        t0 = time.perf_counter()
        boleto_valido = BoletoSchema(**dados_extraidos)
        boleto_valido.confidence_score = calcular_confidencia(boleto_valido)
        validate_ms = int((time.perf_counter() - t0) * 1000)

        total_ms = int((time.perf_counter() - start_total) * 1000)
        telemetria = {
            "modelo_ia": modelo_ia,
            "paginas_total": paginas_total,
            "paginas_processadas": 1,
            "processamento_ms": total_ms,
            "render_ms": render_ms,
            "encode_ms": encode_ms,
            "openai_ms": openai_ms,
            "parse_ms": parse_ms,
            "validate_ms": validate_ms,
            "image_format": image_format,
            "render_scale": render_scale,
            "image_bytes": len(image_bytes),
        }

        return boleto_valido.model_dump(), telemetria
    finally:
        # Sem arquivos temporários nessa versão
        pass
