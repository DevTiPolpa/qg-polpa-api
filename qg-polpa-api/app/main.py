from fastapi import FastAPI, HTTPException

from app.database import list_database_tables, test_database_connection, list_table_columns, list_users


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
    


@app.get("/api/debug/users/columns", tags=["Debug"])
def debug_users_columns():
    try:
        columns = list_table_columns("users")

        return {
            "status": "ok",
            "table": "dbo.users",
            "count": len(columns),
            "columns": columns,
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar colunas da tabela users: {error}",
        )
    

@app.get("/api/users", tags=["Usuários"])    
def get_users(limit: int = 50):
    try:
        if limit < 1:
            limit = 1

        if limit > 100:
            limit = 100

        users = list_users(limit=limit)      


        return {
            "status": "ok", 
            "count": len(users),
            "users": users,
        } 
    
    except Exception as error:
        raise HTTPException(
            status_code=500, 
            detail=f"Erro ao listar usuários: {error}",
        )



