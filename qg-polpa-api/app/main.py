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