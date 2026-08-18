import os
import re
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


@app.on_event("startup")
def _iniciar_scheduler() -> None:
    from app.scheduler import iniciar_scheduler_snapshot_semanal
    iniciar_scheduler_snapshot_semanal()


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
    list_vendedores_cliente_produto_mensal_original,
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
    list_dashboard_original_produto_mix,
    list_dashboard_original_produtos_top,
    list_dashboard_original_regiao_mix,
    list_dashboard_original_regioes_top,
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
    codParcs: list[int] | None = None,
    codProdutos: list[int] | None = None,
    periodos: list[str] | None = None,
) -> dict:
    return {
        "dataInicio": dataInicio or "2026-01-01",
        "dataFim": dataFim or "2026-12-31",
        "periodos": _csv_or_list(periodos),
        "mercados": _csv_or_list(mercados),
        "vendedores": _csv_or_list(vendedores),
        "projetos": _csv_or_list(projetos),
        "gruposProduto": _csv_or_list(gruposProduto),
        "tiposReceita": _csv_or_list(tiposReceita),
        "uf": uf,
        "codParc": codParc,
        "codProduto": codProduto,
        "codParcs": codParcs or ([codParc] if codParc is not None else []),
        "codProdutos": codProdutos or ([codProduto] if codProduto is not None else []),
    }


@app.get("/api/vendedores-original/resumo")
def api_vendedores_original_resumo(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    codParcs: list[int] | None = Query(default=None),
    codProdutos: list[int] | None = Query(default=None),
    limitClientes: int = Query(default=50, ge=1, le=500),
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto,
        codParcs, codProdutos,
        periodos=periodos,
    )
    return get_vendedores_original_resumo(filtros, limitClientes)


@app.get("/api/vendedores-original/kpis")
def api_vendedores_original_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
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
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto, periodos=periodos,
    )
    return get_vendedores_kpis_original(filtros)


@app.get("/api/vendedores-original/performance")
def api_vendedores_original_performance(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
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
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto, periodos=periodos,
    )
    return list_vendedores_performance_original(filtros)


@app.get("/api/vendedores-original/evolucao")
def api_vendedores_original_evolucao(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
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
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto, periodos=periodos,
    )
    return list_vendedores_evolucao_original(filtros)


@app.get("/api/vendedores-original/evolucao-por-tipo")
def api_vendedores_original_evolucao_por_tipo(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, None, uf, codParc, codProduto, periodos=periodos,
    )
    return list_vendedores_evolucao_por_tipo_original(filtros)


@app.get("/api/vendedores-original/clientes-consolidados")
def api_vendedores_original_clientes_consolidados(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
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
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto, periodos=periodos,
    )
    return list_vendedores_clientes_consolidados_original(filtros, limit)


@app.get("/api/vendedores-original/metas")
def api_vendedores_original_metas(
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
):
    filtros = _build_vendedores_filtros(
        None, None, mercados, vendedores, projetos, None, None, None, None, None, periodos=periodos,
    )
    return list_metas_vendedores_original(filtros)


@app.get("/api/vendedores-original/orcamento-kpis")
def api_vendedores_original_orcamento_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, None, projetos, gruposProduto, None, None, None, None, periodos=periodos,
    )
    return get_orcamento_kpis_original(filtros)


@app.get("/api/vendedores-original/orcamento-mensal")
def api_vendedores_original_orcamento_mensal(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, None, projetos, gruposProduto, None, None, None, None, periodos=periodos,
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
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codProduto: int | None = None,
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, None, codProduto, periodos=periodos,
    )
    return list_vendedores_cliente_mix_original(cod_parc, filtros)


@app.get("/api/vendedores-original/clientes/{cod_parc}/produtos/{cod_produto}/mensal")
def api_vendedores_original_cliente_produto_mensal(
    cod_parc: int,
    cod_produto: int,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
):
    filtros = _build_vendedores_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, None, None, periodos=periodos,
    )
    return list_vendedores_cliente_produto_mensal_original(cod_parc, cod_produto, filtros)


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
    codParcs: list[int] | None = None,
    codProdutos: list[int] | None = None,
    periodos: list[str] | None = None,
) -> dict:
    return {
        "dataInicio": dataInicio or "2026-01-01",
        "dataFim": dataFim or "2026-12-31",
        "periodos": _csv_or_list_dashboard(periodos),
        "mercados": _csv_or_list_dashboard(mercados),
        "vendedores": _csv_or_list_dashboard(vendedores),
        "projetos": _csv_or_list_dashboard(projetos),
        "gruposProduto": _csv_or_list_dashboard(gruposProduto),
        "tiposReceita": _csv_or_list_dashboard(tiposReceita),
        "uf": uf,
        "codParc": codParc,
        "codProduto": codProduto,
        "codParcs": codParcs or ([codParc] if codParc is not None else []),
        "codProdutos": codProdutos or ([codProduto] if codProduto is not None else []),
    }


