# Leitor de Boletos IA (SaaS)

Aplicação web (SaaS) em **FastAPI** para extrair dados de **boletos bancários brasileiros** a partir de PDFs usando **visão + IA (OpenAI GPT-4o-mini)**, com autenticação, planos/créditos, dashboard e painel admin.

## O que a aplicação faz

- Upload de **1 ou vários PDFs** de boleto e extração dos campos via IA.
- Exibição do resultado na tela (JSON) ou exportação em **CSV** e **Excel (XLSX)**.
- Armazena histórico por usuário em **SQLite** (`app.db`) e permite consultar/excluir.
- Controle de acesso por login (cookie HTTPOnly) e **admin** com painel.
- Sistema de **planos + créditos** (renovação automática mensal por plano).

## Campos extraídos (modelo)

O modelo retornado pela IA é validado via Pydantic (`app/schemas/boleto.py`) e inclui:

- `banco`
- `linha_digitavel` (apenas números)
- `codigo_barras` (apenas números)
- `valor` (float)
- `vencimento` (YYYY-MM-DD)
- `beneficiario`
- `confidence_score` (score simples baseado no preenchimento dos campos)

## Telas / fluxos

- **Cadastro**: `/auth/signup-page` (cria usuário com 10 créditos e plano `trial`).
- **Login**: `/auth/login-page` (gera JWT e salva em cookie `access_token`).
- **Leitor (home)**: `/` (upload múltiplo + escolher formato de saída).
- **Dashboard**: `/dashboard` (histórico do usuário + detalhes JSON em modal + excluir + exportar Excel).
- **Planos**: `/planos` (usuário solicita plano; fica pendente até admin aprovar).
- **Admin**: `/admin` (lista usuários, aplica plano, aprova pendentes, adiciona créditos e vê telemetria do histórico global).

## Planos e créditos

Planos definidos em `app/users/plans.py`:

- `trial`: 10 créditos/mês
- `basico`: 2000 créditos/mês
- `profissional`: 6000 créditos/mês
- `escritorio`: 12000 créditos/mês

Regras:

- Cada boleto processado com sucesso consome **1 crédito** (admin não tem limite).
- A renovação de créditos ocorre automaticamente quando o usuário faz uma requisição autenticada e a data `creditos_renovam_em` expirou.
- A escolha de plano pelo usuário cria uma solicitação pendente (`plano_pendente`) para aprovação no painel admin.

## Exportações

- **JSON**: mostra o resultado na própria tela do leitor.
- **CSV**: download com separador `;` e encoding `utf-8-sig`.
- **Excel**: download de `.xlsx` com `openpyxl`.
- **Dashboard Excel**: `/dashboard/export/excel` exporta o histórico do usuário.

## Telemetria (admin)

Cada processamento grava telemetria básica em `boleto_history` (tempo total e etapas como render/encode/openai/parse/validate, além de páginas processadas). O painel admin exibe essa telemetria nos últimos 100 itens.

## Tecnologias

- Backend: **FastAPI** + **Uvicorn**
- Templates: **Jinja2** + **Bootstrap 5**
- Banco: **SQLite** + **SQLAlchemy**
- IA: **OpenAI API** (chat completions com `response_format=json_object` + imagem base64)
- PDF -> imagem: **PyMuPDF (fitz)** (dispensa Poppler)
- Exportação: **pandas** + **openpyxl**
- Auth: **python-jose** (JWT) + **passlib** (hash `pbkdf2_sha256`)

## Como rodar localmente

### 1) Requisitos

- Python 3.11+

### 2) Instalação (Windows PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3) Variáveis de ambiente

Crie `app/.env` a partir de `app/.env.example` e preencha:

- `OPENAI_API_KEY` (obrigatória)
- `SECRET_KEY` (opcional; recomendado para produção)

O processamento de imagem também aceita (opcionais):

- `BOLETO_IMAGE_FORMAT` (`jpeg` ou `png`, padrão: `jpeg`)
- `BOLETO_RENDER_SCALE` (padrão: `2.0`)
- `BOLETO_JPEG_QUALITY` (padrão: `70`, entre 30 e 95)

Importante: não versione sua chave em `app/.env` (mantenha apenas em ambiente local/segredo).

### 4) Subir o servidor

Execute a partir da raiz do repositório:

```powershell
uvicorn app.main:app --reload
```

A aplicação cria/atualiza o banco `app.db` automaticamente na inicialização.

## Como criar um admin

1) Cadastre um usuário pela UI.
2) Rode:

```powershell
python make_admin.py seu@email.com
```

Depois disso, o usuário verá o menu **Admin** e terá acesso ao painel em `/admin`.

## Principais rotas (resumo)

- Autenticação: `GET /auth/login-page`, `POST /auth/login`, `GET /auth/signup-page`, `POST /auth/signup`
- Leitor: `GET /`, `POST /upload`
- Dashboard: `GET /dashboard`, `GET /detalhes/{id}`, `POST /excluir/{id}`, `GET /dashboard/export/excel`
- Planos: `GET /planos`, `POST /planos/escolher`
- Admin: `GET /admin`, `GET /admin/detalhes/{id}`, `POST /admin/users/{user_id}/plan`, `POST /admin/users/{user_id}/plan/approve-pending`, `POST /admin/users/{user_id}/credits`
