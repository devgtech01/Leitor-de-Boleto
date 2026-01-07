from app.schemas.boleto import BoletoSchema

def calcular_confidencia(dados: BoletoSchema) -> float:
    campos = [
        dados.codigo_barras,
        dados.beneficiario,
        str(dados.valor) if dados.valor else None,
        dados.vencimento,
    ]

    preenchidos = sum(1 for c in campos if c)
    return round(preenchidos / len(campos), 2)
