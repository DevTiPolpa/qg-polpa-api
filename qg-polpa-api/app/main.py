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

# IMPORTANTE PARA VERCEL + NGROK:
# Quando o frontend está em https://qg-polpa-brasil.vercel.app e a API em
# https://*.ngrok-free.dev, o navegador considera a chamada como cross-site.
# Nesse cenário, o cookie de sessão só é enviado no fetch/XHR se estiver com
# SameSite=None e Secure=True. O valor antigo default false/lax causa exatamente
# o erro 401 em /api/auth/change-password, pois o backend não recebe o cookie.
def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

COOKIE_SECURE = _env_bool("COOKIE_SECURE", True)
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "none" if COOKIE_SECURE else "lax").strip().lower()

# Browsers modernos rejeitam SameSite=None sem Secure. Mantém proteção para não
# gerar cookie inválido em produção.
if COOKIE_SAMESITE == "none" and not COOKIE_SECURE:
    COOKIE_SECURE = True

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
    """Obtém o usuário autenticado pelo cookie de sessão.

    O fluxo principal usa cookie HttpOnly. Como fallback técnico, a função
    também aceita Authorization: Bearer <token>, útil em testes ou em cenários
    onde o navegador bloqueie cookies de terceiros. O frontend atual pode
    continuar usando cookies normalmente.
    """
    token = request.cookies.get(COOKIE_NAME)

    if not token:
        authorization = request.headers.get("Authorization") or request.headers.get("authorization")
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()

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

        auth_user = serialize_auth_user(user)
        # Mantém compatibilidade com o frontend atual e disponibiliza o token
        # como fallback para Authorization: Bearer, caso seja necessário.
        return {
            **auth_user,
            "accessToken": token,
        }

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
# Agente IA / Chatbot — endpoints REST com agente SQL sobre produção
# =============================================================================

import json as _chat_json
import os as _chat_os
import re as _chat_re
import urllib.error as _chat_urllib_error
import urllib.request as _chat_urllib_request
from typing import Any as _ChatAny

from app.database import (
    get_chat_sessions,
    get_chat_history,
    save_chat_message,
    clear_chat_history,
    get_agent_database_schema,
    execute_agent_sql,
    get_faturamento_anual_por_categoria,
)


class ChatSendRequest(BaseModel):
    sessionId: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1)
    history: list[dict] = Field(default_factory=list)


class ChatQGRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[dict] = Field(default_factory=list)


_CHAT_MAX_HISTORY_TURNS = 6
_CHAT_MAX_TOOL_ROUNDS = 5