@app.get("/api/dashboard-original/resumo")
def api_dashboard_original_resumo(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    codParcs: list[int] | None = Query(default=None),
    codProdutos: list[int] | None = Query(default=None),
    limitClientes: int | None = Query(default=None, ge=1, le=500),
):
    filtros = _build_dashboard_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto,
        codParcs, codProdutos,
        periodos=periodos,
    )
    return get_dashboard_original_resumo(filtros, limitClientes)


@app.get("/api/dashboard-original/kpis")
def api_dashboard_original_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
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
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto, periodos=periodos,
    )
    return get_dashboard_original_kpis(filtros)


@app.get("/api/dashboard-original/kpis-ano-anterior")
def api_dashboard_original_kpis_ano_anterior(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
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
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto, periodos=periodos,
    )
    return get_dashboard_original_kpis_ano_anterior(filtros)


@app.get("/api/dashboard-original/evolucao-mensal")
def api_dashboard_original_evolucao_mensal(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
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
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto, periodos=periodos,
    )
    return list_dashboard_original_evolucao_mensal(filtros)


@app.get("/api/dashboard-original/evolucao-ano-anterior")
def api_dashboard_original_evolucao_ano_anterior(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
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
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto, periodos=periodos,
    )
    return list_dashboard_original_evolucao_ano_anterior(filtros)


@app.get("/api/dashboard-original/kpis-por-tipo")
def api_dashboard_original_kpis_por_tipo(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_dashboard_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, None, uf, codParc, codProduto, periodos=periodos,
    )
    return list_dashboard_original_kpis_por_tipo(filtros)


@app.get("/api/dashboard-original/orcamento-kpis")
def api_dashboard_original_orcamento_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, None, projetos, gruposProduto, None, periodos=periodos)
    return get_dashboard_original_orcamento_kpis(filtros)


@app.get("/api/dashboard-original/orcamento-mensal")
def api_dashboard_original_orcamento_mensal(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, None, projetos, gruposProduto, None, periodos=periodos)
    return list_dashboard_original_orcamento_mensal(filtros)


@app.get("/api/dashboard-original/segmentos")
def api_dashboard_original_segmentos(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, periodos=periodos)
    return list_dashboard_original_segmentos(filtros)


@app.get("/api/dashboard-original/projetos")
def api_dashboard_original_projetos(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, periodos=periodos)
    return list_dashboard_original_projetos(filtros)


@app.get("/api/dashboard-original/clientes-top")
def api_dashboard_original_clientes_top(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, periodos=periodos)
    return list_dashboard_original_clientes_top(filtros, limit)


@app.get("/api/dashboard-original/produtos-top")
def api_dashboard_original_produtos_top(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, periodos=periodos)
    return list_dashboard_original_produtos_top(filtros, limit)


@app.get("/api/dashboard-original/produtos/{cod_produto}/mix")
def api_dashboard_original_produto_mix(
    cod_produto: int,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, periodos=periodos)
    return list_dashboard_original_produto_mix(cod_produto, filtros, limit)


@app.get("/api/dashboard-original/regioes-top")
def api_dashboard_original_regioes_top(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, periodos=periodos)
    return list_dashboard_original_regioes_top(filtros)


@app.get("/api/dashboard-original/regioes/{regiao}/mix")
def api_dashboard_original_regiao_mix(
    regiao: str,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, periodos=periodos)
    return list_dashboard_original_regiao_mix(regiao, filtros)


@app.get("/api/dashboard-original/drilldown/{tipo_receita}")
def api_dashboard_original_drilldown(
    tipo_receita: str,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, None, uf, codParc, codProduto, periodos=periodos)
    return list_dashboard_original_drilldown(tipo_receita, filtros)


@app.get("/api/dashboard-original/clientes/{cod_parc}/mix")
def api_dashboard_original_cliente_mix(
    cod_parc: int,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
):
    filtros = _build_dashboard_filtros(dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, periodos=periodos)
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
    list_novos_projetos_recorrentes_convertidos,
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
    codParcs: list[int] | None = None,
    codProdutos: list[int] | None = None,
    periodos: list[str] | None = None,
) -> dict:
    return {
        "dataInicio": dataInicio or "2026-01-01",
        "dataFim": dataFim or "2026-12-31",
        "periodos": _csv_or_list_novos_projetos(periodos),
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
        "codParcs": codParcs or ([codParc] if codParc is not None else []),
        "codProdutos": codProdutos or ([codProduto] if codProduto is not None else []),
    }


def _normalize_modo_card_novos_projetos(modoCard: str | None) -> str | None:
    if modoCard in {"abertos", "totais"}:
        return modoCard
    return None


@app.get("/api/novos-projetos/kpis")
def api_novos_projetos_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    codParcs: list[int] | None = Query(default=None),
    codProdutos: list[int] | None = Query(default=None),
    modoCard: str | None = Query(default=None),
):
    filtros = _build_novos_projetos_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto,
        codParcs, codProdutos,
        periodos=periodos,
    )
    return get_novos_projetos_kpis(filtros, _normalize_modo_card_novos_projetos(modoCard))


@app.get("/api/novos-projetos/por-mes")
def api_novos_projetos_por_mes(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    codParcs: list[int] | None = Query(default=None),
    codProdutos: list[int] | None = Query(default=None),
    modoCard: str | None = Query(default=None),
):
    filtros = _build_novos_projetos_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto,
        codParcs, codProdutos,
        periodos=periodos,
    )
    return list_novos_projetos_por_mes(filtros, _normalize_modo_card_novos_projetos(modoCard))


@app.get("/api/novos-projetos/lista")
def api_novos_projetos_lista(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    codParcs: list[int] | None = Query(default=None),
    codProdutos: list[int] | None = Query(default=None),
    modoCard: str | None = Query(default=None),
):
    filtros = _build_novos_projetos_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto,
        codParcs, codProdutos,
        periodos=periodos,
    )
    return list_novos_projetos(filtros, _normalize_modo_card_novos_projetos(modoCard))


@app.get("/api/novos-projetos/recorrentes-convertidos")
def api_novos_projetos_recorrentes_convertidos(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    tiposReceita: list[str] | None = Query(default=None),
    uf: str | None = None,
    codParc: int | None = None,
    codProduto: int | None = None,
    codParcs: list[int] | None = Query(default=None),
    codProdutos: list[int] | None = Query(default=None),
):
    filtros = _build_novos_projetos_filtros(
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto,
        codParcs, codProdutos,
        periodos=periodos,
    )
    return list_novos_projetos_recorrentes_convertidos(filtros)


