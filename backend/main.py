from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import os
import pathlib

env_path = pathlib.Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)
print(f"[DEBUG] Loaded env from: {env_path}")

from app.services.pdf_font_utils import validate_translation_fonts

validate_translation_fonts()

from app.api.routes import router

app = FastAPI(title="LingoDoc API", version="1.0.0")

allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/")
async def root():
    return {"message": "PDF Translate API is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