_CHAT_BUSINESS_CONTEXT = """
## CONTEXTO DA POLPA BRASIL

A Polpa Brasil é uma fornecedora B2B de ingredientes alimentícios, especialmente frutas e vegetais desidratados. Os clientes principais são indústrias de alimentos e distribuidores/atacadistas. O ciclo comercial é longo: pode passar de 6 meses entre o primeiro contato e o fechamento. No CRM Bitrix24, um negócio ganho representa o primeiro pedido realizado pelo cliente; o campo de oportunidade de um negócio representa uma estimativa anual de faturamento, não necessariamente um pedido único.

## DADOS DE FATURAMENTO / FORECAST / PROJETOS

Para perguntas de faturamento, forecast, vendas firmes, novos projetos, clientes, produtos, vendedores, mercados, grupos de produto ou períodos, use prioritariamente a tabela `fato_vendas`. Ela representa a base analítica de produção do QG. Campos mais usados:

- `valor_pendente`: valor financeiro para somas de faturamento/forecast/projetos.
- `qtd_pendente_kg`: volume em kg.
- `dt_entrega_cliente`: data de entrega usada para filtrar anos, meses e períodos.
- `tipo_receita`: valores esperados `VENDA_FIRME`, `FORECAST`, `NOVO_PROJETO`, `DEVOLUCAO`.
- `nome_vendedor`, `mercado_vendas`, `projeto`, `grupo_produto`, `nome_parc`, `cod_parc`, `descricao_produto`, `cod_produto`, `uf`.
- Para análises gerais, exclua estoque mínimo: `(cod_top IS NULL OR cod_top != 1023)` e `([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')`.

Ao responder “Qual o faturamento total de 2026?”, consulte `fato_vendas` filtrando `dt_entrega_cliente >= '2026-01-01'` e `< '2027-01-01'`, agrupe por `tipo_receita` e some `valor_pendente`. Reproduza a regra do projeto original local: Vendas Firmes soma `VENDA_FIRME` e `DEVOLUCAO` em valor absoluto, Forecast usa `FORECAST` e Projetos usa `NOVO_PROJETO`. Não exiba Devoluções como categoria separada. Inclua total e percentuais.

## CRM BITRIX24

Para perguntas sobre funil, negócios, etapas, pipelines, follow-up, atividades, leads, responsáveis, negócios parados e performance CRM, use as tabelas `crm_*`, especialmente `crm_deals`, `crm_users`, `crm_deal_stages`, `crm_pipelines`, `crm_leads`, `crm_tasks` e `crm_deal_stage_history`, se existirem na base.

Regras críticas de CRM:
- Funil Comercial principal: `category_id = '0'` ou `category_id IS NULL`, salvo se o usuário pedir outro funil.
- Negócios em andamento: `stage_semantic_id = 'P'`.
- Negócios ganhos: `stage_semantic_id = 'S'`.
- Negócios perdidos: `stage_semantic_id = 'F'`.
- Perguntas sobre “sem atividade”, “sem follow-up”, “sem tarefa”, “parados” ou “sem contato” devem usar `last_activity_time` de `crm_deals`, nunca `crm_tasks`, pois tarefas abertas não representam histórico completo.
- Negócio sem atividade há mais de 15 dias é alerta; mais de 30 dias é crítico; mais de 60 dias é estagnado.

## COMO RESPONDER

Você deve consultar o banco antes de responder quando a pergunta envolver valores, rankings, contagens, percentuais, funil, faturamento, forecast, clientes, produtos, vendedores ou CRM. Prefira queries agregadas com `GROUP BY`, `COUNT`, `SUM`, `AVG` e `TOP`. Use SQL Server/T-SQL, não SQLite. Para datas, use `DATEDIFF`, `DATEFROMPARTS`, `YEAR`, `MONTH` e filtros com datas ISO. Responda em português do Brasil, de forma executiva, clara e objetiva. Inclua totais, percentuais e destaques quando relevante. Quando houver limitações de dados, explique de forma transparente.
""".strip()


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
        "Recebi sua pergunta e a conversa foi registrada, mas não consegui executar a análise inteligente "
        "com acesso aos dados da base de produção neste momento. Verifique se OPENAI_API_KEY está configurada, "
        "se a API consegue conectar no SQL Server e se o banco conectado contém tabelas/views com colunas de valor e data para faturamento."
    )
    if error_detail:
        return f"{base}\n\nDetalhe técnico: {error_detail}"
    return base


