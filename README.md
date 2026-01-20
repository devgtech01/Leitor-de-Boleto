# 📑 Leitor de Boletos & Notas Fiscais IA (SaaS)

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![OpenAI](https://img.shields.io/badge/GPT--4o--Mini-412991?style=for-the-badge&logo=openai&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-07405E?style=for-the-badge&logo=sqlite&logoColor=white)

Uma solução SaaS completa desenvolvida com **FastAPI** que utiliza Inteligência Artificial e Visão Computacional para extrair dados estruturados de documentos fiscais e bancários com alta precisão.

---

## 🎯 O que a aplicação faz?

* **Processamento Inteligente:** Upload de Boletos (PDF) e Notas Fiscais (PDF/XML).
* **Extração de Dados:** Uso de GPT-4o-mini para converter documentos não estruturados em JSON.
* **Gestão de Créditos:** Sistema de planos (Trial, Básico, Profissional, Escritório) com renovação mensal automática.
* **Dashboard Completo:** Histórico detalhado, visualização de JSON em modais e exportação de dados.
* **Exportação Multiformato:** Download de resultados em **CSV**, **Excel (XLSX)** ou integração via **JSON**.
* **Painel Administrativo:** Gestão de usuários, aprovação de planos, telemetria de processamento e controle de créditos.

---

## 📊 Estrutura de Extração

### 🏦 Boletos Bancários
Extração validada via `app/schemas/boleto.py`:
* Banco, Linha Digitável e Código de Barras.
* Valor, Data de Vencimento e Beneficiário.
* **Confidence Score:** Score baseado na integridade do preenchimento dos campos.

### 🧾 Notas Fiscais (NFe, NFCe, NFSe)
Extração validada via `app/schemas/nota_fiscal.py`:
* Chave de acesso (44 dígitos), Série e Número.
* Dados completos de Emitente e Destinatário.
* Itens detalhados (NCM, Qtd, Valor Unitário).
* Impostos (ICMS, IPI, PIS, COFINS, ISS Retido).

---

## 💳 Sistema de Planos

| Plano | Créditos / Mês | Perfil Recomendado |
| :--- | :--- | :--- |
| **Trial** | 10 | Testes e demonstração |
| **Básico** | 2.000 | Uso pessoal ou MEI |
| **Profissional** | 6.000 | Pequenas empresas |
| **Escritório** | 12.000 | Contabilidades e alto volume |

> 💡 **Regra de Consumo:** 1 documento processado com sucesso = 1 crédito consumido. Admins possuem uso ilimitado.

---

## 🛠️ Tecnologias Utilizadas

* **Core:** [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn.
* **Frontend:** [Jinja2](https://jinja.palletsprojects.com/) + [Bootstrap 5](https://getbootstrap.com/).
* **IA & Visão:** [OpenAI API](https://platform.openai.com/) (Vision) + [PyMuPDF](https://pymupdf.readthedocs.io/) + [Tesseract OCR](https://github.com/tesseract-ocr/tesseract).
* **Dados:** [SQLAlchemy](https://www.sqlalchemy.org/) + [Pandas](https://pandas.pydata.org/) (Exportação).
* **Segurança:** JWT (python-jose) + Cookies HTTPOnly + Passlib (PBKDF2).

---

## 🚀 Como Executar Localmente

### 1. Requisitos
* Python 3.11 ou superior.
* Tesseract OCR instalado (necessário para a funcionalidade de reforço de leitura).

### 2. Instalação
```powershell
# Clonar o repositório e entrar na pasta
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt