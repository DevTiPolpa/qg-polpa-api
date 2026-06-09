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
    list_b2b_resumo,
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
    list_metas_2026, 
    upsert_meta_2026, 
    delete_meta_2026,
)


app = FastAPI(
    title="QG Polpa Brasil API",
    description="API RESTful para integração do QG Polpa Brasil com SQL Server.",
    version="0.1.0",
)


DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "https://qg-polpa-brasil.vercel.app",
]

EXTRA_ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if origin.strip()
]

ALLOWED_ORIGINS = sorted(set(DEFAULT_ALLOWED_ORIGINS + EXTRA_ALLOWED_ORIGINS))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^http://localhost:\d+$|^http://127\.0\.0\.1:\d+$|^https://.*\.vercel\.app$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

COOKIE_NAME = "qg_session"
COOKIE_SECRET = os.getenv("COOKIE_SECRET", "qgpolpabrasil_dev_secret")
COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "none" if COOKIE_SECURE else "lax")

class Meta2026UpsertRequest(BaseModel):
    nomeVendedor: str = Field(min_length=1)
    mes: str = Field(pattern=r"^\d{4}-\d{2}$")
    valorMeta: float = Field(ge=0)
    projeto: str | None = None
    mercadoVendas: str | None = None



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
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
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
    


@app.get("/api/metas", tags=["Metas"])
def get_metas(ano: str = "2026"):
    try:
        metas = list_metas_2026(ano=ano)
        return {
            "status": "ok",
            "count": len(metas),
            "metas": metas,
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar metas: {error}",
        )


@app.post("/api/metas", tags=["Metas"])
def post_meta(payload: Meta2026UpsertRequest):
    try:
        upsert_meta_2026(
            nome_vendedor=payload.nomeVendedor,
            mes=payload.mes,
            valor_meta=payload.valorMeta,
            projeto=payload.projeto,
            mercado_vendas=payload.mercadoVendas,
        )

        return {
            "status": "ok",
            "message": "Meta salva com sucesso.",
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao salvar meta: {error}",
        )


@app.delete("/api/metas/{meta_id}", tags=["Metas"])
def delete_meta(meta_id: int):
    try:
        delete_meta_2026(meta_id)

        return {
            "status": "ok",
            "message": "Meta excluída com sucesso.",
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao excluir meta: {error}",
        )
    

@app.get("/api/b2b/resumo", tags=["B2B"])
def get_b2b_resumo(ano: str = "2026"):
    if not ano.isdigit() or len(ano) != 4:
        raise HTTPException(
            status_code=400,
            detail="Ano inválido. Use o formato YYYY, por exemplo: 2026.",
        )

    try:
        resumo = list_b2b_resumo(ano=ano)
        return {
            "status": "ok",
            "count": len(resumo),
            "resumo": resumo,
        }
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar resumo da B2B: {error}",
        )


# =============================================================================
# Imports adicionais para Dashboard Executivo e Por Vendedor originais via REST
# =============================================================================

from fastapi import Query

from app.database import (
    get_vendedores_kpis_original,
    get_vendedores_original_resumo,
    get_orcamento_kpis_original,
    list_crm_kpis_por_vendedor_original,
    list_crm_mapping_vendedores_original,
    list_metas_vendedores_original,
    list_orcamento_mensal_original,
    list_vendedores_cliente_mix_original,
    list_vendedores_clientes_consolidados_original,
    list_vendedores_evolucao_original,
    list_vendedores_evolucao_por_tipo_original,
    list_vendedores_performance_original,
)

from app.database import (
    get_dashboard_original_filtros_disponiveis,
    get_dashboard_original_kpis,
    get_dashboard_original_kpis_ano_anterior,
    get_dashboard_original_orcamento_kpis,
    get_dashboard_original_resumo,
    list_dashboard_original_cliente_mix,
    list_dashboard_original_clientes_top,
    list_dashboard_original_drilldown,
    list_dashboard_original_evolucao_ano_anterior,
    list_dashboard_original_evolucao_mensal,
    list_dashboard_original_kpis_por_tipo,
    list_dashboard_original_orcamento_mensal,
    list_dashboard_original_projetos,
    list_dashboard_original_segmentos,
)



# =============================================================================
# Por Vendedor — endpoints originais migrados para REST
# =============================================================================

def _csv_or_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    result: list[str] = []
    for value in values:
        for item in str(value).split(","):
            item = item.strip()
            if item:
                result.append(item)
    return result