def _chat_openai_request(payload: dict, timeout: int = 90) -> dict:
    api_key = _chat_os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY não configurada no ambiente da API Python")

    api_base = _chat_os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/")
    body = _chat_json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = _chat_urllib_request.Request(
        f"{api_base}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with _chat_urllib_request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return _chat_json.loads(raw)


def _chat_normalize_model_history(history: list[dict] | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in (history or [])[-(_CHAT_MAX_HISTORY_TURNS * 2):]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content.strip():
            messages.append({"role": role, "content": content[:8000]})
    return messages


def _chat_get_tool_call_message(choice_message: dict) -> dict:
    return {
        "role": "assistant",
        "content": choice_message.get("content"),
        "tool_calls": choice_message.get("tool_calls") or [],
    }


def _chat_extract_final_content(data: dict) -> str | None:
    choices = data.get("choices") or []
    if not choices:
        return None
    content = ((choices[0] or {}).get("message") or {}).get("content")
    return content.strip() if isinstance(content, str) and content.strip() else None


def _chat_build_system_prompt() -> str:
    try:
        schema = get_agent_database_schema()
    except Exception as exc:
        schema = f"Não foi possível carregar schema automaticamente: {exc}"

    return f"""
Você é o Agente IA do QG Polpa Brasil. Sua função é responder perguntas comerciais e analíticas usando dados reais da base SQL Server de produção.

{_CHAT_BUSINESS_CONTEXT}

## SCHEMA DISPONÍVEL NA BASE

{schema}

## REGRAS OBRIGATÓRIAS

1. Para perguntas numéricas ou analíticas, sempre use a ferramenta `execute_sql` antes de responder.
2. Execute apenas consultas SELECT/WITH. Nunca tente INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, MERGE, EXEC ou comandos administrativos.
3. Use sintaxe SQL Server/T-SQL. Não use funções SQLite como JULIANDAY ou strftime.
4. Se uma query falhar por nome de coluna/tabela, consulte o schema e corrija a query em uma nova tentativa.
5. Responda em português do Brasil e destaque números em formato legível, como R$ 1.234.567,89 e percentuais.
6. Não invente dados. Se a base não tiver informação suficiente, diga exatamente o que faltou.
""".strip()


def _call_openai_sql_agent(message: str, history: list[dict] | None) -> str:
    model = _chat_os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    messages: list[dict] = [
        {"role": "system", "content": _chat_build_system_prompt()},
        *_chat_normalize_model_history(history),
        {"role": "user", "content": message},
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_sql",
                "description": "Executa uma consulta SELECT/WITH segura no SQL Server de produção e retorna linhas em JSON.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Consulta SQL Server somente leitura. Use SELECT ou WITH. Use TOP para limitar listas detalhadas.",
                        }
                    },
                    "required": ["query"],
                },
            },
        }
    ]

    for _round in range(_CHAT_MAX_TOOL_ROUNDS):
        data = _chat_openai_request(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.1,
            }
        )
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI não retornou choices")
        choice_message = (choices[0] or {}).get("message") or {}
        tool_calls = choice_message.get("tool_calls") or []
        if not tool_calls:
            final = choice_message.get("content")
            if isinstance(final, str) and final.strip():
                return final.strip()
            raise RuntimeError("OpenAI não retornou resposta final")

        messages.append(_chat_get_tool_call_message(choice_message))
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            name = function.get("name")
            args_raw = function.get("arguments") or "{}"
            try:
                args = _chat_json.loads(args_raw)
            except Exception:
                args = {}
            if name != "execute_sql":
                result = {"erro": f"Ferramenta desconhecida: {name}"}
            else:
                result = execute_agent_sql(str(args.get("query") or ""))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "content": _chat_json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    data = _chat_openai_request(
        {
            "model": model,
            "messages": messages + [
                {
                    "role": "user",
                    "content": "Finalize a resposta com base nos resultados já obtidos. Se não houver dados suficientes, explique a limitação.",
                }
            ],
            "temperature": 0.1,
        }
    )
    final = _chat_extract_final_content(data)
    if not final:
        raise RuntimeError("Limite de rodadas de ferramenta atingido sem resposta final")
    return final



def _chat_detect_faturamento_anual_intent(message: str) -> int | None:
    text = (message or "").strip().lower()
    if not text:
        return None
    has_revenue_word = any(
        token in text
        for token in (
            "faturamento",
            "receita",
            "venda",
            "vendas",
            "forecast",
            "projeto",
            "projetos",
        )
    )
    if not has_revenue_word:
        return None
    match = _chat_re.search(r"\b(20\d{2}|2100)\b", text)
    if not match:
        return None
    return int(match.group(1))


def _chat_format_currency(value: float | int | None) -> str:
    numeric = float(value or 0)
    formatted = f"R$ {numeric:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _chat_format_percent(value: float | int | None) -> str:
    numeric = float(value or 0)
    return f"{numeric:.1f}%".replace(".", ",")