@app.get("/api/novos-projetos/drilldown")
def api_novos_projetos_drilldown(
    mes: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
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
        dataInicio, dataFim, mercados, vendedores, projetos, gruposProduto, tiposReceita, uf, codParc, codProduto, periodos=periodos,
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
    list_historico_clientes_por_perfil,
    list_historico_cliente_produtos,
    list_historico_cliente_produto_mensal,
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
    dataInicio=None,
    dataFim=None,
    projetos=None,
    periodos=None,
    perfis=None,
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
        "dataInicio": dataInicio,
        "dataFim": dataFim,
        "projetos": _csv_or_list_historico_clientes(projetos),
        "periodos": _csv_or_list_historico_clientes(periodos),
        "perfis": _csv_or_list_historico_clientes(perfis),
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
    dataInicio: str | None = None,
    dataFim: str | None = None,
    periodos: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    perfis: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(
        anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos, dataInicio, dataFim, projetos, periodos=periodos, perfis=perfis,
    )
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
    dataInicio: str | None = None,
    dataFim: str | None = None,
    periodos: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    perfis: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(
        anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos, dataInicio, dataFim, projetos, periodos=periodos, perfis=perfis,
    )
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
    dataInicio: str | None = None,
    dataFim: str | None = None,
    periodos: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    perfis: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(
        anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos, dataInicio, dataFim, projetos, periodos=periodos, perfis=perfis,
    )
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
    dataInicio: str | None = None,
    dataFim: str | None = None,
    periodos: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    perfis: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(
        anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos, dataInicio, dataFim, projetos, periodos=periodos, perfis=perfis,
    )
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
    dataInicio: str | None = None,
    dataFim: str | None = None,
    periodos: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    perfis: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(
        anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos, dataInicio, dataFim, projetos, periodos=periodos, perfis=perfis,
    )
    return list_historico_clientes_por_segmento(filtros)


@app.get("/api/historico-clientes/por-perfil")
def api_historico_clientes_por_perfil(
    anos: list[int] | None = Query(default=None),
    meses: list[int] | None = Query(default=None),
    codParcs: list[int] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    ufs: list[str] | None = Query(default=None),
    codProdutos: list[str] | None = Query(default=None),
    dataInicio: str | None = None,
    dataFim: str | None = None,
    periodos: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    perfis: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(
        anos, meses, codParcs, mercados, gruposProduto, vendedores, ufs, codProdutos, dataInicio, dataFim, projetos, periodos=periodos, perfis=perfis,
    )
    return list_historico_clientes_por_perfil(filtros)


@app.get("/api/historico-clientes/clientes/{cod_parc}/produtos")
def api_historico_cliente_produtos(
    cod_parc: int,
    anos: list[int] | None = Query(default=None),
    meses: list[int] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    dataInicio: str | None = None,
    dataFim: str | None = None,
    periodos: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    perfis: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(
        anos, meses, None, mercados, gruposProduto, vendedores, None, None, dataInicio, dataFim, projetos, periodos=periodos, perfis=perfis,
    )
    return list_historico_cliente_produtos(cod_parc, filtros)


@app.get("/api/historico-clientes/clientes/{cod_parc}/produtos/{cod_produto}/mensal")
def api_historico_cliente_produto_mensal(
    cod_parc: int,
    cod_produto: str,
    anos: list[int] | None = Query(default=None),
    meses: list[int] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    dataInicio: str | None = None,
    dataFim: str | None = None,
    periodos: list[str] | None = Query(default=None),
    projetos: list[str] | None = Query(default=None),
    perfis: list[str] | None = Query(default=None),
):
    filtros = _build_historico_clientes_filtros(
        anos, meses, None, mercados, gruposProduto, vendedores, None, None, dataInicio, dataFim, projetos, periodos=periodos, perfis=perfis,
    )
    return list_historico_cliente_produto_mensal(cod_parc, cod_produto, filtros)


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
    codParcs=None,
    codProdutos=None,
    uf=None,
    periodos=None,
):
    filtros = {
        "mercados": _csv_or_list_snapshot(mercados),
        "vendedores": _csv_or_list_snapshot(vendedores),
        "projetos": _csv_or_list_snapshot(projetos),
        "gruposProduto": _csv_or_list_snapshot(gruposProduto) or _csv_or_list_snapshot(grupos_produto),
        "tiposReceita": _csv_or_list_snapshot(tiposReceita) or _csv_or_list_snapshot(tipos_receita),
        "dataInicio": dataInicio or data_inicio,
        "dataFim": dataFim or data_fim,
        "periodos": _csv_or_list_snapshot(periodos),
        "codParc": codParc or cod_parc,
        "codParcs": codParcs or ([codParc or cod_parc] if (codParc or cod_parc) is not None else []),
        "codProdutos": codProdutos or [],
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
    periodos: list[str] | None = Query(default=None),
    cod_parc: int | None = None,
    codParc: int | None = None,
    codParcs: list[int] | None = Query(default=None),
    codProdutos: list[int] | None = Query(default=None),
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
        codParcs=codParcs,
        codProdutos=codProdutos,
        uf=uf,
        periodos=periodos,
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
    periodos: list[str] | None = Query(default=None),
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
        periodos=periodos,
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
    codParcs=None,
    gruposProduto=None,
    codProdutos=None,
    periodos=None,
):
    filtros = {
        "dataInicio": dataInicio or data_inicio,
        "dataFim": dataFim or data_fim,
        "periodos": _csv_or_list_recorrentes(periodos),
        "mercados": _csv_or_list_recorrentes(mercados),
        "vendedores": _csv_or_list_recorrentes(vendedores),
        "codParc": codParc or cod_parc,
        "codParcs": codParcs or ([codParc or cod_parc] if (codParc or cod_parc) is not None else []),
        "gruposProduto": _csv_or_list_recorrentes(gruposProduto),
        "codProdutos": codProdutos or [],
    }
    return {key: value for key, value in filtros.items() if value not in (None, [], "")}


@app.get("/api/recorrentes/filtros")
def api_recorrentes_filtros():
    return get_recorrentes_filtros()


@app.get("/api/recorrentes/kpis")
def api_recorrentes_kpis(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    codParc: int | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    cod_parc: int | None = None,
    codParcs: list[int] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    codProdutos: list[int] | None = Query(default=None),
):
    filtros = _build_recorrentes_filtros(dataInicio, dataFim, mercados, vendedores, codParc, data_inicio, data_fim, cod_parc, codParcs, gruposProduto, codProdutos, periodos=periodos)
    return get_recorrentes_kpis(filtros)


@app.get("/api/recorrentes/tabela")
def api_recorrentes_tabela(
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    codParc: int | None = None,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    cod_parc: int | None = None,
    codParcs: list[int] | None = Query(default=None),
    gruposProduto: list[str] | None = Query(default=None),
    codProdutos: list[int] | None = Query(default=None),
):
    filtros = _build_recorrentes_filtros(dataInicio, dataFim, mercados, vendedores, codParc, data_inicio, data_fim, cod_parc, codParcs, gruposProduto, codProdutos, periodos=periodos)
    return list_recorrentes_tabela(filtros)


@app.get("/api/recorrentes/produtos/{cod_parc}")
def api_recorrentes_produtos(
    cod_parc: int,
    dataInicio: str | None = Query(default="2026-01-01"),
    dataFim: str | None = Query(default="2026-12-31"),
    periodos: list[str] | None = Query(default=None),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
    data_inicio: str | None = None,
    data_fim: str | None = None,
):
    filtros = _build_recorrentes_filtros(dataInicio, dataFim, mercados, vendedores, None, data_inicio, data_fim, None, periodos=periodos)
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
# Placar Funil Comercial — endpoints REST
# Exige só sessão autenticada (admin ou vendedor) — sem checagem de role.
# =============================================================================

from app.database import get_funil_scorecard

_FUNIL_SCORECARD_RECORTES_VALIDOS = ("semana_atual", "semana_anterior", "mes_atual", "mes_anterior")


def _require_authenticated(request: Request) -> dict:
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return user


@app.get("/api/funil-scorecard/dashboard", tags=["Placar Funil Comercial"])
def api_funil_scorecard_dashboard(request: Request, recorte: str = "semana_anterior"):
    _require_authenticated(request)
    if recorte not in _FUNIL_SCORECARD_RECORTES_VALIDOS:
        raise HTTPException(status_code=400, detail="Recorte inválido")
    return get_funil_scorecard(recorte)


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
from typing import Any as _ChatAny

from app.database import (
    get_chat_sessions,
    get_chat_history,
    save_chat_message,
    clear_chat_history,
    get_agent_database_schema,
    execute_agent_sql,
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

## DADOS DE FATURAMENTO / FORECAST / PROJETOS (tabela `fato_vendas`)

Campos principais: `valor_pendente` (valor financeiro), `qtd_pendente_kg` (volume), `dt_entrega_cliente` (EIXO TEMPORAL PRINCIPAL — use em todo GROUP BY e filtro de período/ano/mês, para ficar consistente com os dashboards do sistema; não use `dt_prev_entrega_embarque` nem `dt_neg` para isso), `nome_vendedor`, `mercado_vendas`, `projeto`, `grupo_produto`, `RAZAOSOCIAL` (nome do cliente), `cod_parc`, `nome_produto`, `cod_produto`, `uf`, `cod_top`, `[top]` (nome reservado — sempre usar colchetes), `tipo_receita`, `flag_devolucao`.

⚠️ REGRA CRÍTICA: o campo `tipo_receita` está desatualizado no banco. NUNCA o use para classificar o tipo de operação. Use sempre `cod_top` como única fonte de verdade:
- "Vendas Firmes" = `cod_top IN (1101,1125,1121,1133,1001,1013,1011,1172,1012,1202,1201,1299,1204)` (já inclui devoluções, que têm valor negativo e tornam o resultado líquido automaticamente).
- "Forecast" = `cod_top = 1020`.
- "Projetos" = `cod_top = 1025`.
- Nunca agrupar Forecast com Projetos — são categorias distintas.

FILTRO BASE obrigatório em toda query de `fato_vendas` (exclui estoque mínimo / demanda interna PCP):
`(cod_top IS NULL OR cod_top != 1023) AND ([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')`

Campo `projeto` (dimensão do CLIENTE, independente de `cod_top`/`tipo_receita`): `'NOVOS PROJETOS'` = cliente comprando aquele produto há menos de 12 meses; `'RECORRENTES'` = há mais de 12 meses; `'TESTE INDUSTRIAL'` = testes de cliente. Por padrão, os dashboards do sistema (ex.: "Por Vendedor") NÃO excluem `'TESTE INDUSTRIAL'` automaticamente — só filtram por `projeto` quando o usuário ativa esse filtro explicitamente na tela. Para que os números do chat fiquem consistentes com os dashboards, NÃO adicione filtro de `projeto` a menos que o usuário peça explicitamente (ex.: "só recorrentes", "excluindo teste industrial", "apenas novos projetos"). Antes de filtrar por `projeto`, confira os valores reais com `SELECT DISTINCT projeto FROM fato_vendas`.

Template de query para separar faturamento por categoria:
```sql
SELECT
  CASE
    WHEN cod_top IN (1101,1125,1121,1133,1001,1013,1011,1172,1012,1202,1201,1299,1204) THEN 'Vendas Firmes'
    WHEN cod_top = 1020 THEN 'Forecast'
    WHEN cod_top = 1025 THEN 'Projetos'
    ELSE 'Outros'
  END AS categoria,
  SUM(valor_pendente) AS faturamento
FROM fato_vendas
WHERE (cod_top IS NULL OR cod_top != 1023)
  AND ([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')
  AND dt_entrega_cliente >= '2026-01-01' AND dt_entrega_cliente < '2027-01-01'
GROUP BY CASE WHEN cod_top IN (1101,1125,1121,1133,1001,1013,1011,1172,1012,1202,1201,1299,1204) THEN 'Vendas Firmes' WHEN cod_top = 1020 THEN 'Forecast' WHEN cod_top = 1025 THEN 'Projetos' ELSE 'Outros' END
```

`nome_vendedor` e `RAZAOSOCIAL` são texto livre; `nome_vendedor` segue o padrão `"<código> - <NOME>"` (ex.: `"5 - JULIA ALBERTI"`). Nunca filtre esses campos com igualdade exata (`=`); use sempre `LIKE '%trecho%'`. Se o `LIKE` não retornar nenhuma linha, faça um `SELECT DISTINCT` para confirmar o valor exato antes de concluir que não há dados — não assuma R$ 0,00 sem essa verificação.

`orcamento_2026` tem a mesma estrutura de `fato_vendas` e representa a meta/orçamento; atingimento (%) = `SUM(fato_vendas.valor_pendente) / NULLIF(SUM(orcamento_2026.valor_pendente),0) * 100`.

## CRM BITRIX24

Para perguntas sobre funil, negócios, etapas, pipelines, follow-up, atividades, leads, responsáveis, negócios parados e performance CRM, use as tabelas `crm_*`: `crm_deals`, `crm_users`, `crm_deal_stages`, `crm_pipelines`, `crm_leads`, `crm_tasks`, `crm_deal_stage_history`.

Regras críticas:
- Funil Comercial principal: `category_id = '0'` ou `category_id IS NULL`; Marca Própria/Private Label: `category_id = '31'`. Ignorar nas análises os pipelines 15, 23 e 25, salvo pedido explícito.
- Negócios em andamento: `stage_semantic_id = 'P'`. Ganhos: `'S'`. Perdidos: `'F'`.
- "Sem atividade"/"sem follow-up"/"parados" devem usar `last_activity_time` de `crm_deals`, nunca `crm_tasks` (tarefas abertas não representam o histórico completo). Sem atividade há mais de 15 dias é alerta; mais de 30 é crítico; mais de 60 é estagnado.
- Opportunity = faturamento anual estimado do cliente, não o valor de um pedido único.
- Para correlacionar com faturamento: JOIN por nome (`crm_deals.title`/empresa do negócio com `RAZAOSOCIAL` de `fato_vendas`), pois não há chave numérica comum entre CRM e ERP.

## COMO RESPONDER

Consulte o banco com `execute_sql` antes de responder qualquer pergunta envolvendo valores, rankings, contagens, percentuais, funil, faturamento, forecast, clientes, produtos, vendedores ou CRM. Pode encadear múltiplas queries. Prefira queries agregadas (`GROUP BY`, `COUNT`, `SUM`, `AVG`, `TOP`). Use sintaxe SQL Server/T-SQL (nunca SQLite — sem `JULIANDAY`/`strftime`, use `DATEDIFF`, `YEAR`, `MONTH`, `FORMAT`). Se uma query falhar por nome de coluna/tabela, corrija e tente novamente. Não invente dados: se a base não tiver informação suficiente, diga exatamente o que faltou.

FORMATAÇÃO DA RESPOSTA: responda sempre em português do Brasil, em texto corrido. O frontend exibe a resposta como texto puro (sem renderizar markdown), então NUNCA use `**negrito**`, tabelas, `#` títulos ou outros marcadores — eles aparecem como caracteres literais. Use apenas parágrafos, travessão para listas e valores em R$ 1.234.567,89 / percentuais com uma casa decimal.
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
        "com acesso aos dados da base de produção neste momento. Verifique se ANTHROPIC_API_KEY está configurada, "
        "se a API consegue conectar no SQL Server e se o banco conectado contém tabelas/views com colunas de valor e data para faturamento."
    )
    if error_detail:
        return f"{base}\n\nDetalhe técnico: {error_detail}"
    return base


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


_ANTHROPIC_TOOLS = [
    {
        "name": "execute_sql",
        "description": "Executa uma consulta SELECT/WITH segura no SQL Server de produção e retorna linhas em JSON.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Consulta SQL Server somente leitura. Use SELECT ou WITH. Use TOP para limitar listas detalhadas.",
                }
            },
            "required": ["query"],
        },
    }
]


