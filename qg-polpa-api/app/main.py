import os
from datetime import datetime, timedelta, timezone
import jwt
import secrets
import bcrypt
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


from app.database import (
    list_database_tables,
    test_database_connection,
    list_table_columns,
    list_users,
    update_user,
    create_user,
    reset_user_password,
)

from app.database import (
    list_database_tables,
    test_database_connection,
    list_table_columns,
    list_users,
    update_user,
    create_user,
    reset_user_password,
    get_user_by_email,
    get_user_by_id,
    update_last_signed_in,
    update_password,
)


app = FastAPI(
    title="QG Polpa Brasil API",
    description="API RESTful para integração do QG Polpa Brasil com SQL Server.",
    version="0.1.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://qg-polpa-brasil.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COOKIE_NAME = "qg_session"
COOKIE_SECRET = os.getenv("COOKIE_SECRET", "qgpolpabrasil_dev_secret")
COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60


class AuthLoginRequest(BaseModel):
    email: str = Field(min_length=5)
    password: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    newPassword: str = Field(min_length=6)

class UserUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2)
    role: str | None = None
    ativo: bool | None = None

class UserCreateRequest(BaseModel):
    name: str = Field(min_length=2)
    email: str = Field(min_length=5)
    role: str

def serialize_auth_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "mustChangePassword": user["must_change_password"],
    }


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(
        password.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


def create_session_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "userId": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=365)).timestamp()),
    }
    return jwt.encode(payload, COOKIE_SECRET, algorithm="HS256")


def get_current_user_from_request(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    try:
        payload = jwt.decode(token, COOKIE_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None

    user_id = payload.get("userId")
    if not user_id:
        return None

    user = get_user_by_id(int(user_id))
    if not user or not user["ativo"]:
        return None

    update_last_signed_in(user["id"])
    return user


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=True,
        samesite="none",
    )


def generate_random_password(length: int = 10) -> str:
    chars = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(chars) for _ in range(length))


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


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


@app.patch("/api/users/{user_id}", tags=["Usuários"])
def patch_user(user_id: int, payload: UserUpdateRequest):
    try:
        if payload.role is not None and payload.role not in ["ADMIN", "VENDEDOR"]:
            raise HTTPException(
                status_code=400,
                detail="Perfil inválido. Use ADMIN ou VENDEDOR.",
            )

        update_user(
            user_id=user_id,
            name=payload.name,
            role=payload.role,
            ativo=payload.ativo,
        )

        return {
            "status": "ok",
            "message": "Usuário atualizado com sucesso.",
        }

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao atualizar usuário: {error}",
        )


@app.post("/api/users", tags=["Usuários"])
def post_user(payload: UserCreateRequest):
    try:
        if payload.role not in ["ADMIN", "VENDEDOR"]:
            raise HTTPException(
                status_code=400,
                detail="Perfil inválido. Use ADMIN ou VENDEDOR.",
            )

        temp_password = generate_random_password()
        password_hash = hash_password(temp_password)

        user_id = create_user(
            name=payload.name,
            email=payload.email,
            password_hash=password_hash,
            role=payload.role,
        )

        return {
            "status": "ok",
            "id": user_id,
            "tempPassword": temp_password,
        }

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao criar usuário: {error}",
        )

@app.post("/api/users/{user_id}/reset-password", tags=["Usuários"])
def post_reset_user_password(user_id: int):
    try:
        temp_password = generate_random_password()
        password_hash = hash_password(temp_password)

        reset_user_password(
            user_id=user_id,
            password_hash=password_hash,
        )

        return {
            "status": "ok",
            "tempPassword": temp_password,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao resetar senha do usuário: {error}",
        )


@app.get("/api/auth/me", tags=["Autenticação"])
def auth_me(request: Request):
    user = get_current_user_from_request(request)
    if not user:
        return None

    return serialize_auth_user(user)


@app.post("/api/auth/login", tags=["Autenticação"])
def auth_login(payload: AuthLoginRequest, response: Response):
    try:
        user = get_user_by_email(payload.email)

        if not user or not user["ativo"]:
            raise HTTPException(status_code=401, detail="Email ou senha inválidos")

        if not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Email ou senha inválidos")

        token = create_session_token(user["id"], user["role"])
        set_session_cookie(response, token)
        update_last_signed_in(user["id"])

        return serialize_auth_user(user)

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao autenticar usuário: {error}",
        )


@app.post("/api/auth/logout", tags=["Autenticação"])
def auth_logout(response: Response):
    clear_session_cookie(response)
    return {"success": True}


@app.post("/api/auth/change-password", tags=["Autenticação"])
def auth_change_password(payload: ChangePasswordRequest, request: Request):
    try:
        user = get_current_user_from_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Não autenticado")

        new_password_hash = hash_password(payload.newPassword)
        update_password(user["id"], new_password_hash)

        return {"success": True}

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao alterar senha: {error}",
        )