def _chat_build_faturamento_anual_answer(message: str) -> str | None:
    ano = _chat_detect_faturamento_anual_intent(message)
    if ano is None:
        return None

    result = get_faturamento_anual_por_categoria(ano)
    if not result.get("success"):
        detail = result.get("error") or "erro desconhecido na consulta determinística"
        linhas = [
            f"Não consegui calcular o faturamento de **{ano}** porque a API conectou em um banco onde não encontrei uma fonte de faturamento compatível.",
            "",
            f"Detalhe técnico: {detail}",
        ]
        candidates = result.get("candidate_sources") or []
        if candidates:
            linhas.extend(["", "Possíveis fontes encontradas, mas ainda não retornaram valor para o ano solicitado:", "", "| Tabela/View | Coluna de valor | Coluna de data | Pontuação |", "|---|---|---|---:|"])
            for item in candidates[:8]:
                linhas.append(f"| `{item.get('schema')}.{item.get('table')}` | `{item.get('value_col')}` | `{item.get('date_col')}` | {item.get('score')} |")
        available = result.get("available_tables_sample") or []
        if available:
            linhas.extend(["", "Amostra das tabelas/views visíveis no banco conectado:", ""])
            for item in available[:25]:
                linhas.append(f"- `{item}`")
        linhas.append("")
        linhas.append("Isso indica que a API pode estar apontando para outro banco/schema, ou que o faturamento está em uma tabela com nomes de colunas muito diferentes. Se aparecer uma tabela correta na lista acima, me envie o nome dela que eu fixo a consulta nela.")
        return "\n".join(linhas)

    rows = result.get("rows") or []
    total = float(result.get("total") or 0)
    if not rows or total == 0:
        return (
            f"Consultei a base SQL Server conectada para o ano de **{ano}**, "
            "mas não encontrei faturamento com `dt_entrega_cliente` dentro desse período.\n\n"
            "Verifique se os dados desse ano já foram carregados, ou se o faturamento está registrado em outro campo/período."
        )

    lines = [
        f"Consultei a base SQL Server conectada e encontrei o seguinte faturamento para **{ano}**:",
        "",
        "| Categoria | Valor | % do total |",
        "|---|---:|---:|",
    ]
    for item in rows:
        lines.append(
            f"| {item.get('categoria') or 'Sem categoria'} | {_chat_format_currency(item.get('total'))} | {_chat_format_percent(item.get('percentual'))} |"
        )
    lines.extend([
        f"| **Total** | **{_chat_format_currency(total)}** | **100,0%** |",
        "",
        "**Destaques executivos:**",
    ])

    sorted_rows = sorted(rows, key=lambda item: float(item.get("total") or 0), reverse=True)
    leader = sorted_rows[0]
    lines.append(
        f"A maior parcela do faturamento está em **{leader.get('categoria')}**, com **{_chat_format_currency(leader.get('total'))}** "
        f"({_chat_format_percent(leader.get('percentual'))} do total)."
    )

    vendas_firmes = next((item for item in rows if item.get("categoria") == "Vendas Firmes"), None)
    forecast = next((item for item in rows if item.get("categoria") == "Forecast"), None)
    projetos = next((item for item in rows if item.get("categoria") == "Projetos"), None)

    if vendas_firmes:
        lines.append(
            f"As **Vendas Firmes** somam **{_chat_format_currency(vendas_firmes.get('total'))}**, "
            f"representando {_chat_format_percent(vendas_firmes.get('percentual'))} do total anual."
        )
    if forecast or projetos:
        pipeline_total = float((forecast or {}).get("total") or 0) + float((projetos or {}).get("total") or 0)
        pipeline_pct = (pipeline_total / total * 100.0) if total else 0.0
        lines.append(
            f"O componente projetado/pipeline, somando **Forecast** e **Projetos**, representa **{_chat_format_currency(pipeline_total)}** "
            f"({_chat_format_percent(pipeline_pct)} do total)."
        )

    context = result.get("query_context") or {}
    table = context.get("table") or "fato_vendas"
    lines.append("")
    lines.append(
        f"Critério usado: soma de valores em `{table}`, filtrando o ano **{ano}**. Regra igual ao projeto original local: `VENDA_FIRME` e `DEVOLUCAO` entram em **Vendas Firmes**, `FORECAST` entra em **Forecast** e `NOVO_PROJETO` entra em **Projetos**. Quando `fato_vendas` não existe, uso fallback automático em tabelas/views locais e, por último, descoberta por colunas prováveis de valor e data."
    )
    return "\n".join(lines)

def _chat_qg_generate_answer(message: str, history: list[dict] | None = None) -> dict:
    deterministic_answer = _chat_build_faturamento_anual_answer(message)
    if deterministic_answer:
        return {
            "answer": deterministic_answer,
            "history": _chat_public_history(history, message, deterministic_answer),
        }

    try:
        answer = _call_openai_sql_agent(message, history)
    except _chat_urllib_error.HTTPError as exc:
        detail = f"OpenAI HTTP {exc.code}"
        try:
            detail_body = exc.read().decode("utf-8")[:800]
            if detail_body:
                detail = f"{detail}: {detail_body}"
        except Exception:
            pass
        answer = _chat_fallback_answer(message, detail)
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
    expected = _chat_os.getenv("INTERNAL_CHAT_SECRET", "")
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