def _get_anthropic_client():
    api_key = _chat_os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY não configurada no ambiente da API Python")
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def _call_anthropic_sql_agent(message: str, history: list[dict] | None) -> str:
    model = _chat_os.getenv("ANTHROPIC_CHAT_MODEL", "claude-sonnet-4-6")
    client = _get_anthropic_client()

    messages: list[dict] = [
        *_chat_normalize_model_history(history),
        {"role": "user", "content": message},
    ]
    system_prompt = _chat_build_system_prompt()

    for _round in range(_CHAT_MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            tools=_ANTHROPIC_TOOLS,
            messages=messages,
            temperature=0.1,
        )

        messages.append({"role": "assistant", "content": response.content})

        tool_use_blocks = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
        if not tool_use_blocks:
            text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
            final = "\n".join(part.strip() for part in text_parts if part and part.strip())
            if final:
                return final
            raise RuntimeError("Anthropic não retornou resposta final")

        tool_results = []
        for block in tool_use_blocks:
            if block.name != "execute_sql":
                result = {"erro": f"Ferramenta desconhecida: {block.name}"}
            else:
                query = str((block.input or {}).get("query") or "")
                result = execute_agent_sql(query)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": _chat_json.dumps(result, ensure_ascii=False, default=str),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=messages + [
            {
                "role": "user",
                "content": "Finalize a resposta com base nos resultados já obtidos. Se não houver dados suficientes, explique a limitação.",
            }
        ],
        temperature=0.1,
    )
    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    final = "\n".join(part.strip() for part in text_parts if part and part.strip())
    if not final:
        raise RuntimeError("Limite de rodadas de ferramenta atingido sem resposta final")
    return final



