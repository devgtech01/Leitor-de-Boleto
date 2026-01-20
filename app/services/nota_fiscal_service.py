import os
import base64
import json
import re
import random
import fitz  # PyMuPDF
import time
import io
from openai import OpenAI
from app.schemas.nota_fiscal import NotaFiscalSchema

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def processar_nota_fiscal(caminho_arquivo: str, high_volume: bool = False) -> tuple[dict, dict]:
    start_total = time.perf_counter()
    ext = os.path.splitext(caminho_arquivo)[1].lower()

    paginas_total = None
    modelo_ia = os.getenv("NOTA_FISCAL_PRIMARY_MODEL") or os.getenv("BOLETO_PRIMARY_MODEL", "gpt-4o-mini")
    modelo_fallback = os.getenv("NOTA_FISCAL_FALLBACK_MODEL") or os.getenv("BOLETO_FALLBACK_MODEL", "gpt-4o")
    render_ms = None
    encode_ms = None
    openai_ms = None
    parse_ms = None
    validate_ms = None
    image_format = os.getenv("BOLETO_IMAGE_FORMAT", "jpeg").strip().lower()
    render_scale_raw = os.getenv("BOLETO_RENDER_SCALE", "2.0").strip()
    jpeg_quality_raw = os.getenv("BOLETO_JPEG_QUALITY", "70").strip()
    hv_render_scale_raw = os.getenv("BOLETO_HIGH_VOLUME_RENDER_SCALE", "1.4").strip()
    hv_jpeg_quality_raw = os.getenv("BOLETO_HIGH_VOLUME_JPEG_QUALITY", "55").strip()
    retry_max_raw = os.getenv("BOLETO_OPENAI_MAX_RETRIES", "3").strip()
    retry_base_raw = os.getenv("BOLETO_OPENAI_RETRY_BASE_DELAY", "1.5").strip()
    retry_max_delay_raw = os.getenv("BOLETO_OPENAI_RETRY_MAX_DELAY", "8.0").strip()
    ocr_enabled_raw = os.getenv("BOLETO_ENABLE_OCR", "1").strip()
    ocr_lang_raw = os.getenv("BOLETO_OCR_LANG", "por").strip()
    tesseract_cmd = os.getenv("BOLETO_TESSERACT_CMD", "").strip()

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

        try:
            hv_render_scale = float(hv_render_scale_raw)
        except Exception:
            hv_render_scale = 1.4

        try:
            hv_jpeg_quality = int(hv_jpeg_quality_raw)
        except Exception:
            hv_jpeg_quality = 55
        hv_jpeg_quality = max(30, min(95, hv_jpeg_quality))

        try:
            retry_max = int(retry_max_raw)
        except Exception:
            retry_max = 3

        try:
            retry_base = float(retry_base_raw)
        except Exception:
            retry_base = 1.5

        try:
            retry_max_delay = float(retry_max_delay_raw)
        except Exception:
            retry_max_delay = 8.0

        ocr_enabled = ocr_enabled_raw not in ("0", "false", "no")
        ocr_lang = ocr_lang_raw or "por"

        if high_volume:
            render_scale = min(render_scale, hv_render_scale)
            jpeg_quality = min(jpeg_quality, hv_jpeg_quality)

        if image_format in ("jpg", "jpeg"):
            image_format = "jpeg"
            image_mime = "image/jpeg"
        else:
            image_format = "png"
            image_mime = "image/png"

        text_cache = {"value": None}

        prompt = """
        Voce e um especialista em notas fiscais brasileiras (NFe, NFC-e, NFS-e).
        Extraia os dados e retorne um JSON com os campos:
        - tipo_documento (nfe, nfce, nfse)
        - chave_acesso (44 digitos)
        - numero
        - serie
        - data_emissao (YYYY-MM-DD)
        - tipo_operacao (entrada ou saida)
        - emitente_cnpj_cpf
        - emitente_razao_social
        - emitente_inscricao_estadual
        - emitente_endereco
        - destinatario_cnpj_cpf
        - destinatario_razao_social
        - destinatario_inscricao_estadual
        - destinatario_endereco
        - itens (lista com: descricao, codigo_produto, ncm, quantidade, unidade, valor_unitario, valor_total_item)
        - valor_total_nota
        - base_calculo_icms
        - valor_icms
        - valor_ipi
        - valor_pis
        - valor_cofins
        - valor_frete
        - valor_seguro
        - pagamento (objeto com: linha_digitavel, codigo_barras, vencimentos_parcelas)
        - dados_bancarios (objeto com: banco, agencia, conta)
        - iss_retido
        Se nao existir, use null. Se itens nao estiverem disponiveis, use lista vazia.
        """

        prompt_missing = """
        Voce ja extraiu parte dos dados. Com base no texto abaixo, preencha apenas os campos que estiverem ausentes.
        Retorne um JSON com os mesmos campos do extrator principal. Nao invente valores.
        """

        def _is_empty(value) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                return not value.strip() or value.strip().lower() == "null"
            if isinstance(value, list):
                return len(value) == 0
            if isinstance(value, dict):
                return len(value) == 0
            return False

        def _only_digits(value: str | None) -> str:
            if not value:
                return ""
            return "".join(ch for ch in str(value) if ch.isdigit())

        def _is_valid_cnpj_cpf(value: str | None) -> bool:
            digits = _only_digits(value)
            return len(digits) in (11, 14)

        def _normalize_doc_type(value: str | None) -> str | None:
            if not value:
                return None
            text = str(value).strip().lower()
            text = text.replace("-", "").replace(" ", "")
            if text in ("nfe", "nfce", "nfse"):
                return text
            if "nfce" in text:
                return "nfce"
            if "nfse" in text:
                return "nfse"
            if "nfe" in text:
                return "nfe"
            return None

        def _normalize_doc_id(value: str | None) -> str | None:
            digits = _only_digits(value)
            if len(digits) == 13:
                digits = f"0{digits}"
            if len(digits) in (11, 14):
                return digits
            return digits or None

        def _normalize_date(value: str | None) -> str | None:
            if not value:
                return None
            text = str(value).strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
                return text
            match = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", text)
            if match:
                day, month, year = match.groups()
                return f"{year}-{month}-{day}"
            match = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", text)
            if match:
                day, month, year = match.groups()
                return f"{year}-{month}-{day}"
            return None

        def _normalize_date_list(values) -> list[str]:
            if not values:
                return []
            if isinstance(values, str):
                values = [values]
            dates = []
            for value in values:
                normalized = _normalize_date(str(value))
                if normalized and normalized not in dates:
                    dates.append(normalized)
            return dates

        def _parse_amount(value) -> float | None:
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).strip()
            if not text:
                return None
            text = text.replace(" ", "")
            if "," in text and "." in text:
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", ".")
            match = re.search(r"-?\d+(?:\.\d+)?", text)
            if not match:
                return None
            try:
                return float(match.group())
            except Exception:
                return None

        def _normalize_nota_dict(data: dict) -> dict:
            normalized = dict(data)
            normalized["tipo_documento"] = _normalize_doc_type(normalized.get("tipo_documento"))
            normalized["chave_acesso"] = _only_digits(normalized.get("chave_acesso"))
            if normalized["chave_acesso"] and len(normalized["chave_acesso"]) == 43:
                normalized["chave_acesso"] = f"0{normalized['chave_acesso']}"
            if normalized["chave_acesso"] and len(normalized["chave_acesso"]) != 44:
                normalized["chave_acesso"] = None
            normalized["numero"] = str(normalized.get("numero")).strip() if normalized.get("numero") else None
            normalized["serie"] = str(normalized.get("serie")).strip() if normalized.get("serie") else None
            normalized["data_emissao"] = _normalize_date(normalized.get("data_emissao"))
            if normalized.get("tipo_operacao"):
                op = str(normalized.get("tipo_operacao")).strip().lower()
                normalized["tipo_operacao"] = op if op in ("entrada", "saida") else None
            normalized["emitente_cnpj_cpf"] = _normalize_doc_id(normalized.get("emitente_cnpj_cpf"))
            normalized["destinatario_cnpj_cpf"] = _normalize_doc_id(normalized.get("destinatario_cnpj_cpf"))
            normalized["emitente_inscricao_estadual"] = (
                str(normalized.get("emitente_inscricao_estadual")).strip()
                if normalized.get("emitente_inscricao_estadual")
                else None
            )
            normalized["destinatario_inscricao_estadual"] = (
                str(normalized.get("destinatario_inscricao_estadual")).strip()
                if normalized.get("destinatario_inscricao_estadual")
                else None
            )
            if not _is_valid_cnpj_cpf(normalized.get("emitente_cnpj_cpf")) and _is_valid_cnpj_cpf(
                normalized.get("emitente_inscricao_estadual")
            ):
                normalized["emitente_cnpj_cpf"] = _only_digits(normalized.get("emitente_inscricao_estadual"))
            if not _is_valid_cnpj_cpf(normalized.get("destinatario_cnpj_cpf")) and _is_valid_cnpj_cpf(
                normalized.get("destinatario_inscricao_estadual")
            ):
                normalized["destinatario_cnpj_cpf"] = _only_digits(normalized.get("destinatario_inscricao_estadual"))
            normalized["valor_total_nota"] = _parse_amount(normalized.get("valor_total_nota"))
            normalized["base_calculo_icms"] = _parse_amount(normalized.get("base_calculo_icms"))
            normalized["valor_icms"] = _parse_amount(normalized.get("valor_icms"))
            normalized["valor_ipi"] = _parse_amount(normalized.get("valor_ipi"))
            normalized["valor_pis"] = _parse_amount(normalized.get("valor_pis"))
            normalized["valor_cofins"] = _parse_amount(normalized.get("valor_cofins"))
            normalized["valor_frete"] = _parse_amount(normalized.get("valor_frete"))
            normalized["valor_seguro"] = _parse_amount(normalized.get("valor_seguro"))
            normalized["iss_retido"] = _parse_amount(normalized.get("iss_retido"))
            if normalized.get("itens") is None or not isinstance(normalized.get("itens"), list):
                normalized["itens"] = []
            if normalized.get("pagamento") is None or not isinstance(normalized.get("pagamento"), dict):
                normalized["pagamento"] = {}
            if normalized.get("dados_bancarios") is None or not isinstance(normalized.get("dados_bancarios"), dict):
                normalized["dados_bancarios"] = {}
            normalized["pagamento"]["linha_digitavel"] = _only_digits(
                normalized["pagamento"].get("linha_digitavel")
            ) or None
            normalized["pagamento"]["codigo_barras"] = _only_digits(
                normalized["pagamento"].get("codigo_barras")
            ) or None
            normalized["pagamento"]["vencimentos_parcelas"] = _normalize_date_list(
                normalized["pagamento"].get("vencimentos_parcelas")
            )
            normalized["dados_bancarios"]["banco"] = (
                str(normalized["dados_bancarios"].get("banco")).strip()
                if normalized["dados_bancarios"].get("banco")
                else None
            )
            normalized["dados_bancarios"]["agencia"] = (
                str(normalized["dados_bancarios"].get("agencia")).strip()
                if normalized["dados_bancarios"].get("agencia")
                else None
            )
            normalized["dados_bancarios"]["conta"] = (
                str(normalized["dados_bancarios"].get("conta")).strip()
                if normalized["dados_bancarios"].get("conta")
                else None
            )
            return normalized

        def _list_missing_fields(data: dict) -> list[str]:
            missing = []
            if _is_empty(data.get("tipo_documento")):
                missing.append("tipo_documento")
            if _is_empty(data.get("numero")):
                missing.append("numero")
            if _is_empty(data.get("data_emissao")):
                missing.append("data_emissao")
            if _is_empty(data.get("emitente_cnpj_cpf")):
                missing.append("emitente_cnpj_cpf")
            if _is_empty(data.get("emitente_razao_social")):
                missing.append("emitente_razao_social")
            if _is_empty(data.get("destinatario_cnpj_cpf")):
                missing.append("destinatario_cnpj_cpf")
            if _is_empty(data.get("destinatario_razao_social")):
                missing.append("destinatario_razao_social")
            if data.get("tipo_documento") in ("nfe", "nfce") and _is_empty(data.get("chave_acesso")):
                missing.append("chave_acesso")
            if _is_empty(data.get("valor_total_nota")):
                missing.append("valor_total_nota")
            return missing

        def _critical_invalid(data: dict) -> bool:
            return len(_list_missing_fields(data)) >= 4

        def _merge_missing_fields(base: dict, extra: dict):
            if not isinstance(extra, dict):
                return
            for key, value in extra.items():
                if key not in base:
                    continue
                if key in ("pagamento", "dados_bancarios") and isinstance(value, dict):
                    base[key] = base.get(key) or {}
                    for sub_key, sub_val in value.items():
                        if _is_empty(base[key].get(sub_key)) and not _is_empty(sub_val):
                            base[key][sub_key] = sub_val
                    continue
                if _is_empty(base.get(key)) and not _is_empty(value):
                    base[key] = value

        def _extract_first(pattern: str, text: str) -> str | None:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                return None
            return match.group(1).strip()

        def _extract_chave(text: str) -> str | None:
            match = re.search(r"\b\d{44}\b", text)
            if match:
                return match.group(0)
            match = re.search(r"((?:\d[\s\.-]?){44})", text)
            if match:
                return _only_digits(match.group(1))
            return None

        def _extract_doc_by_context(text: str, keywords: list[str]) -> str | None:
            for keyword in keywords:
                pattern = rf"{keyword}.{{0,200}}?(?:CNPJ|CPF)\s*[:\-]?\s*([0-9\.\-\/]{{11,20}})"
                value = _extract_first(pattern, text)
                if value:
                    normalized = _normalize_doc_id(value)
                    if normalized:
                        return normalized
            return None

        def _extract_ie_by_context(text: str, keywords: list[str]) -> str | None:
            for keyword in keywords:
                pattern = rf"{keyword}.{{0,200}}?\bIE\b\s*[:\-]?\s*([0-9\.\-\/]+)"
                value = _extract_first(pattern, text)
                if value:
                    return value
            return None

        def _extract_amount_by_label(text: str, labels: list[str]) -> float | None:
            for label in labels:
                pattern = rf"{re.escape(label)}[^0-9]{{0,10}}([0-9\.\,]{{3,}})"
                value = _extract_first(pattern, text)
                amount = _parse_amount(value)
                if amount is not None:
                    return amount
            return None

        def _extract_dates_after_label(text: str, label: str) -> list[str]:
            pattern = rf"{re.escape(label)}[^0-9]{{0,10}}([0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}})"
            matches = re.findall(pattern, text, flags=re.IGNORECASE)
            return _normalize_date_list(matches)

        def _extract_linha_barras(text: str) -> tuple[str | None, str | None]:
            digits = _only_digits(text)
            linha = None
            barras = None
            if digits:
                for match in re.findall(r"\d{47}", digits):
                    linha = match
                    break
                for match in re.findall(r"\d{44}", digits):
                    barras = match
                    break
            return linha, barras

        def _infer_tipo_documento(text: str) -> str | None:
            lower = text.lower()
            if "nfse" in lower or "nfs-e" in lower:
                return "nfse"
            if "nfce" in lower or "nfc-e" in lower:
                return "nfce"
            if "nfe" in lower or "nf-e" in lower or "danfe" in lower:
                return "nfe"
            return None

        def _apply_text_rescue(data: dict, text: str):
            if not text:
                return
            if _is_empty(data.get("tipo_documento")):
                data["tipo_documento"] = _infer_tipo_documento(text)
            if _is_empty(data.get("chave_acesso")):
                data["chave_acesso"] = _extract_chave(text)
            if _is_empty(data.get("numero")):
                data["numero"] = _extract_first(r"(?:Numero|No)\s*[:\-]?\s*(\d+)", text)
            if _is_empty(data.get("serie")):
                data["serie"] = _extract_first(r"(?:Serie)\s*[:\-]?\s*([A-Za-z0-9]+)", text)
            if _is_empty(data.get("data_emissao")):
                data["data_emissao"] = _extract_first(r"(?:Emissao|Data de Emissao)\s*[:\-]?\s*(\d{2}/\d{2}/\d{4})", text)
            if _is_empty(data.get("tipo_operacao")):
                if re.search(r"\bentrada\b", text, flags=re.IGNORECASE):
                    data["tipo_operacao"] = "entrada"
                if re.search(r"\bsaida\b", text, flags=re.IGNORECASE):
                    data["tipo_operacao"] = "saida"
            if _is_empty(data.get("emitente_cnpj_cpf")):
                data["emitente_cnpj_cpf"] = _extract_doc_by_context(text, ["Emitente", "Prestador"])
            if _is_empty(data.get("destinatario_cnpj_cpf")):
                data["destinatario_cnpj_cpf"] = _extract_doc_by_context(text, ["Destinatario", "Tomador"])
            if _is_empty(data.get("emitente_inscricao_estadual")):
                data["emitente_inscricao_estadual"] = _extract_ie_by_context(text, ["Emitente", "Prestador"])
            if _is_empty(data.get("destinatario_inscricao_estadual")):
                data["destinatario_inscricao_estadual"] = _extract_ie_by_context(text, ["Destinatario", "Tomador"])
            if _is_empty(data.get("valor_total_nota")):
                data["valor_total_nota"] = _extract_amount_by_label(
                    text, ["Valor Total", "Valor Total da Nota", "Valor da Nota"]
                )
            if _is_empty(data.get("base_calculo_icms")):
                data["base_calculo_icms"] = _extract_amount_by_label(text, ["Base de Calculo ICMS", "Base ICMS"])
            if _is_empty(data.get("valor_icms")):
                data["valor_icms"] = _extract_amount_by_label(text, ["Valor ICMS", "ICMS"])
            if _is_empty(data.get("valor_ipi")):
                data["valor_ipi"] = _extract_amount_by_label(text, ["Valor IPI", "IPI"])
            if _is_empty(data.get("valor_pis")):
                data["valor_pis"] = _extract_amount_by_label(text, ["Valor PIS", "PIS"])
            if _is_empty(data.get("valor_cofins")):
                data["valor_cofins"] = _extract_amount_by_label(text, ["Valor COFINS", "COFINS"])
            if _is_empty(data.get("valor_frete")):
                data["valor_frete"] = _extract_amount_by_label(text, ["Valor do Frete", "Frete"])
            if _is_empty(data.get("valor_seguro")):
                data["valor_seguro"] = _extract_amount_by_label(text, ["Valor do Seguro", "Seguro"])
            if _is_empty(data.get("iss_retido")):
                data["iss_retido"] = _extract_amount_by_label(text, ["ISS Retido", "ISS Retido na Fonte"])
            if "pagamento" not in data or data.get("pagamento") is None:
                data["pagamento"] = {}
            if _is_empty(data["pagamento"].get("linha_digitavel")) or _is_empty(
                data["pagamento"].get("codigo_barras")
            ):
                linha, barras = _extract_linha_barras(text)
                if _is_empty(data["pagamento"].get("linha_digitavel")):
                    data["pagamento"]["linha_digitavel"] = linha
                if _is_empty(data["pagamento"].get("codigo_barras")):
                    data["pagamento"]["codigo_barras"] = barras
            if _is_empty(data["pagamento"].get("vencimentos_parcelas")):
                vencs = _extract_dates_after_label(text, "Vencimento")
                if vencs:
                    data["pagamento"]["vencimentos_parcelas"] = vencs
            if "dados_bancarios" not in data or data.get("dados_bancarios") is None:
                data["dados_bancarios"] = {}
            if _is_empty(data["dados_bancarios"].get("banco")):
                data["dados_bancarios"]["banco"] = _extract_first(r"\bBanco\b\s*[:\-]?\s*([A-Za-z0-9 ]{3,})", text)
            if _is_empty(data["dados_bancarios"].get("agencia")):
                data["dados_bancarios"]["agencia"] = _extract_first(r"Agencia\s*[:\-]?\s*([0-9\-]+)", text)
            if _is_empty(data["dados_bancarios"].get("conta")):
                data["dados_bancarios"]["conta"] = _extract_first(r"\bConta\b\s*[:\-]?\s*([0-9\-]+)", text)

        def _render_and_encode(scale: float, quality: int):
            t0_render = time.perf_counter()
            doc = fitz.open(caminho_arquivo)
            try:
                paginas = doc.page_count
                page = doc.load_page(0)
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
            finally:
                doc.close()
            render_elapsed = int((time.perf_counter() - t0_render) * 1000)

            t0_encode = time.perf_counter()
            from PIL import Image
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            buf = io.BytesIO()
            if image_format == "jpeg":
                image.save(buf, format="JPEG", quality=quality, optimize=True)
            else:
                image.save(buf, format="PNG", optimize=True)
            image_bytes = buf.getvalue()
            img_b64_local = base64.b64encode(image_bytes).decode("utf-8")
            encode_elapsed = int((time.perf_counter() - t0_encode) * 1000)
            return paginas, img_b64_local, render_elapsed, encode_elapsed, len(image_bytes)

        def _render_image(scale: float):
            t0_render = time.perf_counter()
            doc = fitz.open(caminho_arquivo)
            try:
                paginas = doc.page_count
                page = doc.load_page(0)
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
            finally:
                doc.close()
            render_elapsed = int((time.perf_counter() - t0_render) * 1000)
            from PIL import Image
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            return paginas, image, render_elapsed

        def _call_openai_image(model_name: str, prompt_text: str, img_data: str):
            t0_call = time.perf_counter()
            response = None
            retries = 0
            last_error = None
            for attempt in range(retry_max + 1):
                try:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt_text},
                                    {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{img_data}"}},
                                ],
                            }
                        ],
                        response_format={"type": "json_object"},
                    )
                    retries = attempt
                    break
                except Exception as exc:
                    last_error = str(exc)
                    if attempt >= retry_max:
                        raise
                    delay = min(retry_max_delay, retry_base * (2 ** attempt))
                    jitter = random.random() * delay * 0.2
                    time.sleep(delay + jitter)
            elapsed_ms = int((time.perf_counter() - t0_call) * 1000)
            return response, retries, last_error, elapsed_ms

        def _call_openai_text(model_name: str, prompt_text: str, raw_text: str):
            t0_call = time.perf_counter()
            response = None
            retries = 0
            last_error = None
            payload = f"{prompt_text}\n\nTexto extraido:\n{raw_text}"
            for attempt in range(retry_max + 1):
                try:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": payload}],
                        response_format={"type": "json_object"},
                    )
                    retries = attempt
                    break
                except Exception as exc:
                    last_error = str(exc)
                    if attempt >= retry_max:
                        raise
                    delay = min(retry_max_delay, retry_base * (2 ** attempt))
                    jitter = random.random() * delay * 0.2
                    time.sleep(delay + jitter)
            elapsed_ms = int((time.perf_counter() - t0_call) * 1000)
            return response, retries, last_error, elapsed_ms

        def _parse_and_validate(response_obj):
            t0_parse = time.perf_counter()
            dados_extraidos = json.loads(response_obj.choices[0].message.content)
            parse_elapsed = int((time.perf_counter() - t0_parse) * 1000)

            t0_validate = time.perf_counter()
            nota_valida = NotaFiscalSchema(**dados_extraidos)
            validate_elapsed = int((time.perf_counter() - t0_validate) * 1000)
            return nota_valida, parse_elapsed, validate_elapsed

        def _post_process(nota_obj: NotaFiscalSchema, text_source: str | None, model_name: str):
            data = _normalize_nota_dict(nota_obj.model_dump())
            if text_source:
                _apply_text_rescue(data, text_source)
                data = _normalize_nota_dict(data)
            missing = _list_missing_fields(data)
            if text_source and missing and len(missing) >= 4:
                response_extra, _, _, _ = _call_openai_text(model_name, prompt_missing, text_source)
                extra_data = json.loads(response_extra.choices[0].message.content)
                _merge_missing_fields(data, extra_data)
                data = _normalize_nota_dict(data)
                missing = _list_missing_fields(data)
            return NotaFiscalSchema(**data), data, missing

        def _get_pdf_text() -> str:
            if text_cache["value"] is not None:
                return text_cache["value"]
            doc = fitz.open(caminho_arquivo)
            try:
                parts = []
                pages = min(2, doc.page_count)
                for page_index in range(pages):
                    text = doc.load_page(page_index).get_text("text") or ""
                    parts.append(text)
            finally:
                doc.close()
            text_cache["value"] = "\n".join(parts)
            return text_cache["value"]

        def _get_ocr_text(scale: float):
            if not ocr_enabled:
                return "", None, "disabled"
            try:
                import pytesseract
            except Exception as exc:
                return "", None, str(exc)

            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

            _, image, _ = _render_image(scale)
            t0_ocr = time.perf_counter()
            gray = image.convert("L")
            text = pytesseract.image_to_string(gray, lang=ocr_lang) or ""
            ocr_ms = int((time.perf_counter() - t0_ocr) * 1000)
            return text, ocr_ms, None

        response = None
        openai_retries = 0
        openai_error = None
        openai_ms = None
        modelo_usado = modelo_ia
        fallback_usado = False
        text_fallback_used = False
        ocr_used = False
        ocr_error = None
        ocr_ms = None
        ocr_text_len = None
        image_bytes_len = None
        missing_fields = []

        try:
            if ext == ".xml":
                with open(caminho_arquivo, "rb") as f:
                    xml_text = f.read().decode("utf-8", errors="replace")
                response, openai_retries, openai_error, openai_ms = _call_openai_text(modelo_ia, prompt, xml_text)
                nota_valida, parse_ms, validate_ms = _parse_and_validate(response)
                nota_valida, nota_data, missing_fields = _post_process(nota_valida, xml_text, modelo_ia)
                text_fallback_used = True
                if _critical_invalid(nota_data):
                    fallback_usado = True
                    modelo_usado = modelo_fallback
                    response, openai_retries, openai_error, openai_ms = _call_openai_text(modelo_fallback, prompt, xml_text)
                    nota_valida, parse_ms, validate_ms = _parse_and_validate(response)
                    nota_valida, nota_data, missing_fields = _post_process(nota_valida, xml_text, modelo_fallback)
            else:
                paginas_total, img_b64, render_ms, encode_ms, image_bytes_len = _render_and_encode(render_scale, jpeg_quality)
                if paginas_total is None:
                    paginas_total = None

                try:
                    response, openai_retries, openai_error, openai_ms = _call_openai_image(modelo_ia, prompt, img_b64)
                    nota_valida, parse_ms, validate_ms = _parse_and_validate(response)
                    nota_valida, nota_data, missing_fields = _post_process(nota_valida, None, modelo_ia)
                    if _critical_invalid(nota_data):
                        raise ValueError("Extracao insuficiente.")
                except Exception:
                    fallback_usado = True
                    modelo_usado = modelo_fallback
                    response, openai_retries, openai_error, openai_ms = _call_openai_image(modelo_fallback, prompt, img_b64)
                    nota_valida, parse_ms, validate_ms = _parse_and_validate(response)
                    nota_valida, nota_data, missing_fields = _post_process(nota_valida, None, modelo_fallback)

                texto = _get_pdf_text()
                if texto:
                    text_fallback_used = True
                    nota_valida, nota_data, missing_fields = _post_process(nota_valida, texto, modelo_usado)

                if missing_fields and ocr_enabled:
                    ocr_text, ocr_ms, ocr_error = _get_ocr_text(max(render_scale, 2.8))
                    ocr_text_len = len(ocr_text)
                    if ocr_text:
                        ocr_used = True
                        nota_valida, nota_data, missing_fields = _post_process(nota_valida, ocr_text, modelo_usado)

        except Exception as exc:
            raise exc

        total_ms = int((time.perf_counter() - start_total) * 1000)
        telemetria = {
            "modelo_ia": modelo_usado,
            "modelo_fallback": modelo_fallback,
            "fallback_usado": fallback_usado,
            "origem_arquivo": "xml" if ext == ".xml" else "pdf",
            "paginas_total": paginas_total,
            "paginas_processadas": 1 if ext != ".xml" else None,
            "processamento_ms": total_ms,
            "render_ms": render_ms,
            "encode_ms": encode_ms,
            "openai_ms": openai_ms,
            "openai_retries": openai_retries,
            "openai_error": openai_error,
            "text_fallback_used": text_fallback_used,
            "ocr_used": ocr_used,
            "ocr_error": ocr_error,
            "ocr_ms": ocr_ms,
            "ocr_text_len": ocr_text_len,
            "parse_ms": parse_ms,
            "validate_ms": validate_ms,
            "image_format": image_format,
            "render_scale": render_scale,
            "image_bytes": image_bytes_len,
            "high_volume": high_volume,
        }

        return nota_valida.model_dump(), telemetria
    finally:
        pass
