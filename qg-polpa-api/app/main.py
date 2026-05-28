from fastapi import FastAPI, HTTPException

from app.database import list_database_tables, test_database_connection


app = FastAPI(
    title="QG Polpa Brasil API",
    description="API RESTful para integração do QG Polpa Brasil com SQL Server.",
    version="0.1.0",
)


@app.get("/", tags=["Sistema"])
def root():
    return {
        "message": "QG Polpa Brasil API",
        "status": "online",
    }


@app.get("/api/health", tags=["Sistema"])
def health_check():
    return {
        "status": "ok",
        "service": "qg-polpa-api",
    }


@app.get("/api/database/health", tags=["Banco de Dados"])
def database_health_check():
    try:
        database_info = test_database_connection()

        return {
            "status": "ok",
            "database": database_info,
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao conectar no SQL Server: {error}",
        )
    

@app.get("/api/debug/tables", tags=["Debug"])
def debug_list_tables():
    try:
        tables = list_database_tables()

        return {
            "status": "ok",
            "count": len(tables),
            "tables": tables,
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar tabelas do SQL Server: {error}",
        )