def _chat_qg_generate_answer(message: str, history: list[dict] | None = None) -> dict:
    try:
        answer = _call_anthropic_sql_agent(message, history)
    except Exception as exc:
        import anthropic

        if isinstance(exc, anthropic.APIStatusError):
            answer = _chat_fallback_answer(message, f"Anthropic HTTP {exc.status_code}: {exc.message}")
        else:
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


# =============================================================================
# Geração de Listas (CRM) — lógica embutida neste processo (app/geracao_listas/),
# sem depender de nenhum serviço/porta fora deste repo. Autenticação via cookie
# de sessão (mesmo padrão do resto desta API), created_by sempre injetado do
# usuário logado (nunca vem do client), conversão snake_case <-> camelCase.
# =============================================================================

from app.geracao_listas import service as gl_service

_CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _require_authenticated_user(request: Request) -> dict:
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return user


def _snake_to_camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(part.title() for part in rest)


def _camel_to_snake(key: str) -> str:
    return _CAMEL_BOUNDARY_RE.sub("_", key).lower()


def _camelize(obj):
    if isinstance(obj, dict):
        return {_snake_to_camel(k): _camelize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_camelize(v) for v in obj]
    return obj


def _snakeify(obj):
    if isinstance(obj, dict):
        return {_camel_to_snake(k): _snakeify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_snakeify(v) for v in obj]
    return obj


