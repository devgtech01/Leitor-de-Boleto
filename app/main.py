from app.database import engine, Base, ensure_boleto_history_telemetry_columns, ensure_users_admin_column
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends
from app.routes.boleto import router as boleto_router
from app.routes.nota_fiscal import router as nota_fiscal_router
from app.routes.admin import router as admin_router
from app.routes.plans import router as plans_router
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.auth.routes import router as auth_router
from app.auth.security import get_current_user

# Importante importar os modelos para que o Base.metadata os reconheça
from app.models.user import User
from app.models.boleto_history import BoletoHistory

app = FastAPI(title="Leitor de Boletos IA")


# --- ADICIONE ESTA LINHA AQUI ---
Base.metadata.create_all(bind=engine) 
# --------------------------------
ensure_users_admin_column()
ensure_boleto_history_telemetry_columns()

app.include_router(auth_router)
app.include_router(boleto_router)
app.include_router(nota_fiscal_router)
app.include_router(admin_router)
app.include_router(plans_router)

templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})
