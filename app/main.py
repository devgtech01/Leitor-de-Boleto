from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from app.routes.boleto import router as boleto_router
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


app = FastAPI(title="Leitor de Boletos IA")

app.include_router(boleto_router)

templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})