class GLCriarCardRequest(BaseModel):
    titulo: str | None = None


class GLChatBriefingRequest(BaseModel):
    message: str
    history: list = Field(default_factory=list)


class GLFinalizarBriefingRequest(BaseModel):
    briefing: dict
    conversa: list = Field(default_factory=list)


class GLClassificarRequest(BaseModel):
    arquivoBase64: str | None = None
    nomeArquivo: str | None = None
    textoColado: str | None = None


@app.get("/api/geracao-listas/cards", tags=["Geração de Listas"])
def api_gl_listar_cards(request: Request, todas: bool = False):
    # Decisão do Ramon: por padrão só as próprias listas (mesmo critério de nome
    # usado na exclusão); ADMIN pode passar ?todas=true pra ver o histórico
    # completo do time.
    user = _require_authenticated_user(request)
    cards = _camelize(gl_service.listar_cards())
    if todas and user.get("role") == "ADMIN":
        return cards
    nome = (user["name"] or "").strip().lower()
    return [c for c in cards if (c.get("createdBy") or "").strip().lower() == nome]


@app.get("/api/geracao-listas/cards/{card_id}", tags=["Geração de Listas"])
def api_gl_obter_card(card_id: int, request: Request):
    _require_authenticated_user(request)
    card = gl_service.obter_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card não encontrado")
    return _camelize(card)


@app.post("/api/geracao-listas/cards/validacao", tags=["Geração de Listas"])
def api_gl_criar_card(payload: GLCriarCardRequest, request: Request):
    user = _require_authenticated_user(request)
    card_id = gl_service.criar_card_validacao(payload.titulo, user["name"])
    return {"cardId": card_id}


@app.delete("/api/geracao-listas/cards/{card_id}", tags=["Geração de Listas"])
def api_gl_excluir_card(card_id: int, request: Request):
    # Decisão do Ramon: só quem criou a lista pode excluí-la, com bypass pra
    # ADMIN (pra poder limpar lixo/teste de qualquer vendedora - bate com o
    # botão que o frontend já implementou como createdBy===nome OU role===
    # ADMIN). created_by é injetado a partir de user["name"] na criação
    # (criarCardValidacao / finalizarBriefing), nunca vem do client - então
    # comparar contra o nome do usuário logado é confiável para cards criados
    # por aqui. Cards antigos (created_by = texto livre digitado) só são
    # excluíveis por não-admin se o texto bater exatamente com o nome de conta
    # (case-insensitive).
    user = _require_authenticated_user(request)
    if user.get("role") != "ADMIN":
        dono = gl_service.obter_card_dono(card_id)
        if dono is None:
            raise HTTPException(status_code=404, detail="Card não encontrado")
        if (dono or "").strip().lower() != (user["name"] or "").strip().lower():
            raise HTTPException(status_code=403, detail="Só quem criou esta lista pode excluí-la")
    gl_service.excluir_card(card_id)
    return {"ok": True}


@app.post("/api/geracao-listas/cards/{card_id}/classificar", tags=["Geração de Listas"])
def api_gl_classificar(card_id: int, payload: GLClassificarRequest, request: Request):
    _require_authenticated_user(request)
    return _camelize(gl_service.classificar(card_id, payload.arquivoBase64, payload.textoColado))


@app.post("/api/geracao-listas/cards/{card_id}/exportar", tags=["Geração de Listas"])
def api_gl_exportar(card_id: int, request: Request):
    _require_authenticated_user(request)
    resultado = gl_service.exportar_excel(card_id)
    if resultado is None:
        raise HTTPException(status_code=404, detail="Lista não encontrada ou ainda não classificada")
    return _camelize(resultado)


@app.get("/api/geracao-listas/buscar", tags=["Geração de Listas"])
def api_gl_buscar(request: Request, nome: str, cnpj: str = ""):
    _require_authenticated_user(request)
    return _camelize(gl_service.buscar_empresa(nome, cnpj))


@app.post("/api/geracao-listas/briefing/chat", tags=["Geração de Listas"])
def api_gl_chat_briefing(payload: GLChatBriefingRequest, request: Request):
    _require_authenticated_user(request)
    resultado = gl_service.chat_briefing(payload.message, _snakeify(payload.history))
    return _camelize(resultado)


