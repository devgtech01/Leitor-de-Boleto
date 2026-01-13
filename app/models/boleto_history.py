from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
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
