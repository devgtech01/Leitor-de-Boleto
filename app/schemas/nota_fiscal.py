from pydantic import BaseModel
from typing import Optional, List


class NotaFiscalItem(BaseModel):
    descricao: Optional[str] = None
    codigo_produto: Optional[str] = None
    ncm: Optional[str] = None
    quantidade: Optional[float] = None
    unidade: Optional[str] = None
    valor_unitario: Optional[float] = None
    valor_total_item: Optional[float] = None


class NotaFiscalPagamento(BaseModel):
    linha_digitavel: Optional[str] = None
    codigo_barras: Optional[str] = None
    vencimentos_parcelas: Optional[List[str]] = None


class NotaFiscalDadosBancarios(BaseModel):
    banco: Optional[str] = None
    agencia: Optional[str] = None
    conta: Optional[str] = None


class NotaFiscalSchema(BaseModel):
    tipo_documento: Optional[str] = None
    chave_acesso: Optional[str] = None
    numero: Optional[str] = None
    serie: Optional[str] = None
    data_emissao: Optional[str] = None
    tipo_operacao: Optional[str] = None
    emitente_cnpj_cpf: Optional[str] = None
    emitente_razao_social: Optional[str] = None
    emitente_inscricao_estadual: Optional[str] = None
    emitente_endereco: Optional[str] = None
    destinatario_cnpj_cpf: Optional[str] = None
    destinatario_razao_social: Optional[str] = None
    destinatario_inscricao_estadual: Optional[str] = None
    destinatario_endereco: Optional[str] = None
    itens: Optional[List[NotaFiscalItem]] = None
    valor_total_nota: Optional[float] = None
    base_calculo_icms: Optional[float] = None
    valor_icms: Optional[float] = None
    valor_ipi: Optional[float] = None
    valor_pis: Optional[float] = None
    valor_cofins: Optional[float] = None
    valor_frete: Optional[float] = None
    valor_seguro: Optional[float] = None
    pagamento: Optional[NotaFiscalPagamento] = None
    dados_bancarios: Optional[NotaFiscalDadosBancarios] = None
    iss_retido: Optional[float] = None
