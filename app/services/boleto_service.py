import os
import base64
import json
import re
import random
import fitz  # Import do PyMuPDF
import time
from datetime import date, timedelta
import io
from openai import OpenAI
from app.schemas.boleto import BoletoSchema
from app.utils.confidence import calcular_confidencia

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def processar_boleto(caminho_pdf: str, high_volume: bool = False) -> tuple[dict, dict]:
    start_total = time.perf_counter()
    
    paginas_total = None
    modelo_ia = os.getenv("BOLETO_PRIMARY_MODEL", "gpt-4o-mini").strip()
    modelo_fallback = os.getenv("BOLETO_FALLBACK_MODEL", "gpt-4o").strip()
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
    min_confidence_raw = os.getenv("BOLETO_MIN_CONFIDENCE", "0.6").strip()
    adaptive_render_scale_raw = os.getenv("BOLETO_ADAPTIVE_RENDER_SCALE", "2.6").strip()
    adaptive_jpeg_quality_raw = os.getenv("BOLETO_ADAPTIVE_JPEG_QUALITY", "82").strip()
    barcode_render_scale_raw = os.getenv("BOLETO_BARCODE_RENDER_SCALE", "3.0").strip()
    barcode_jpeg_quality_raw = os.getenv("BOLETO_BARCODE_JPEG_QUALITY", "90").strip()
    barcode_crop_ratio_raw = os.getenv("BOLETO_BARCODE_CROP_RATIO", "0.35").strip()
    ocr_enabled_raw = os.getenv("BOLETO_ENABLE_OCR", "1").strip()
    ocr_psm_raw = os.getenv("BOLETO_OCR_PSM", "6").strip()
    ocr_lang_raw = os.getenv("BOLETO_OCR_LANG", "eng").strip()
    tesseract_cmd = os.getenv("BOLETO_TESSERACT_CMD", "").strip()
    due_date_strategy = os.getenv("BOLETO_DUE_DATE_STRATEGY", "closest").strip().lower()

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

        try:
            min_confidence = float(min_confidence_raw)
        except Exception:
            min_confidence = 0.6

        try:
            adaptive_render_scale = float(adaptive_render_scale_raw)
        except Exception:
            adaptive_render_scale = 2.6

        try:
            adaptive_jpeg_quality = int(adaptive_jpeg_quality_raw)
        except Exception:
            adaptive_jpeg_quality = 82
        adaptive_jpeg_quality = max(30, min(95, adaptive_jpeg_quality))

        try:
            barcode_render_scale = float(barcode_render_scale_raw)
        except Exception:
            barcode_render_scale = 3.0

        try:
            barcode_jpeg_quality = int(barcode_jpeg_quality_raw)
        except Exception:
            barcode_jpeg_quality = 90
        barcode_jpeg_quality = max(30, min(95, barcode_jpeg_quality))

        try:
            barcode_crop_ratio = float(barcode_crop_ratio_raw)
        except Exception:
            barcode_crop_ratio = 0.35
        barcode_crop_ratio = max(0.2, min(0.6, barcode_crop_ratio))

        ocr_enabled = ocr_enabled_raw not in ("0", "false", "no")
        try:
            ocr_psm = int(ocr_psm_raw)
        except Exception:
            ocr_psm = 6
        ocr_lang = ocr_lang_raw or "eng"

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

        def _render_and_encode(scale: float, quality: int):
            t0_render = time.perf_counter()
            doc = fitz.open(caminho_pdf)
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

        def _render_and_encode_crop(scale: float, quality: int, crop_ratio: float):
            t0_render = time.perf_counter()
            doc = fitz.open(caminho_pdf)
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
            width, height = image.size
            top = int(height * (1 - crop_ratio))
            cropped = image.crop((0, top, width, height))
            buf = io.BytesIO()
            if image_format == "jpeg":
                cropped.save(buf, format="JPEG", quality=quality, optimize=True)
            else:
                cropped.save(buf, format="PNG", optimize=True)
            image_bytes = buf.getvalue()
            img_b64_local = base64.b64encode(image_bytes).decode("utf-8")
            encode_elapsed = int((time.perf_counter() - t0_encode) * 1000)
            return paginas, img_b64_local, render_elapsed, encode_elapsed, len(image_bytes)

        def _render_crop_image(scale: float, crop_ratio: float):
            t0_render = time.perf_counter()
            doc = fitz.open(caminho_pdf)
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
            width, height = image.size
            top = int(height * (1 - crop_ratio))
            cropped = image.crop((0, top, width, height))
            return paginas, cropped, render_elapsed

        # 1. Converter PDF para imagem usando PyMuPDF (Sem Poppler!)
        paginas_total, img_b64, render_ms, encode_ms, image_bytes_len = _render_and_encode(render_scale, jpeg_quality)
        if paginas_total is None:
            paginas_total = None

        # 3. Prompt para a IA
        prompt = """
        Você é um especialista em boletos brasileiros. Extraia os dados deste boleto e retorne um JSON contendo os campos:
        - banco (nome do banco)
        - linha_digitavel (apenas numeros)
        - codigo_barras (apenas numeros)
        - valor (float)
        - vencimento (YYYY-MM-DD)
        - beneficiario (nome da empresa)
        """

        prompt_adapt = """
        Revise o boleto com mais precisao e retorne somente o JSON com os campos:
        - banco (nome do banco)
        - linha_digitavel (apenas numeros)
        - codigo_barras (apenas numeros)
        - valor (float)
        - vencimento (YYYY-MM-DD)
        - beneficiario (nome da empresa)
        """

        prompt_barcode = """
        Extraia somente os numeros da linha_digitavel e do codigo_barras.
        Retorne um JSON com:
        - linha_digitavel
        - codigo_barras
        """

        def _call_openai(model_name: str, prompt_text: str, img_data: str):
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
                                    {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{img_data}"}}
                                ]
                            }
                        ],
                        response_format={"type": "json_object"}
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
            boleto_valido = BoletoSchema(**dados_extraidos)
            boleto_valido.confidence_score = calcular_confidencia(boleto_valido)
            validate_elapsed = int((time.perf_counter() - t0_validate) * 1000)
            return boleto_valido, parse_elapsed, validate_elapsed

        def _is_digits(value: str | None) -> bool:
            return bool(value) and value.isdigit()

        def _critical_invalid(boleto_obj: BoletoSchema) -> bool:
            linha = _clean_digits(boleto_obj.linha_digitavel)
            barras = _clean_digits(boleto_obj.codigo_barras)
            valor = boleto_obj.valor
            venc = boleto_obj.vencimento or ""
            if not _is_valid_linha(linha) and not _is_valid_barcode(barras):
                return True
            if valor is None or valor <= 0:
                return True
            if len(venc) < 8:
                return True
            return False

        def _clean_digits(value: str | None) -> str:
            if not value:
                return ""
            return "".join(ch for ch in value if ch.isdigit())

        def _parse_factor_and_value(linha: str | None, barras: str | None):
            barras_digits = _clean_digits(barras)
            if len(barras_digits) == 44:
                factor = barras_digits[5:9]
                value_digits = barras_digits[9:19]
                return factor, value_digits
            linha_digits = _clean_digits(linha)
            if len(linha_digits) == 47:
                factor = linha_digits[33:37]
                value_digits = linha_digits[37:47]
                return factor, value_digits
            return None, None

        def _factor_to_date(factor: str | None) -> str | None:
            if not factor or not factor.isdigit() or len(factor) != 4:
                return None
            if factor == "0000":
                return None
            days = int(factor)
            base_old = date(1997, 10, 7)
            base_new = date(2025, 2, 22)
            date_old = base_old + timedelta(days=days)
            date_new = None
            if days >= 1000:
                date_new = base_new + timedelta(days=days - 1000)

            if due_date_strategy == "old":
                return date_old.isoformat()
            if due_date_strategy == "new" and date_new is not None:
                return date_new.isoformat()

            if date_new is None:
                return date_old.isoformat()

            today = date.today()
            if abs((date_new - today).days) < abs((date_old - today).days):
                return date_new.isoformat()
            return date_old.isoformat()

        def _value_from_digits(value_digits: str | None) -> float | None:
            if not value_digits or not value_digits.isdigit():
                return None
            try:
                return int(value_digits) / 100.0
            except Exception:
                return None

        def _mod10(num: str) -> int:
            total = 0
            factor = 2
            for ch in reversed(num):
                add = int(ch) * factor
                if add > 9:
                    add -= 9
                total += add
                factor = 1 if factor == 2 else 2
            return (10 - (total % 10)) % 10

        def _mod11_barcode(num: str) -> int:
            total = 0
            weight = 2
            for ch in reversed(num):
                total += int(ch) * weight
                weight += 1
                if weight > 9:
                    weight = 2
            remainder = total % 11
            dv = 11 - remainder
            if dv in (0, 10, 11):
                dv = 1
            return dv

        def _linha_to_barcode(linha: str) -> str | None:
            if len(linha) != 47 or not linha.isdigit():
                return None
            return (
                linha[:4]
                + linha[32]
                + linha[33:47]
                + linha[4:9]
                + linha[10:20]
                + linha[21:31]
            )

        def _barcode_to_linha(barras: str) -> str | None:
            if len(barras) != 44 or not barras.isdigit():
                return None
            bank_curr = barras[:4]
            dv = barras[4]
            factor_value = barras[5:19]
            free = barras[19:]
            campo1 = bank_curr + free[:5]
            campo2 = free[5:15]
            campo3 = free[15:25]
            return (
                campo1
                + str(_mod10(campo1))
                + campo2
                + str(_mod10(campo2))
                + campo3
                + str(_mod10(campo3))
                + dv
                + factor_value
            )

        def _is_valid_barcode(barras: str) -> bool:
            if len(barras) != 44 or not barras.isdigit():
                return False
            dv = int(barras[4])
            computed = _mod11_barcode(barras[:4] + barras[5:])
            return dv == computed

        def _is_valid_linha(linha: str) -> bool:
            if len(linha) != 47 or not linha.isdigit():
                return False
            if _mod10(linha[:9]) != int(linha[9]):
                return False
            if _mod10(linha[10:20]) != int(linha[20]):
                return False
            if _mod10(linha[21:31]) != int(linha[31]):
                return False
            barcode = _linha_to_barcode(linha)
            if not barcode:
                return False
            return _is_valid_barcode(barcode)

        def _extract_candidates_from_text(text: str) -> list[str]:
            if not text:
                return []
            candidates = []
            for match in re.finditer(r"(?:\\d[\\d\\.\\s-]{40,100}\\d)", text):
                cleaned = _clean_digits(match.group())
                if len(cleaned) in (44, 47, 48):
                    candidates.append(cleaned)
            for match in re.finditer(r"\\d{44,48}", text):
                if len(match.group()) in (44, 47, 48):
                    candidates.append(match.group())
            unique = []
            seen = set()
            for candidate in candidates:
                if candidate not in seen:
                    seen.add(candidate)
                    unique.append(candidate)
            return unique

        def _get_pdf_text() -> str:
            if text_cache["value"] is not None:
                return text_cache["value"]
            doc = fitz.open(caminho_pdf)
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

        def _pick_best_candidate(candidates: list[str]) -> tuple[str, str] | None:
            for candidate in candidates:
                if len(candidate) == 47 and _is_valid_linha(candidate):
                    return ("linha", candidate)
            for candidate in candidates:
                if len(candidate) == 44 and _is_valid_barcode(candidate):
                    return ("barcode", candidate)
            for candidate in candidates:
                if len(candidate) == 48:
                    return ("linha", candidate)
            return None

        def _apply_text_fallback(boleto_obj: BoletoSchema) -> bool:
            linha_digits = _clean_digits(boleto_obj.linha_digitavel)
            barras_digits = _clean_digits(boleto_obj.codigo_barras)
            linha_valid = _is_valid_linha(linha_digits)
            barras_valid = _is_valid_barcode(barras_digits)
            if linha_valid and barras_valid:
                return False

            text = _get_pdf_text()
            if not text:
                return False
            candidates = _extract_candidates_from_text(text)
            if not candidates:
                return False
            chosen = _pick_best_candidate(candidates)
            if not chosen:
                return False

            kind, value = chosen
            if kind == "linha":
                if not linha_valid:
                    boleto_obj.linha_digitavel = value
                if not barras_valid:
                    barcode = _linha_to_barcode(value)
                    if barcode:
                        boleto_obj.codigo_barras = barcode
            else:
                if not barras_valid:
                    boleto_obj.codigo_barras = value
                if not linha_valid:
                    linha = _barcode_to_linha(value)
                    if linha:
                        boleto_obj.linha_digitavel = linha
            return True

        def _apply_ocr_fallback(boleto_obj: BoletoSchema):
            if not ocr_enabled:
                return False, None, None, "disabled", None

            try:
                import pytesseract
            except Exception as exc:
                return False, None, None, str(exc), None

            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

            scale = max(render_scale, barcode_render_scale)
            crop_candidates = [barcode_crop_ratio, 0.45, 0.25]
            last_error = None
            last_crop = None
            text_len = None
            t0_ocr = time.perf_counter()

            for crop_ratio in crop_candidates:
                _, cropped, _ = _render_crop_image(scale, crop_ratio)
                gray = cropped.convert("L")
                bw = gray.point(lambda x: 0 if x < 160 else 255, "1")
                config = f"--oem 1 --psm {ocr_psm} -c tessedit_char_whitelist=0123456789"
                text = pytesseract.image_to_string(bw, config=config, lang=ocr_lang) or ""
                text_len = len(text)
                candidates = _extract_candidates_from_text(text)
                chosen = _pick_best_candidate(candidates)
                if chosen:
                    kind, value = chosen
                    if kind == "linha":
                        boleto_obj.linha_digitavel = value
                        barcode = _linha_to_barcode(value)
                        if barcode:
                            boleto_obj.codigo_barras = barcode
                    else:
                        boleto_obj.codigo_barras = value
                        linha = _barcode_to_linha(value)
                        if linha:
                            boleto_obj.linha_digitavel = linha
                    ocr_ms = int((time.perf_counter() - t0_ocr) * 1000)
                    return True, ocr_ms, text_len, None, crop_ratio

                last_error = "no_match"
                last_crop = crop_ratio

            ocr_ms = int((time.perf_counter() - t0_ocr) * 1000)
            return False, ocr_ms, text_len, last_error, last_crop

        def _apply_barcode_focus(boleto_obj: BoletoSchema):
            linha_digits = _clean_digits(boleto_obj.linha_digitavel)
            barras_digits = _clean_digits(boleto_obj.codigo_barras)
            if _is_valid_linha(linha_digits) or _is_valid_barcode(barras_digits):
                return False, None, None, None, None, None, None

            try:
                scale = max(render_scale, barcode_render_scale)
                quality = max(jpeg_quality, barcode_jpeg_quality)
                crop_candidates = [barcode_crop_ratio, 0.45, 0.25]
                used_crop = None
                last_error = None
                for crop_ratio in crop_candidates:
                    _, img_b64_crop, render_elapsed, encode_elapsed, image_bytes_len = _render_and_encode_crop(
                        scale, quality, crop_ratio
                    )
                    response, _, _, openai_elapsed = _call_openai(modelo_fallback, prompt_barcode, img_b64_crop)
                    data = json.loads(response.choices[0].message.content)
                    linha = _clean_digits(data.get("linha_digitavel"))
                    barras = _clean_digits(data.get("codigo_barras"))

                    if linha and _is_valid_linha(linha):
                        boleto_obj.linha_digitavel = linha
                        barcode = _linha_to_barcode(linha)
                        if barcode:
                            boleto_obj.codigo_barras = barcode
                        used_crop = crop_ratio
                        return True, render_elapsed, encode_elapsed, image_bytes_len, openai_elapsed, None, used_crop

                    if barras and _is_valid_barcode(barras):
                        boleto_obj.codigo_barras = barras
                        linha_calc = _barcode_to_linha(barras)
                        if linha_calc:
                            boleto_obj.linha_digitavel = linha_calc
                        used_crop = crop_ratio
                        return True, render_elapsed, encode_elapsed, image_bytes_len, openai_elapsed, None, used_crop

                    last_error = "invalid_checksum"

                return False, render_elapsed, encode_elapsed, image_bytes_len, openai_elapsed, last_error, used_crop
            except Exception as exc:
                return False, None, None, None, None, str(exc), None

        def _apply_barcode_corrections(boleto_obj: BoletoSchema):
            linha_digits = _clean_digits(boleto_obj.linha_digitavel)
            barras_digits = _clean_digits(boleto_obj.codigo_barras)
            barcode_source = None
            if _is_valid_barcode(barras_digits):
                barcode_source = barras_digits
            elif _is_valid_linha(linha_digits):
                barcode_source = _linha_to_barcode(linha_digits)

            if not barcode_source:
                return False, None, None

            factor = barcode_source[5:9]
            value_digits = barcode_source[9:19]
            computed_venc = _factor_to_date(factor)
            computed_valor = _value_from_digits(value_digits)
            changed = False

            if computed_venc and computed_venc != boleto_obj.vencimento:
                boleto_obj.vencimento = computed_venc
                changed = True

            if computed_valor is not None and boleto_obj.valor != computed_valor:
                boleto_obj.valor = computed_valor
                changed = True

            if changed:
                boleto_obj.confidence_score = calcular_confidencia(boleto_obj)

            return changed, computed_venc, computed_valor

        response = None
        openai_retries = 0
        openai_error = None
        openai_ms = None
        modelo_usado = modelo_ia
        fallback_usado = False
        vencimento_corrigido = False
        vencimento_derivado = None
        valor_corrigido = False
        valor_derivado = None
        text_fallback_used = False
        barcode_focus_used = False
        barcode_focus_error = None
        barcode_focus_render_ms = None
        barcode_focus_encode_ms = None
        barcode_focus_image_bytes = None
        barcode_focus_openai_ms = None
        barcode_focus_crop_ratio = None
        ocr_used = False
        ocr_error = None
        ocr_ms = None
        ocr_text_len = None
        ocr_crop_ratio = None

        try:
            response, openai_retries, openai_error, openai_ms = _call_openai(modelo_ia, prompt, img_b64)
            boleto_valido, parse_ms, validate_ms = _parse_and_validate(response)
            text_fallback_used = _apply_text_fallback(boleto_valido) or text_fallback_used
            changed, vencimento_derivado, valor_derivado = _apply_barcode_corrections(boleto_valido)
            vencimento_corrigido = bool(changed and vencimento_derivado)
            valor_corrigido = bool(changed and valor_derivado is not None)
            if boleto_valido.confidence_score is not None and boleto_valido.confidence_score < min_confidence:
                raise ValueError("Baixa confianca na extracao.")
        except Exception:
            fallback_usado = True
            modelo_usado = modelo_fallback
            response, openai_retries, openai_error, openai_ms = _call_openai(modelo_fallback, prompt, img_b64)
            boleto_valido, parse_ms, validate_ms = _parse_and_validate(response)
            text_fallback_used = _apply_text_fallback(boleto_valido) or text_fallback_used
            changed, vencimento_derivado, valor_derivado = _apply_barcode_corrections(boleto_valido)
            vencimento_corrigido = bool(changed and vencimento_derivado)
            valor_corrigido = bool(changed and valor_derivado is not None)

        adaptive_used = False
        adaptive_error = None
        adaptive_render_ms = None
        adaptive_encode_ms = None
        adaptive_image_bytes = None

        low_confidence = boleto_valido.confidence_score is not None and boleto_valido.confidence_score < min_confidence
        critical_invalid = _critical_invalid(boleto_valido)
        if low_confidence or critical_invalid:
            try:
                adaptive_used = True
                scale = max(render_scale, adaptive_render_scale)
                quality = max(jpeg_quality, adaptive_jpeg_quality)
                paginas_total, img_b64_adapt, adaptive_render_ms, adaptive_encode_ms, adaptive_image_bytes = _render_and_encode(scale, quality)
                response, openai_retries, openai_error, openai_ms = _call_openai(modelo_fallback, prompt_adapt, img_b64_adapt)
                boleto_valido, parse_ms, validate_ms = _parse_and_validate(response)
                text_fallback_used = _apply_text_fallback(boleto_valido) or text_fallback_used
                changed, vencimento_derivado, valor_derivado = _apply_barcode_corrections(boleto_valido)
                vencimento_corrigido = bool(changed and vencimento_derivado)
                valor_corrigido = bool(changed and valor_derivado is not None)
                modelo_usado = modelo_fallback
                fallback_usado = True
            except Exception as exc:
                adaptive_error = str(exc)

        linha_digits = _clean_digits(boleto_valido.linha_digitavel)
        barras_digits = _clean_digits(boleto_valido.codigo_barras)
        if not _is_valid_linha(linha_digits) and not _is_valid_barcode(barras_digits):
            (
                barcode_focus_used,
                barcode_focus_render_ms,
                barcode_focus_encode_ms,
                barcode_focus_image_bytes,
                barcode_focus_openai_ms,
                barcode_focus_error,
                barcode_focus_crop_ratio,
            ) = _apply_barcode_focus(boleto_valido)
            if barcode_focus_used:
                changed, vencimento_derivado, valor_derivado = _apply_barcode_corrections(boleto_valido)
                vencimento_corrigido = bool(changed and vencimento_derivado)
                valor_corrigido = bool(changed and valor_derivado is not None)

        linha_digits = _clean_digits(boleto_valido.linha_digitavel)
        barras_digits = _clean_digits(boleto_valido.codigo_barras)
        if not _is_valid_linha(linha_digits) and not _is_valid_barcode(barras_digits):
            ocr_used, ocr_ms, ocr_text_len, ocr_error, ocr_crop_ratio = _apply_ocr_fallback(boleto_valido)
            if ocr_used:
                changed, vencimento_derivado, valor_derivado = _apply_barcode_corrections(boleto_valido)
                vencimento_corrigido = bool(changed and vencimento_derivado)
                valor_corrigido = bool(changed and valor_derivado is not None)

        total_ms = int((time.perf_counter() - start_total) * 1000)
        telemetria = {
            "modelo_ia": modelo_usado,
            "modelo_fallback": modelo_fallback,
            "fallback_usado": fallback_usado,
            "paginas_total": paginas_total,
            "paginas_processadas": 1,
            "processamento_ms": total_ms,
            "render_ms": render_ms,
            "encode_ms": encode_ms,
            "openai_ms": openai_ms,
            "openai_retries": openai_retries,
            "openai_error": openai_error,
            "adaptive_used": adaptive_used,
            "adaptive_error": adaptive_error,
            "adaptive_render_ms": adaptive_render_ms,
            "adaptive_encode_ms": adaptive_encode_ms,
            "adaptive_image_bytes": adaptive_image_bytes,
            "text_fallback_used": text_fallback_used,
            "barcode_focus_used": barcode_focus_used,
            "barcode_focus_error": barcode_focus_error,
            "barcode_focus_render_ms": barcode_focus_render_ms,
            "barcode_focus_encode_ms": barcode_focus_encode_ms,
            "barcode_focus_image_bytes": barcode_focus_image_bytes,
            "barcode_focus_openai_ms": barcode_focus_openai_ms,
            "barcode_focus_crop_ratio": barcode_focus_crop_ratio,
            "ocr_used": ocr_used,
            "ocr_error": ocr_error,
            "ocr_ms": ocr_ms,
            "ocr_text_len": ocr_text_len,
            "ocr_crop_ratio": ocr_crop_ratio,
            "vencimento_corrigido": vencimento_corrigido,
            "vencimento_derivado": vencimento_derivado,
            "valor_corrigido": valor_corrigido,
            "valor_derivado": valor_derivado,
            "parse_ms": parse_ms,
            "validate_ms": validate_ms,
            "image_format": image_format,
            "render_scale": render_scale,
            "image_bytes": image_bytes_len,
            "high_volume": high_volume,
        }

        return boleto_valido.model_dump(), telemetria
    finally:
        # Sem arquivos temporários nessa versão
        pass
