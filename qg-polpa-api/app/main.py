from fastapi import FastAPI

app = FastAPI (
    title="QG Polpa Brasil API", 
    description="API RESTful para integração do QG Polpa Brasil com SQL Servr.",
    version="0.1.0",
)


@app.get("/")
def root():
    return {
        "message": "QG Polpa Brasil API", 
        "status": "online",
    }

@app.get("/api/health")
def health_check():
    return {
        "status": "ok", 
        "service": "qg-polpa-api",
    }