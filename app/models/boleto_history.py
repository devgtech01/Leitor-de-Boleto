from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta, timezone
from app.database import Base

class BoletoHistory(Base):
    __tablename__ = "boleto_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id")) # Vincula ao dono do boleto
    filename = Column(String)
    banco = Column(String)
    valor = Column(Float)
    vencimento = Column(String)
    linha_digitavel = Column(String)
    dados_completos = Column(JSON) # Salva o JSON inteiro da OpenAI
    data_processamento = Column(DateTime, default=datetime.utcnow)
    tipo_documento = Column(String, default="boleto")

    # Telemetria básica
    sucesso = Column(Boolean, default=True, nullable=False)
    erro = Column(String, nullable=True)
    modelo_ia = Column(String, nullable=True)
    paginas_total = Column(Integer, nullable=True)
    paginas_processadas = Column(Integer, nullable=True)
    processamento_ms = Column(Integer, nullable=True)
    telemetria = Column(JSON, nullable=True)

    # Relacionamento: Um usuário tem muitos históricos
    owner = relationship("User", back_populates="boletos")

    @property
    def data_processamento_br(self):
        if not self.data_processamento:
            return None
        dt = self.data_processamento
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=-3)))