@app.post("/api/geracao-listas/briefing/finalizar", tags=["Geração de Listas"])
def api_gl_finalizar_briefing(payload: GLFinalizarBriefingRequest, request: Request):
    user = _require_authenticated_user(request)
    resultado = gl_service.finalizar_briefing(_snakeify(payload.briefing), _snakeify(payload.conversa), user["name"])
    return _camelize(resultado)


# =============================================================================
# Movimentação de Clientes e Produtos — Abertos/Perdidos e Lançados/Descontinuados
# =============================================================================

from app.database import (
    get_movimentacao_clientes,
    get_movimentacao_produtos,
    get_movimentacao_cliente_produtos,
    get_movimentacao_produto_clientes,
)


@app.get("/api/movimentacao/clientes", tags=["Movimentação"])
def api_movimentacao_clientes(
    ano: int = Query(..., ge=2000, le=2100),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
):
    try:
        return get_movimentacao_clientes(ano, mercados, vendedores)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao calcular movimentação de clientes: {error}",
        )


@app.get("/api/movimentacao/produtos", tags=["Movimentação"])
def api_movimentacao_produtos(
    ano: int = Query(..., ge=2000, le=2100),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
):
    try:
        return get_movimentacao_produtos(ano, mercados, vendedores)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao calcular movimentação de produtos: {error}",
        )


@app.get("/api/movimentacao/clientes/{cod_parc}/produtos", tags=["Movimentação"])
def api_movimentacao_cliente_produtos(
    cod_parc: int,
    ano: int = Query(..., ge=2000, le=2100),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
):
    try:
        return get_movimentacao_cliente_produtos(cod_parc, ano, mercados, vendedores)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar produtos do cliente: {error}",
        )


@app.get("/api/movimentacao/produtos/{cod_produto}/clientes", tags=["Movimentação"])
def api_movimentacao_produto_clientes(
    cod_produto: int,
    ano: int = Query(..., ge=2000, le=2100),
    mercados: list[str] | None = Query(default=None),
    vendedores: list[str] | None = Query(default=None),
):
    try:
        return get_movimentacao_produto_clientes(cod_produto, ano, mercados, vendedores)
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar clientes do produto: {error}",
        )


# =============================================================================
# Tarefas — acompanhamento manual de variações identificadas em Comparativo
# Semanal, Movimentação de Clientes e Produtos e Recorrentes R×O.
# =============================================================================

from fastapi import Query
from app.database import (
    list_tasks,
    get_task,
    create_task,
    update_task,
)

TASK_ORIGENS_VALIDAS = ("COMPARATIVO_SEMANAL", "MOVIMENTACAO_CLIENTES_PRODUTOS", "RECORRENTES_RXO")
TASK_STATUSES_VALIDOS = ("PENDENTE", "EM_ANALISE", "AGUARDANDO_RETORNO", "CONCLUIDA")


def _require_task_user(request: Request) -> dict:
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Não autenticado")
    return user


class TaskCreateRequest(BaseModel):
    origem: str
    tipoOcorrencia: str = Field(min_length=1)
    codParc: int | None = None
    razaoSocial: str | None = None
    codProduto: int | None = None
    nomeProduto: str | None = None
    infoVariacao: str | None = None
    origemUrl: str | None = None
    fato: str = Field(min_length=1)
    responsavelId: int
    prazo: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class TaskUpdateRequest(BaseModel):
    responsavelId: int | None = None
    prazo: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str | None = None
    causa: str | None = None
    acoes: str | None = None


@app.get("/api/tasks", tags=["Tarefas"])
def api_list_tasks(
    request: Request,
    origem: str | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    responsavelId: int | None = Query(default=None),
    codParc: int | None = Query(default=None),
    codProduto: int | None = Query(default=None),
):
    _require_task_user(request)
    try:
        return list_tasks({
            "origem": origem,
            "status": status,
            "responsavelId": responsavelId,
            "codParc": codParc,
            "codProduto": codProduto,
        })
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Erro ao listar tarefas: {error}")


@app.get("/api/tasks/{task_id}", tags=["Tarefas"])
def api_get_task(task_id: int, request: Request):
    _require_task_user(request)
    try:
        task = get_task(task_id)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Erro ao buscar tarefa: {error}")
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task


@app.post("/api/tasks", tags=["Tarefas"])
def api_create_task(payload: TaskCreateRequest, request: Request):
    user = _require_task_user(request)
    if payload.origem not in TASK_ORIGENS_VALIDAS:
        raise HTTPException(status_code=400, detail="Origem inválida.")
    try:
        return create_task(payload.model_dump(), int(user["id"]))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Erro ao criar tarefa: {error}")


@app.patch("/api/tasks/{task_id}", tags=["Tarefas"])
def api_update_task(task_id: int, payload: TaskUpdateRequest, request: Request):
    user = _require_task_user(request)
    if payload.status is not None and payload.status not in TASK_STATUSES_VALIDOS:
        raise HTTPException(status_code=400, detail="Status inválido.")
    body = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    try:
        task = update_task(task_id, body, int(user["id"]))
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar tarefa: {error}")
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task