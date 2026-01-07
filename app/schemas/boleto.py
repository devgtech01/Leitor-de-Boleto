from pydantic import BaseModel
from typing import Optional


class BoletoSchema(BaseModel):
    banco: Optional[str] = None
    linha_digitavel: Optional[str] = None
    codigo_barras: Optional[str] = None
    valor: Optional[float] = None
    vencimento: Optional[str] = None
    beneficiario: Optional[str] = None
    confidence_score: Optional[float] = None