def _build_vendedores_filtros(
    dataInicio: str | None = None,
    dataFim: str | None = None,
    mercados: list[str] | None = None,
    vendedores: list[str] | None = None,
    projetos: list[str] | None = None,
    gruposProduto: list[str] | None = None,
    tiposReceita: list[str] | None = None,
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
) -> dict:
    return {
        "dataInicio": dataInicio or "2026-01-01",
        "dataFim": dataFim or "2026-12-31",
        "mercados": _csv_or_list(mercados),
        "vendedores": _csv_or_list(vendedores),
        "projetos": _csv_or_list(projetos),
        "gruposProduto": _csv_or_list(gruposProduto),
        "tiposReceita": _csv_or_list(tiposReceita),
        "uf": uf,
        "codParc": codParc,
        "codProduto": codProduto,
    }


@app.get("/api/vendedores-original/resumo")
def api_vendedores_original_resumo(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    limitClientes: int = Query(default=50, ge=1, le=500),
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return get_vendedores_original_resumo(filtros, limitClientes)


@app.get("/api/vendedores-original/kpis")
def api_vendedores_original_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return get_vendedores_kpis_original(filtros)


@app.get("/api/vendedores-original/performance")
def api_vendedores_original_performance(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return list_vendedores_performance_original(filtros)


@app.get("/api/vendedores-original/evolucao")
def api_vendedores_original_evolucao(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return list_vendedores_evolucao_original(filtros)


@app.get("/api/vendedores-original/evolucao-por-tipo")
def api_vendedores_original_evolucao_por_tipo(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, None, uf, codParc, codProduto
    )
    return list_vendedores_evolucao_por_tipo_original(filtros)


@app.get("/api/vendedores-original/clientes-consolidados")
def api_vendedores_original_clientes_consolidados(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    limit: int = Query(default=50, ge=1, le=500),
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return list_vendedores_clientes_consolidados_original(filtros, limit)


@app.get("/api/vendedores-original/metas")
def api_vendedores_original_metas(
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
):
    filtros = _build_vendedores_filtros(
        None, None, mercados, vendedores, projetos, None, None, None, None, None
    )
    return list_metas_vendedores_original(filtros)


@app.get("/api/vendedores-original/orcamento-kpis")
def api_vendedores_original_orcamento_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, None, projetos, gruposProduto, None, None, None, None
    )
    return get_orcamento_kpis_original(filtros)


@app.get("/api/vendedores-original/orcamento-mensal")
def api_vendedores_original_orcamento_mensal(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, None, projetos, gruposProduto, None, None, None, None
    )
    return list_orcamento_mensal_original(filtros)


@app.get("/api/vendedores-original/crm-mapping")
def api_vendedores_original_crm_mapping():
    return list_crm_mapping_vendedores_original()


@app.get("/api/vendedores-original/crm-kpis")
def api_vendedores_original_crm_kpis():
    return list_crm_kpis_por_vendedor_original()


# =============================================================================
# Por Vendedor — expansão lazy de produtos por cliente
# =============================================================================

@app.get("/api/vendedores-original/clientes/{cod_parc}/mix")
def api_vendedores_original_cliente_mix(
    cod_parc: int,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codProduto: int | None = None,
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, None, codProduto
    )
    return list_vendedores_cliente_mix_original(cod_parc, filtros)


# =============================================================================
# Dashboard Executivo — endpoints originais migrados para REST
# =============================================================================

def _csv_or_list_dashboard(values: list[str] | None) -> list[str]:
    if not values:
        return []
    result: list[str] = []
    for value in values:
        for item in str(value).split(","):
            item = item.strip()
            if item:
                result.append(item)
    return result


def _build_dashboard_filtros(
    dataInicio: str | None = None,
    dataFim: str | None = None,
    mercados: list[str] | None = None,
    vendedores: list[str] | None = None,
    projetos: list[str] | None = None,
    gruposProduto: list[str] | None = None,
    tiposReceita: list[str] | None = None,
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
) -> dict:
    return {
        "dataInicio": dataInicio or "2026-01-01",
        "dataFim": dataFim or "2026-12-31",
        "mercados": _csv_or_list_dashboard(mercados),
        "vendedores": _csv_or_list_dashboard(vendedores),
        "projetos": _csv_or_list_dashboard(projetos),
        "gruposProduto": _csv_or_list_dashboard(gruposProduto),
        "tiposReceita": _csv_or_list_dashboard(tiposReceita),
        "uf": uf,
        "codParc": codParc,
        "codProduto": codProduto,
    }


@app.get("/api/dashboard-original/resumo")
def api_dashboard_original_resumo(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    limitClientes: int | None = Query(default=None, ge=1, le=500),
):
    filtros = _build_dashboard_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return get_dashboard_original_resumo(filtros, limitClientes)


@app.get("/api/dashboard-original/kpis")
def api_dashboard_original_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_dashboard_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return get_dashboard_original_kpis(filtros)


@app.get("/api/dashboard-original/kpis-ano-anterior")
def api_dashboard_original_kpis_ano_anterior(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_dashboard_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return get_dashboard_original_kpis_ano_anterior(filtros)


@app.get("/api/dashboard-original/evolucao-mensal")
def api_dashboard_original_evolucao_mensal(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_dashboard_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return list_dashboard_original_evolucao_mensal(filtros)


@app.get("/api/dashboard-original/evolucao-ano-anterior")
def api_dashboard_original_evolucao_ano_anterior(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_dashboard_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return list_dashboard_original_evolucao_ano_anterior(filtros)


@app.get("/api/dashboard-original/kpis-por-tipo")
def api_dashboard_original_kpis_por_tipo(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_dashboard_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, None, uf, codParc, codProduto
    )
    return list_dashboard_original_kpis_por_tipo(filtros)


@app.get("/api/dashboard-original/orcamento-kpis")
def api_dashboard_original_orcamento_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, None, projetos, gruposProduto, None)
    return get_dashboard_original_orcamento_kpis(filtros)


@app.get("/api/dashboard-original/orcamento-mensal")
def api_dashboard_original_orcamento_mensal(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, None, projetos, gruposProduto, None)
    return list_dashboard_original_orcamento_mensal(filtros)


@app.get("/api/dashboard-original/segmentos")
def api_dashboard_original_segmentos(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita)
    return list_dashboard_original_segmentos(filtros)


@app.get("/api/dashboard-original/projetos")
def api_dashboard_original_projetos(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita)
    return list_dashboard_original_projetos(filtros)


@app.get("/api/dashboard-original/clientes-top")
def api_dashboard_original_clientes_top(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita)
    return list_dashboard_original_clientes_top(filtros, limit)


@app.get("/api/dashboard-original/drilldown/{tipo_receita}")
def api_dashboard_original_drilldown(
    tipo_receita: str,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, None, uf, codParc, codProduto)
    return list_dashboard_original_drilldown(tipo_receita, filtros)


@app.get("/api/dashboard-original/clientes/{cod_parc}/mix")
def api_dashboard_original_cliente_mix(
    cod_parc: int,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita)
    return list_dashboard_original_cliente_mix(cod_parc, filtros, limit)


@app.get("/api/dashboard-original/filtros-disponiveis")
def api_dashboard_original_filtros_disponiveis():
    return get_dashboard_original_filtros_disponiveis()


# ============================================================
# Novos Projetos (/projetos) - API REST
# ============================================================

"""
Trechos para adicionar em app/main.py.

Cria endpoints REST para a tela "Novos Projetos" (/projetos), equivalentes às
queries tRPC originais `novosProjetos.kpis`, `porMes`, `lista` e `drilldown`.

Importante:
1. Copie primeiro as funções de novos_projetos_database_endpoints.py para app/database.py.
2. Depois copie os imports e rotas abaixo para main.py.
"""

from fastapi import Query

from app.database import (
    get_novos_projetos_kpis,
    list_novos_projetos,
    list_novos_projetos_drilldown,
    list_novos_projetos_por_mes,
)


def _csv_or_list_novos_projetos(values: list[str] | None) -> list[str]:
    if not values:
        return []
    result: list[str] = []
    for value in values:
        for item in str(value).split(","):
            item = item.strip()
            if item:
                result.append(item)
    return result


def _build_novos_projetos_filtros(
    dataInicio: str | None = None,
    dataFim: str | None = None,
    mercados: list[str] | None = None,
    vendedores: list[str] | None = None,
    projetos: list[str] | None = None,
    gruposProduto: list[str] | None = None,
    tiposReceita: list[str] | None = None,
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
) -> dict:
    return {
        "dataInicio": dataInicio or "2026-01-01",
        "dataFim": dataFim or "2026-12-31",
        "mercados": _csv_or_list_novos_projetos(mercados),
        "vendedores": _csv_or_list_novos_projetos(vendedores),
        # Mantido por compatibilidade de assinatura; o database.py ignora este filtro
        # porque a tela sempre usa NOVOS PROJETOS e TESTE INDUSTRIAL.
        "projetos": _csv_or_list_novos_projetos(projetos),
        "gruposProduto": _csv_or_list_novos_projetos(gruposProduto),
        "tiposReceita": _csv_or_list_novos_projetos(tiposReceita),
        "uf": uf,
        "codParc": codParc,
        "codProduto": codProduto,
    }


def _normalize_modo_card_novos_projetos(modoCard: str | None) -> str | None:
    if modoCard in {"abertos", "totais"}:
        return modoCard
    return None


@app.get("/api/novos-projetos/kpis")
def api_novos_projetos_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    modoCard: str | None = Query(default=None),
):
    filtros = _build_novos_projetos_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return get_novos_projetos_kpis(filtros, _normalize_modo_card_novos_projetos(modoCard))


@app.get("/api/novos-projetos/por-mes")
def api_novos_projetos_por_mes(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    modoCard: str | None = Query(default=None),
):
    filtros = _build_novos_projetos_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return list_novos_projetos_por_mes(filtros, _normalize_modo_card_novos_projetos(modoCard))


@app.get("/api/novos-projetos/lista")
def api_novos_projetos_lista(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    modoCard: str | None = Query(default=None),
):
    filtros = _build_novos_projetos_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return list_novos_projetos(filtros, _normalize_modo_card_novos_projetos(modoCard))


@app.get("/api/novos-projetos/drilldown")
def api_novos_projetos_drilldown(
    mes: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_novos_projetos_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto
    )
    return list_novos_projetos_drilldown(mes, filtros)


# ============================================================
# Histórico Clientes / Produtos (/historico-clientes) - API REST
# ============================================================

from fastapi import Query
from app.database import (
    get_historico_clientes_filtros,
    get_historico_clientes_kpis,
    list_historico_clientes,
    list_historico_clientes_evolucao_mensal,
    list_historico_clientes_por_estado,
    list_historico_clientes_por_segmento,
    list_historico_cliente_produtos,
)


def _csv_or_list_historico_clientes(values):
    if values is None:
        return []
    out = []
    for value in values if isinstance(values, list) else [values]:
        if value is None:
            continue
        for part in str(value).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _int_csv_or_list_historico_clientes(values):
    out = []
    for value in _csv_or_list_historico_clientes(values):
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


def _build_historico_clientes_filtros(
    anos,
    meses,
    codParcs,
    mercados,
    gruposProduto,
    vendedores,
    ufs,
    codProdutos,
):
    filtros = {
        "anos": _int_csv_or_list_historico_clientes(anos),
        "meses": _int_csv_or_list_historico_clientes(meses),
        "codParcs": _int_csv_or_list_historico_clientes(codParcs),
        "mercados": _csv_or_list_historico_clientes(mercados),
        "gruposProduto": _csv_or_list_historico_clientes(gruposProduto),
        "vendedores": _csv_or_list_historico_clientes(vendedores),
        "ufs": _csv_or_list_historico_clientes(ufs),
        "codProdutos": _csv_or_list_historico_clientes(codProdutos),
    }
    return {k: v for k, v in filtros.items() if v}


@app.get("/api/historico-clientes/filtros")
def api_historico_clientes_filtros():
    return get_historico_clientes_filtros()


@app.get("/api/historico-clientes/kpis")
def api_historico_clientes_kpis(
    anos: list[int] | None = Query(default=None),
    meses: list[int] | None = Query(default=None),
    codParcs: list[int] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    ufs: list[str] | None = Query(default=None),
    codProdutos: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos)
    return get_historico_clientes_kpis(filtros)


@app.get("/api/historico-clientes/clientes")
def api_historico_clientes_lista(
    anos: list[int] | None = Query(default=None),
    meses: list[int] | None = Query(default=None),
    codParcs: list[int] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    ufs: list[str] | None = Query(default=None),
    codProdutos: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos)
    return list_historico_clientes(filtros)


@app.get("/api/historico-clientes/evolucao-mensal")
def api_historico_clientes_evolucao_mensal(
    anos: list[int] | None = Query(default=None),
    meses: list[int] | None = Query(default=None),
    codParcs: list[int] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    ufs: list[str] | None = Query(default=None),
    codProdutos: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos)
    return list_historico_clientes_evolucao_mensal(filtros)


@app.get("/api/historico-clientes/por-estado")
def api_historico_clientes_por_estado(
    anos: list[int] | None = Query(default=None),
    meses: list[int] | None = Query(default=None),
    codParcs: list[int] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    ufs: list[str] | None = Query(default=None),
    codProdutos: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos)
    return list_historico_clientes_por_estado(filtros)


@app.get("/api/historico-clientes/por-segmento")
def api_historico_clientes_por_segmento(
    anos: list[int] | None = Query(default=None),
    meses: list[int] | None = Query(default=None),
    codParcs: list[int] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    ufs: list[str] | None = Query(default=None),
    codProdutos: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos)
    return list_historico_clientes_por_segmento(filtros)


@app.get("/api/historico-clientes/clientes/{cod_parc}/produtos")
def api_historico_cliente_produtos(
    cod_parc: int,
    anos: list[int] | None = Query(default=None),
    meses: list[int] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(anos, meses, None, mercados, gruposProduto, vendedores, None, None)
    return list_historico_cliente_produtos(cod_parc, filtros)


# ============================================================
# Comparativo Semanal / Snapshot (/snapshot) - API REST
# ============================================================

from fastapi import Query
from app.database import (
    get_snapshot_datas,
    get_snapshot_historico,
    get_snapshot_historico_produtos,
    criar_forecast_snapshot,
)


def _csv_or_list_snapshot(values):
    if values is None:
        return []
    out = []
    for value in values if isinstance(values, list) else [values]:
        if value is None:
            continue
        for part in str(value).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _build_snapshot_filtros(
    mercados=None,
    vendedores=None,
    projetos=None,
    grupos_produto=None,
    gruposProduto=None,
    tipos_receita=None,
    tiposReceita=None,
    data_inicio=None,
    data_fim=None,
    dataInicio=None,
    dataFim=None,
    cod_parc=None,
    codParc=None,
    uf=None,
):
    filtros = {
        "mercados": _csv_or_list_snapshot(mercados),
        "vendedores": _csv_or_list_snapshot(vendedores),
        "projetos": _csv_or_list_snapshot(projetos),
        "gruposProduto": _csv_or_list_snapshot(gruposProduto) or _csv_or_list_snapshot(grupos_produto),
        "tiposReceita": _csv_or_list_snapshot(tiposReceita) or _csv_or_list_snapshot(tipos_receita),
        "dataInicio": dataInicio or data_inicio,
        "dataFim": dataFim or data_fim,
        "codParc": codParc or cod_parc,
        "uf": uf,
    }
    return {key: value for key, value in filtros.items() if value not in (None, [], "")}


@app.get("/api/snapshot/datas")
def api_snapshot_datas():
    return get_snapshot_datas()


@app.get("/api/snapshot/historico")
def api_snapshot_historico(
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    grupos_produto: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tipos_receita: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    data_inicio: str | None = None,
    data_fim: str | None = None,
    dataInicio: str | None = None,
    dataFim: str | None = None,
    cod_parc: int | None = None,
    codParc: int | None = None,
    uf: str | None = None,
):
    filtros = _build_snapshot_filtros(
        mercados=mercados,
        vendedores=vendedores,
        projetos=projetos,
        grupos_produto=grupos_produto,
        gruposProduto=gruposProduto,
        tipos_receita=tipos_receita,
        tiposReceita=tiposReceita,
        data_inicio=data_inicio,
        data_fim=data_fim,
        dataInicio=dataInicio,
        dataFim=dataFim,
        cod_parc=cod_parc,
        codParc=codParc,
        uf=uf,
    )
    return get_snapshot_historico(filtros)


@app.get("/api/snapshot/historico-produtos/{cod_parc}")
def api_snapshot_historico_produtos(
    cod_parc: int,
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    grupos_produto: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tipos_receita: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    data_inicio: str | None = None,
    data_fim: str | None = None,
    dataInicio: str | None = None,
    dataFim: str | None = None,
    uf: str | None = None,
):
    filtros = _build_snapshot_filtros(
        mercados=mercados,
        vendedores=vendedores,
        projetos=projetos,
        grupos_produto=grupos_produto,
        gruposProduto=gruposProduto,
        tipos_receita=tipos_receita,
        tiposReceita=tiposReceita,
        data_inicio=data_inicio,
        data_fim=data_fim,
        dataInicio=dataInicio,
        dataFim=dataFim,
        uf=uf,
    )
    return get_snapshot_historico_produtos(cod_parc, filtros)


@app.post("/api/snapshot/criar")
def api_snapshot_criar(request: Request):
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    if str(user.get("role", "")).lower() != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return criar_forecast_snapshot()


# =============================================================================
# Recorrentes R x O — endpoints REST
# =============================================================================

from app.database import (
    get_recorrentes_filtros,
    get_recorrentes_kpis,
    list_recorrentes_tabela,
    list_recorrentes_produtos,
)


def _csv_or_list_recorrentes(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            if item is None:
                continue
            for part in str(item).split(","):
                part = part.strip()
                if part:
                    out.append(part)
        return out
    out = []
    for part in str(value).split(","):
        part = part.strip()
        if part:
            out.append(part)
    return out


def _build_recorrentes_filtros(
    dataInicio=None,
    dataFim=None,
    mercados=None,
    vendedores=None,
    codParc=None,
    data_inicio=None,
    data_fim=None,
    cod_parc=None,
):
    filtros = {
        "dataInicio": dataInicio or data_inicio,
        "dataFim": dataFim or data_fim,
        "mercados": _csv_or_list_recorrentes(mercados),
        "vendedores": _csv_or_list_recorrentes(vendedores),
        "codParc": codParc or cod_parc,
    }
    return {key: value for key, value in filtros.items() if value not in (None, [], "")}


@app.get("/api/recorrentes/filtros")
def api_recorrentes_filtros():
    return get_recorrentes_filtros()


@app.get("/api/recorrentes/kpis")
def api_recorrentes_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    codParc: int | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    cod_parc: int | None = None,
):
    filtros = _build_recorrentes_filtros(dataInicio, dataFim, mercados, vendedores, codParc, data_inicio, data_fim, cod_parc)
    return get_recorrentes_kpis(filtros)


@app.get("/api/recorrentes/tabela")
def api_recorrentes_tabela(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    codParc: int | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    cod_parc: int | None = None,
):
    filtros = _build_recorrentes_filtros(dataInicio, dataFim, mercados, vendedores, codParc, data_inicio, data_fim, cod_parc)
    return list_recorrentes_tabela(filtros)


@app.get("/api/recorrentes/produtos/{cod_parc}")
def api_recorrentes_produtos(
    cod_parc: int,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    data_inicio: str | None = None,
    data_fim: str | None = None,
):
    filtros = _build_recorrentes_filtros(dataInicio, dataFim, mercados, vendedores, None, data_inicio, data_fim, None)
    return list_recorrentes_produtos(cod_parc, filtros)

# =============================================================================
# Funil de Vendas — endpoints REST
# =============================================================================

from app.database import (
    list_funil_vendas_vendedores,
    get_funil_vendas_kpis,
    list_funil_vendas_por_etapa,
    list_funil_vendas_por_pipeline,
    list_funil_vendas_top_vendedores,
    list_funil_vendas_evolucao_mensal,
)


def _csv_or_list_funil(value):
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for item in values:
        if item is None or item == "":
            continue
        if isinstance(item, str) and "," in item:
            out.extend(part.strip() for part in item.split(",") if part.strip())
        else:
            out.append(item)
    return out


def _pipeline_ids_funil(value):
    ids = []
    for item in _csv_or_list_funil(value):
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


@app.get("/api/funil-vendas/vendedores")
def api_funil_vendas_vendedores():
    return list_funil_vendas_vendedores()


@app.get("/api/funil-vendas/kpis")
def api_funil_vendas_kpis(
    pipelineIds: list[str] | None = Query(default=None),
    pipeline_ids: list[str] | None = Query(default=None),
    userId: int | None = None,
    user_id: int | None = None,
):
    pipelines = _pipeline_ids_funil(pipelineIds or pipeline_ids)
    return get_funil_vendas_kpis(pipelines, userId or user_id)


@app.get("/api/funil-vendas/por-etapa")
def api_funil_vendas_por_etapa(
    pipelineIds: list[str] | None = Query(default=None),
    pipeline_ids: list[str] | None = Query(default=None),
    userId: int | None = None,
    user_id: int | None = None,
):
    pipelines = _pipeline_ids_funil(pipelineIds or pipeline_ids)
    return list_funil_vendas_por_etapa(pipelines, userId or user_id)


@app.get("/api/funil-vendas/por-pipeline")
def api_funil_vendas_por_pipeline(
    pipelineIds: list[str] | None = Query(default=None),
    pipeline_ids: list[str] | None = Query(default=None),
    userId: int | None = None,
    user_id: int | None = None,
):
    pipelines = _pipeline_ids_funil(pipelineIds or pipeline_ids)
    return list_funil_vendas_por_pipeline(pipelines, userId or user_id)


@app.get("/api/funil-vendas/top-vendedores")
def api_funil_vendas_top_vendedores(
    pipelineIds: list[str] | None = Query(default=None),
    pipeline_ids: list[str] | None = Query(default=None),
    userId: int | None = None,
    user_id: int | None = None,
):
    pipelines = _pipeline_ids_funil(pipelineIds or pipeline_ids)
    return list_funil_vendas_top_vendedores(pipelines, userId or user_id)


@app.get("/api/funil-vendas/evolucao-mensal")
def api_funil_vendas_evolucao_mensal(
    pipelineIds: list[str] | None = Query(default=None),
    pipeline_ids: list[str] | None = Query(default=None),
    userId: int | None = None,
    user_id: int | None = None,
):
    pipelines = _pipeline_ids_funil(pipelineIds or pipeline_ids)
    return list_funil_vendas_evolucao_mensal(pipelines, userId or user_id)


# =============================================================================
# Panorama CRM — endpoints REST
# =============================================================================

from app.database import (
    list_panorama_crm_vendedores,
    get_panorama_leads_snapshot,
    get_panorama_deals_snapshot,
    get_panorama_leads,
    get_panorama_deals,
)


def _panorama_parse_pipeline_id(value: str | int | None) -> int | None:
    if value is None or value == "" or value == "null" or value == "todos":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _panorama_parse_user_id(value: str | int | None) -> int | None:
    if value is None or value == "" or value == "null" or value == "todos":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _panorama_normalize_origem(value: str | None) -> str:
    return value if value in {"leads", "base", "total"} else "total"


def _panorama_normalize_visao(value: str | None) -> str:
    return value if value in {"calendario", "coorte"} else "calendario"


@app.get("/api/panorama-crm/vendedores")
def api_panorama_crm_vendedores():
    return list_panorama_crm_vendedores()


@app.get("/api/panorama-crm/leads-snapshot")
def api_panorama_crm_leads_snapshot():
    return get_panorama_leads_snapshot()


@app.get("/api/panorama-crm/deals-snapshot")
def api_panorama_crm_deals_snapshot(
    pipelineId: str | None = None,
    pipeline_id: str | None = None,
    origem: str | None = None,
    userId: str | None = None,
    user_id: str | None = None,
):
    return get_panorama_deals_snapshot(
        _panorama_parse_pipeline_id(pipelineId if pipelineId is not None else pipeline_id),
        _panorama_normalize_origem(origem),
        _panorama_parse_user_id(userId if userId is not None else user_id),
    )


@app.get("/api/panorama-crm/leads")
def api_panorama_crm_leads(
    dateIni: str = Query(default="2026-01-01"),
    dateFim: str = Query(default="2026-12-31"),
    date_ini: str | None = None,
    date_fim: str | None = None,
    visao: str | None = Query(default="calendario"),
):
    return get_panorama_leads(
        date_ini or dateIni,
        date_fim or dateFim,
        _panorama_normalize_visao(visao),
    )


@app.get("/api/panorama-crm/deals")
def api_panorama_crm_deals(
    dateIni: str = Query(default="2026-01-01"),
    dateFim: str = Query(default="2026-12-31"),
    date_ini: str | None = None,
    date_fim: str | None = None,
    visao: str | None = Query(default="calendario"),
    pipelineId: str | None = None,
    pipeline_id: str | None = None,
    origem: str | None = None,
    userId: str | None = None,
    user_id: str | None = None,
):
    return get_panorama_deals(
        date_ini or dateIni,
        date_fim or dateFim,
        _panorama_normalize_visao(visao),
        _panorama_parse_pipeline_id(pipelineId if pipelineId is not None else pipeline_id),
        _panorama_normalize_origem(origem),
        _panorama_parse_user_id(userId if userId is not None else user_id),
    )

# =============================================================================
# Agente IA / Chatbot — endpoints REST
# =============================================================================

import json as _chat_json
import urllib.error as _chat_urllib_error
import urllib.request as _chat_urllib_request
from typing import Any as _ChatAny

from app.database import (
    get_chat_sessions,
    get_chat_history,
    save_chat_message,
    clear_chat_history,
)


class ChatSendRequest(BaseModel):
    sessionId: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1)
    history: list[dict] = Field(default_factory=list)


class ChatQGRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[dict] = Field(default_factory=list)


def _chat_public_history(history: list[dict] | None, user_message: str, assistant_answer: str) -> list[dict]:
    normalized: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            normalized.append({"role": role, "content": content})
    normalized.append({"role": "user", "content": user_message})
    normalized.append({"role": "assistant", "content": assistant_answer})
    return normalized[-30:]


def _chat_fallback_answer(message: str, error_detail: str | None = None) -> str:
    base = (
        "Recebi sua pergunta e a conversa foi registrada, mas o motor inteligente ainda não está "
        "configurado nesta API Python. Configure OPENAI_API_KEY no .env da API para habilitar "
        "respostas analíticas automáticas sobre faturamento, CRM e SQL Server."
    )
    if error_detail:
        return f"{base}\n\nDetalhe técnico: {error_detail}"
    return base


def _call_openai_chat(message: str, history: list[dict] | None) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "Você é o Agente IA do QG Polpa Brasil. Responda em português do Brasil, "
                "com foco em faturamento, CRM Bitrix24, funil de vendas, clientes e análises comerciais. "
                "Quando não houver dados concretos disponíveis no contexto, seja transparente e peça o filtro ou período necessário."
            ),
        }
    ]

    for item in (history or [])[-20:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    body = _chat_json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
    ).encode("utf-8")

    request = _chat_urllib_request.Request(
        f"{api_base}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    with _chat_urllib_request.urlopen(request, timeout=45) as response:
        raw = response.read().decode("utf-8")
        data: dict[str, _ChatAny] = _chat_json.loads(raw)
        choices = data.get("choices") or []
        if not choices:
            return None
        content = ((choices[0] or {}).get("message") or {}).get("content")
        return content.strip() if isinstance(content, str) and content.strip() else None


def _chat_qg_generate_answer(message: str, history: list[dict] | None = None) -> dict:
    try:
        answer = _call_openai_chat(message, history)
        if not answer:
            answer = _chat_fallback_answer(message)
    except _chat_urllib_error.HTTPError as exc:
        answer = _chat_fallback_answer(message, f"OpenAI HTTP {exc.code}")
    except Exception as exc:
        answer = _chat_fallback_answer(message, str(exc))

    return {
        "answer": answer,
        "history": _chat_public_history(history, message, answer),
    }


def _require_chat_user(request: Request) -> dict:
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return user


def _validate_internal_chat_secret(request: Request) -> None:
    expected = os.getenv("INTERNAL_CHAT_SECRET", "")
    if not expected:
        return
    received = request.headers.get("X-Internal-Secret", "")
    if received != expected:
        raise HTTPException(status_code=401, detail="Segredo interno inválido")


@app.get("/api/chatbot/sessions", tags=["Agente IA"])
def api_chatbot_sessions(request: Request):
    user = _require_chat_user(request)
    return get_chat_sessions(int(user["id"]))


@app.get("/api/chatbot/history/{session_id}", tags=["Agente IA"])
def api_chatbot_history(session_id: str, request: Request, limit: int = 50):
    _require_chat_user(request)
    return get_chat_history(session_id, limit)


@app.post("/api/chatbot/send", tags=["Agente IA"])
def api_chatbot_send(payload: ChatSendRequest, request: Request):
    user = _require_chat_user(request)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Mensagem vazia")

    save_chat_message(payload.sessionId, int(user["id"]), "user", message)
    data = _chat_qg_generate_answer(message, payload.history)
    answer = str(data.get("answer") or "")
    save_chat_message(payload.sessionId, None, "assistant", answer)

    return {
        "reply": answer,
        "agentHistory": data.get("history") or [],
    }


@app.delete("/api/chatbot/sessions/{session_id}", tags=["Agente IA"])
def api_chatbot_delete_session(session_id: str, request: Request):
    _require_chat_user(request)
    clear_chat_history(session_id)
    return {"success": True}


@app.post("/api/chat-qg", tags=["Agente IA"])
def api_chat_qg(payload: ChatQGRequest, request: Request):
    _validate_internal_chat_secret(request)
    return _chat_qg_generate_answer(payload.message.strip(), payload.history)