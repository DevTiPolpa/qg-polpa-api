"""
Database layer completo da API QG Polpa Brasil.

Arquivo consolidado para substituir `app/database.py` na API Python/FastAPI local.
Inclui conexão SQL Server, autenticação/usuários, Metas 2026, B2B, Por Vendedor
original REST e Dashboard Executivo original REST.
"""

import os
from datetime import datetime
from decimal import Decimal
from typing import Any

import pyodbc
from dotenv import load_dotenv


load_dotenv()


def get_connection_string() -> str:
    driver = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
    server = os.getenv("DB_SERVER")
    port = os.getenv("DB_PORT", "1433")
    database = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")

    missing_vars = []

    if not server:
        missing_vars.append("DB_SERVER")
    if not database:
        missing_vars.append("DB_NAME")
    if not user:
        missing_vars.append("DB_USER")
    if not password:
        missing_vars.append("DB_PASSWORD")

    if missing_vars:
        raise RuntimeError(
            "Variáveis ausentes no .env: " + ", ".join(missing_vars)
        )

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
    )


def get_connection():
    connection_string = get_connection_string()
    return pyodbc.connect(connection_string, timeout=5)


def test_database_connection() -> dict:
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                DB_NAME() AS database_name,
                @@SERVERNAME AS server_name,
                GETDATE() AS server_datetime
            """
        )
        row = cursor.fetchone()

    return {
        "database_name": row.database_name,
        "server_name": row.server_name,
        "server_datetime": str(row.server_datetime),
    }


def fetch_all(query: str, params: tuple = ()) -> list[dict]:
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(query, params)

        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()

    return [dict(zip(columns, row)) for row in rows]


def list_database_tables() -> list[dict]:
    return fetch_all(
        """
        SELECT
            TABLE_SCHEMA AS table_schema,
            TABLE_NAME AS table_name,
            TABLE_TYPE AS table_type
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_SCHEMA, TABLE_NAME
        """
    )


def list_table_columns(table_name: str, table_schema: str = "dbo") -> list[dict]:
    return fetch_all(
        """
        SELECT
            COLUMN_NAME AS column_name,
            DATA_TYPE AS data_type,
            IS_NULLABLE AS is_nullable,
            CHARACTER_MAXIMUM_LENGTH AS max_length
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """,
        (table_schema, table_name),
    )



def list_users(limit: int = 50) -> list[dict]:
    return fetch_all(

        """
        SELECT TOP (?)
            id,
            name,
            email,
            role,
            ativo,
            must_change_password,
            created_at,
            updated_at,
            last_signed_in
        FROM dbo.users
        ORDER BY name   
        """, 
        (limit,), 
    )


def update_user(
    user_id: int,
    name: str | None = None,
    role: str | None = None,
    ativo: bool | None = None,
) -> None:
    sets = []
    params = []

    if name is not None:
        sets.append("name = ?")
        params.append(name)

    if role is not None:
        sets.append("role = ?")
        params.append(role)

    if ativo is not None:
        sets.append("ativo = ?")
        params.append(1 if ativo else 0)

    if not sets:
        return

    sets.append("updated_at = GETDATE()")
    params.append(user_id)

    query = f"""
        UPDATE dbo.users
        SET {", ".join(sets)}
        WHERE id = ?
    """

    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(query, tuple(params))
        connection.commit()



def create_user(
    name: str,
    email: str,
    password_hash: str,
    role: str,
) -> int:
    query = """
        INSERT INTO dbo.users (name, email, password_hash, role, ativo, must_change_password)
        OUTPUT INSERTED.id
        VALUES (?, ?, ?, ?, 1, 1)
    """

    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(query, (name, email, password_hash, role))
        row = cursor.fetchone()
        connection.commit()

    return int(row[0])


def reset_user_password(user_id: int, password_hash: str) -> None:
    query = """
        UPDATE dbo.users
        SET password_hash = ?,
            must_change_password = 1,
            updated_at = GETDATE()
        WHERE id = ?
    """

    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(query, (password_hash, user_id))
        connection.commit()  

def get_user_by_email(email: str) -> dict | None:
    rows = fetch_all(
        """
        SELECT
            id,
            name,
            email,
            password_hash,
            role,
            ativo,
            must_change_password,
            last_signed_in
        FROM dbo.users
        WHERE email = ?
        """,
        (email,),
    )

    return rows[0] if rows else None


def get_user_by_id(user_id: int) -> dict | None:
    rows = fetch_all(
        """
        SELECT
            id,
            name,
            email,
            password_hash,
            role,
            ativo,
            must_change_password,
            last_signed_in
        FROM dbo.users
        WHERE id = ?
        """,
        (user_id,),
    )

    return rows[0] if rows else None


def update_last_signed_in(user_id: int) -> None:
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE dbo.users
            SET last_signed_in = GETDATE()
            WHERE id = ?
            """,
            (user_id,),
        )
        connection.commit()


def update_password(user_id: int, password_hash: str) -> None:
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            UPDATE dbo.users
            SET password_hash = ?,
                must_change_password = 0,
                updated_at = GETDATE()
            WHERE id = ?
            """,
            (password_hash, user_id),
        )
        connection.commit()


# =============================================================================
# Metas 2026
# =============================================================================

def list_metas_2026(ano: str = "2026") -> list[dict]:
    """
    Lista metas cadastradas em dbo.metas_2026.

    Esta função pressupõe que o seu app/database.py já tenha uma função
    de conexão parecida com get_connection(). Se no seu arquivo o nome for
    diferente, reaproveite o mesmo padrão usado por list_users().
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            id,
            nome_vendedor,
            mes,
            valor_meta,
            projeto,
            mercado_vendas,
            created_at,
            updated_at
        FROM dbo.metas_2026
        WHERE mes LIKE ?
        ORDER BY nome_vendedor, mes, projeto
        """,
        f"{ano}-%",
    )

    rows = cursor.fetchall()
    metas: list[dict] = []

    for row in rows:
        metas.append({
            "id": int(row.id),
            "nomeVendedor": row.nome_vendedor,
            "mes": row.mes,
            "valorMeta": _serialize_decimal(row.valor_meta),
            "projeto": row.projeto,
            "mercadoVendas": row.mercado_vendas,
            "createdAt": _serialize_datetime(row.created_at),
            "updatedAt": _serialize_datetime(row.updated_at),
        })

    cursor.close()
    conn.close()
    return metas


def upsert_meta_2026(nome_vendedor: str, mes: str, valor_meta: float, projeto: str | None = None, mercado_vendas: str | None = None) -> None:
    """
    Cria ou atualiza meta usando a regra atual:
    nome_vendedor + mes + projeto + mercado_vendas.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        MERGE dbo.metas_2026 AS target
        USING (
            SELECT
                ? AS nome_vendedor,
                ? AS mes,
                ? AS projeto,
                ? AS mercado_vendas
        ) AS source
        ON target.nome_vendedor = source.nome_vendedor
           AND target.mes = source.mes
           AND (target.projeto = source.projeto OR (target.projeto IS NULL AND source.projeto IS NULL))
           AND (target.mercado_vendas = source.mercado_vendas OR (target.mercado_vendas IS NULL AND source.mercado_vendas IS NULL))
        WHEN MATCHED THEN
            UPDATE SET
                valor_meta = ?,
                updated_at = SYSDATETIME()
        WHEN NOT MATCHED THEN
            INSERT (nome_vendedor, mes, valor_meta, projeto, mercado_vendas, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, SYSDATETIME(), SYSDATETIME());
        """,
        nome_vendedor,
        mes,
        projeto,
        mercado_vendas,
        valor_meta,
        nome_vendedor,
        mes,
        valor_meta,
        projeto,
        mercado_vendas,
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_meta_2026(meta_id: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM dbo.metas_2026 WHERE id = ?", meta_id)
    conn.commit()
    cursor.close()
    conn.close()


# =============================================================================
# B2B — leitura operacional
# =============================================================================

def list_b2b_resumo(ano: str = "2026") -> list[dict]:
    """
    Lista resumo mensal da tabela dbo.B2B.

    Observações:
    - Esta função pressupõe que o app/database.py já tenha get_connection().
    - A consulta usa somente SELECT e agregações, sem qualquer escrita na B2B.
    - COALESCE(DTMOV, DTNEG) é usado como data operacional base.
    - ValorPendente é mantido com o nome original de indicador pendente, não como faturamento.
    """
    data_inicio = f"{ano}-01-01"
    data_fim = f"{int(ano) + 1}-01-01"

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            CONVERT(char(7), COALESCE(DTMOV, DTNEG), 120) AS ano_mes,
            COALESCE(VENDEDOR, 'SEM VENDEDOR') AS vendedor,
            COALESCE(PROJETO, 'SEM PROJETO') AS projeto,
            COALESCE(AD_MERCADO_VENDAS, 'SEM MERCADO') AS mercado_vendas,
            SUM(COALESCE(QTDNEG, 0)) AS quantidade_negociada,
            SUM(COALESCE(QTDENTREGUE, 0)) AS quantidade_entregue,
            SUM(COALESCE(PESOLIQ, 0)) AS peso_liquido,
            SUM(COALESCE(ValorPendente, 0)) AS valor_pendente,
            COUNT(DISTINCT NUNOTA) AS notas,
            COUNT(DISTINCT CODPARC) AS clientes
        FROM dbo.B2B
        WHERE COALESCE(DTMOV, DTNEG) >= ?
          AND COALESCE(DTMOV, DTNEG) < ?
        GROUP BY
            CONVERT(char(7), COALESCE(DTMOV, DTNEG), 120),
            COALESCE(VENDEDOR, 'SEM VENDEDOR'),
            COALESCE(PROJETO, 'SEM PROJETO'),
            COALESCE(AD_MERCADO_VENDAS, 'SEM MERCADO')
        ORDER BY ano_mes, vendedor, projeto, mercado_vendas;
        """,
        data_inicio,
        data_fim,
    )

    rows = cursor.fetchall()
    resumo: list[dict] = []

    for row in rows:
        resumo.append({
            "anoMes": row.ano_mes,
            "vendedor": row.vendedor,
            "projeto": row.projeto,
            "mercadoVendas": row.mercado_vendas,
            "quantidadeNegociada": _serialize_decimal(row.quantidade_negociada) or 0,
            "quantidadeEntregue": _serialize_decimal(row.quantidade_entregue) or 0,
            "pesoLiquido": _serialize_decimal(row.peso_liquido) or 0,
            "valorPendente": _serialize_decimal(row.valor_pendente) or 0,
            "notas": int(row.notas or 0),
            "clientes": int(row.clientes or 0),
        })

    cursor.close()
    conn.close()
    return resumo


# =============================================================================
# Por Vendedor — dados originais migrados para REST
# =============================================================================

PIPELINE_BLACKLIST = (6, 8)


def _serialize_datetime(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_decimal(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _number(value: Any) -> float:
    value = _serialize_decimal(value)
    return float(value or 0)


def _int(value: Any) -> int:
    return int(value or 0)


def _split_filter(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = str(value).split(",")
    return [str(item).strip() for item in raw_values if str(item).strip()]


def _build_in_clause(column: str, values: list[str], params: list[Any]) -> str | None:
    if not values:
        return None
    params.extend(values)
    return f"{column} IN ({','.join(['?'] * len(values))})"


def _normalize_filtros(filtros: dict | None) -> dict:
    filtros = filtros or {}
    return {
        "mercados": _split_filter(filtros.get("mercados") or filtros.get("mercado")),
        "vendedores": _split_filter(filtros.get("vendedores") or filtros.get("vendedor")),
        "projetos": _split_filter(filtros.get("projetos") or filtros.get("projeto")),
        "gruposProduto": _split_filter(filtros.get("gruposProduto") or filtros.get("grupoProduto")),
        "tiposReceita": _split_filter(filtros.get("tiposReceita") or filtros.get("tipoReceita")),
        "dataInicio": filtros.get("dataInicio"),
        "dataFim": filtros.get("dataFim"),
        "codParc": filtros.get("codParc"),
        "codProduto": filtros.get("codProduto"),
        "uf": filtros.get("uf"),
    }


def build_fato_vendas_where(filtros: dict | None, alias: str = "fv") -> tuple[str, list[Any]]:
    """Reproduz o buildWhere original da versão Node/tRPC."""
    f = _normalize_filtros(filtros)
    parts: list[str] = []
    params: list[Any] = []

    for clause in [
        _build_in_clause(f"{alias}.mercado_vendas", f["mercados"], params),
        _build_in_clause(f"{alias}.nome_vendedor", f["vendedores"], params),
        _build_in_clause(f"{alias}.projeto", f["projetos"], params),
        _build_in_clause(f"{alias}.grupo_produto", f["gruposProduto"], params),
    ]:
        if clause:
            parts.append(clause)

    tipos_receita = f["tiposReceita"]
    if "VENDA_FIRME" in tipos_receita and "DEVOLUCAO" not in tipos_receita:
        tipos_receita = [*tipos_receita, "DEVOLUCAO"]
    clause = _build_in_clause(f"{alias}.tipo_receita", tipos_receita, params)
    if clause:
        parts.append(clause)

    if f["dataInicio"]:
        parts.append(f"{alias}.dt_entrega_cliente >= ?")
        params.append(f["dataInicio"])
    if f["dataFim"]:
        parts.append(f"{alias}.dt_entrega_cliente <= ?")
        params.append(f["dataFim"])
    if f["codParc"]:
        parts.append(f"{alias}.cod_parc = ?")
        params.append(int(f["codParc"]))
    if f["codProduto"]:
        parts.append(f"{alias}.cod_produto = ?")
        params.append(int(f["codProduto"]))
    if f["uf"]:
        parts.append(f"{alias}.uf = ?")
        params.append(f["uf"])

    parts.append(f"({alias}.cod_top IS NULL OR {alias}.cod_top != 1023)")
    parts.append(f"({alias}.[top] IS NULL OR {alias}.[top] NOT LIKE '%ESTOQUE MINIM%')")

    return "WHERE " + " AND ".join(parts), params


def build_orcamento_where(filtros: dict | None) -> tuple[str, list[Any]]:
    f = _normalize_filtros(filtros)
    parts: list[str] = []
    params: list[Any] = []

    if f["dataInicio"]:
        parts.append("dt_prev_entrega_embarque >= ?")
        params.append(f["dataInicio"])
    if f["dataFim"]:
        parts.append("dt_prev_entrega_embarque <= ?")
        params.append(f["dataFim"])

    for column, values in [
        ("projeto", f["projetos"]),
        ("mercado_vendas", f["mercados"]),
        ("grupo_produto", f["gruposProduto"]),
    ]:
        clause = _build_in_clause(column, values, params)
        if clause:
            parts.append(clause)

    return ("WHERE " + " AND ".join(parts), params) if parts else ("", params)


def get_vendedores_kpis_original(filtros: dict | None = None) -> dict:
    clause, params = build_fato_vendas_where(filtros)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento_total,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume_total,
            COUNT(DISTINCT fv.cod_parc) AS clientes_ativos,
            COUNT(DISTINCT fv.cod_produto) AS produtos_vendidos,
            COUNT(*) AS total_registros,
            COALESCE(SUM(CASE WHEN fv.tipo_receita IN ('VENDA_FIRME','DEVOLUCAO') THEN fv.valor_pendente ELSE 0 END), 0) AS venda_firme,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'FORECAST' THEN fv.valor_pendente ELSE 0 END), 0) AS forecast,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'NOVO_PROJETO' THEN fv.valor_pendente ELSE 0 END), 0) AS novo_projeto
        FROM dbo.fato_vendas fv
        {clause}
        """,
        *params,
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    faturamento_total = _number(row.faturamento_total) if row else 0
    volume_total = _number(row.volume_total) if row else 0
    return {
        "faturamentoTotal": faturamento_total,
        "volumeTotal": volume_total,
        "precoMedio": faturamento_total / volume_total if volume_total else 0,
        "clientesAtivos": _int(row.clientes_ativos) if row else 0,
        "produtosVendidos": _int(row.produtos_vendidos) if row else 0,
        "totalRegistros": _int(row.total_registros) if row else 0,
        "vendaFirme": _number(row.venda_firme) if row else 0,
        "forecast": _number(row.forecast) if row else 0,
        "novoProjeto": _number(row.novo_projeto) if row else 0,
    }


def list_vendedores_evolucao_original(filtros: dict | None = None) -> list[dict]:
    clause, params = build_fato_vendas_where(filtros)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            FORMAT(fv.dt_entrega_cliente, 'yyyy-MM') AS mes,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COALESCE(SUM(CASE WHEN fv.tipo_receita IN ('VENDA_FIRME','DEVOLUCAO') THEN fv.valor_pendente ELSE 0 END), 0) AS venda_firme,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'FORECAST' THEN fv.valor_pendente ELSE 0 END), 0) AS forecast,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'NOVO_PROJETO' THEN fv.valor_pendente ELSE 0 END), 0) AS novo_projeto,
            COUNT(DISTINCT fv.cod_parc) AS clientes
        FROM dbo.fato_vendas fv
        {clause}
        GROUP BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        ORDER BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        """,
        *params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "mes": row.mes,
            "faturamento": _number(row.faturamento),
            "volume": _number(row.volume),
            "vendaFirme": _number(row.venda_firme),
            "forecast": _number(row.forecast),
            "novoProjeto": _number(row.novo_projeto),
            "clientes": _int(row.clientes),
        }
        for row in rows
    ]


def list_vendedores_performance_original(filtros: dict | None = None) -> list[dict]:
    clause, params = build_fato_vendas_where(filtros)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            fv.nome_vendedor AS nome_vendedor,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.cod_parc) AS clientes,
            COUNT(DISTINCT fv.cod_produto) AS produtos,
            COALESCE(SUM(CASE WHEN fv.tipo_receita IN ('VENDA_FIRME','DEVOLUCAO') THEN fv.valor_pendente ELSE 0 END), 0) AS venda_firme,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'FORECAST' THEN fv.valor_pendente ELSE 0 END), 0) AS forecast,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'NOVO_PROJETO' THEN fv.valor_pendente ELSE 0 END), 0) AS novo_projeto,
            COALESCE(SUM(CASE WHEN fv.projeto = 'Novo Projeto' THEN fv.valor_pendente ELSE 0 END), 0) AS fat_novo_projeto,
            COALESCE(SUM(CASE WHEN fv.projeto = 'Recorrente' THEN fv.valor_pendente ELSE 0 END), 0) AS fat_recorrente
        FROM dbo.fato_vendas fv
        {clause}
        GROUP BY fv.nome_vendedor
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        *params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "nomeVendedor": row.nome_vendedor,
            "faturamento": _number(row.faturamento),
            "volume": _number(row.volume),
            "clientes": _int(row.clientes),
            "produtos": _int(row.produtos),
            "vendaFirme": _number(row.venda_firme),
            "forecast": _number(row.forecast),
            "novoProjeto": _number(row.novo_projeto),
            "fatNovoProjeto": _number(row.fat_novo_projeto),
            "fatRecorrente": _number(row.fat_recorrente),
        }
        for row in rows
    ]


def list_vendedores_clientes_consolidados_original(filtros: dict | None = None, limit: int = 50) -> list[dict]:
    clause, params = build_fato_vendas_where(filtros)
    safe_limit = max(1, min(int(limit or 50), 500))
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT TOP ({safe_limit})
            fv.cod_parc AS cod_parc,
            COALESCE(dc.razao_social, fv.RAZAOSOCIAL) AS razao_social,
            fv.perfil_parceiro AS perfil_parceiro,
            fv.uf AS uf,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            MAX(CONVERT(VARCHAR, fv.dt_entrega_cliente, 23)) AS ultima_compra
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
        {clause}
        GROUP BY fv.cod_parc, dc.razao_social, fv.RAZAOSOCIAL, fv.perfil_parceiro, fv.uf
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        *params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "codParc": _int(row.cod_parc),
            "razaoSocial": row.razao_social,
            "perfilParceiro": row.perfil_parceiro,
            "uf": row.uf,
            "faturamento": _number(row.faturamento),
            "volume": _number(row.volume),
            "ultimaCompra": row.ultima_compra,
        }
        for row in rows
    ]


def list_vendedores_evolucao_por_tipo_original(filtros: dict | None = None) -> list[dict]:
    filtros_sem_tipo = dict(filtros or {})
    filtros_sem_tipo.pop("tiposReceita", None)
    filtros_sem_tipo.pop("tipoReceita", None)
    clause, params = build_fato_vendas_where(filtros_sem_tipo)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            FORMAT(fv.dt_entrega_cliente, 'yyyy-MM') AS mes,
            CASE WHEN fv.tipo_receita = 'DEVOLUCAO' THEN 'VENDA_FIRME' ELSE fv.tipo_receita END AS tipo_receita,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento
        FROM dbo.fato_vendas fv
        {clause}
          AND fv.tipo_receita IN ('VENDA_FIRME','FORECAST','NOVO_PROJETO','DEVOLUCAO')
        GROUP BY
            FORMAT(fv.dt_entrega_cliente, 'yyyy-MM'),
            CASE WHEN fv.tipo_receita = 'DEVOLUCAO' THEN 'VENDA_FIRME' ELSE fv.tipo_receita END
        ORDER BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        """,
        *params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "mes": row.mes,
            "tipoReceita": row.tipo_receita,
            "faturamento": _number(row.faturamento),
        }
        for row in rows
    ]


def list_metas_vendedores_original(filtros: dict | None = None) -> list[dict]:
    f = _normalize_filtros(filtros)
    parts: list[str] = []
    params: list[Any] = []

    for column, values in [
        ("projeto", f["projetos"]),
        ("mercado_vendas", f["mercados"]),
        ("nome_vendedor", f["vendedores"]),
    ]:
        clause = _build_in_clause(column, values, params)
        if clause:
            parts.append(clause)

    where = "WHERE " + " AND ".join(parts) if parts else ""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            nome_vendedor AS nome_vendedor,
            mes AS mes,
            CAST(valor_meta AS FLOAT) AS valor_meta,
            projeto AS projeto,
            mercado_vendas AS mercado_vendas
        FROM dbo.metas_2026
        {where}
        ORDER BY nome_vendedor, mes
        """,
        *params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "nomeVendedor": row.nome_vendedor,
            "mes": row.mes,
            "valorMeta": _number(row.valor_meta),
            "projeto": row.projeto,
            "mercadoVendas": row.mercado_vendas,
        }
        for row in rows
    ]


def get_orcamento_kpis_original(filtros: dict | None = None) -> dict:
    clause, params = build_orcamento_where(filtros)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(valor_pendente), 0) AS faturamento_total,
            COALESCE(SUM(qtd_pendente_kg), 0) AS volume_total,
            COUNT(*) AS total_registros,
            COUNT(DISTINCT cod_parc) AS clientes_unicos,
            COUNT(DISTINCT cod_produto) AS produtos_unicos
        FROM dbo.orcamento_2026
        {clause}
        """,
        *params,
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    faturamento_total = _number(row.faturamento_total) if row else 0
    volume_total = _number(row.volume_total) if row else 0
    return {
        "faturamentoTotal": faturamento_total,
        "volumeTotal": volume_total,
        "precoMedio": faturamento_total / volume_total if volume_total else 0,
        "totalRegistros": _int(row.total_registros) if row else 0,
        "clientesUnicos": _int(row.clientes_unicos) if row else 0,
        "produtosUnicos": _int(row.produtos_unicos) if row else 0,
    }


def list_orcamento_mensal_original(filtros: dict | None = None) -> list[dict]:
    clause, params = build_orcamento_where(filtros)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            FORMAT(dt_prev_entrega_embarque, 'yyyy-MM') AS mes,
            COALESCE(SUM(valor_pendente), 0) AS faturamento,
            COALESCE(SUM(qtd_pendente_kg), 0) AS volume
        FROM dbo.orcamento_2026
        {clause}
        GROUP BY FORMAT(dt_prev_entrega_embarque, 'yyyy-MM')
        ORDER BY FORMAT(dt_prev_entrega_embarque, 'yyyy-MM')
        """,
        *params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {"mes": row.mes, "faturamento": _number(row.faturamento), "volume": _number(row.volume)}
        for row in rows
    ]


def list_crm_mapping_vendedores_original() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT DISTINCT
            u.id AS id,
            LTRIM(RTRIM(u.name + ' ' + COALESCE(u.last_name, ''))) AS nome
        FROM dbo.crm_users u
        JOIN dbo.crm_deals d ON d.assigned_by_id = u.id
        WHERE CAST(COALESCE(d.category_id, '0') AS INT) NOT IN ({','.join(str(x) for x in PIPELINE_BLACKLIST)})
        ORDER BY nome
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [{"id": _int(row.id), "nome": row.nome} for row in rows]


def list_crm_kpis_por_vendedor_original() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            assigned_by_id AS crm_user_id,
            SUM(CASE WHEN stage_semantic_id = 'P' THEN 1 ELSE 0 END) AS em_andamento,
            COALESCE(SUM(CASE WHEN stage_semantic_id = 'P' THEN opportunity ELSE 0 END), 0) AS valor_andamento,
            SUM(CASE WHEN stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS ganhos,
            COALESCE(SUM(CASE WHEN stage_semantic_id = 'S' THEN opportunity ELSE 0 END), 0) AS valor_ganho,
            SUM(CASE WHEN stage_semantic_id = 'F' THEN 1 ELSE 0 END) AS perdidos,
            CASE
                WHEN SUM(CASE WHEN stage_semantic_id IN ('S','F') THEN 1 ELSE 0 END) = 0 THEN 0
                ELSE CAST(SUM(CASE WHEN stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS FLOAT)
                   / SUM(CASE WHEN stage_semantic_id IN ('S','F') THEN 1 ELSE 0 END) * 100
            END AS taxa_conversao,
            COALESCE(AVG(CASE
                WHEN stage_semantic_id = 'S' AND closedate IS NOT NULL AND date_create IS NOT NULL
                THEN DATEDIFF(day, TRY_CAST(date_create AS DATE), TRY_CAST(closedate AS DATE))
                ELSE NULL
            END), 0) AS ciclo_ganhos
        FROM dbo.crm_deals
        WHERE CAST(COALESCE(category_id, '0') AS INT) NOT IN ({','.join(str(x) for x in PIPELINE_BLACKLIST)})
          AND assigned_by_id IS NOT NULL
        GROUP BY assigned_by_id
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [
        {
            "crmUserId": _int(row.crm_user_id),
            "emAndamento": _int(row.em_andamento),
            "valorAndamento": _number(row.valor_andamento),
            "ganhos": _int(row.ganhos),
            "valorGanho": _number(row.valor_ganho),
            "perdidos": _int(row.perdidos),
            "taxaConversao": _number(row.taxa_conversao),
            "cicloGanhos": _number(row.ciclo_ganhos),
        }
        for row in rows
    ]


def get_vendedores_original_resumo(filtros: dict | None = None, limit_clientes: int = 50) -> dict:
    """Retorna em uma chamada as principais coleções necessárias para a página Vendedores."""
    return {
        "kpis": get_vendedores_kpis_original(filtros),
        "evolucaoMensal": list_vendedores_evolucao_original(filtros),
        "evolucaoPorTipo": list_vendedores_evolucao_por_tipo_original(filtros),
        "vendedores": list_vendedores_performance_original(filtros),
        "clientesConsolidados": list_vendedores_clientes_consolidados_original(filtros, limit_clientes),
        "metas": list_metas_vendedores_original(filtros),
        "orcamentoKpis": get_orcamento_kpis_original(filtros),
        "orcamentoMensal": list_orcamento_mensal_original(filtros),
        "crmMapping": list_crm_mapping_vendedores_original(),
        "crmKpis": list_crm_kpis_por_vendedor_original(),
    }



# =============================================================================
# Por Vendedor — mix de produtos por cliente para expansão lazy
# =============================================================================

def list_vendedores_cliente_mix_original(cod_parc: int, filtros: dict | None = None) -> list[dict]:
    filtros_sem_cliente = dict(filtros or {})
    filtros_sem_cliente.pop("codParc", None)
    clause, params = build_fato_vendas_where(filtros_sem_cliente, "fv")
    add_cond = clause.replace("WHERE ", "AND ", 1) if clause else ""

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            fv.cod_produto AS codProduto,
            COALESCE(dp.nome_produto, fv.nome_produto) AS nomeProduto,
            fv.grupo_produto AS grupoProduto,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.nro_unico) AS pedidos,
            MAX(CONVERT(VARCHAR, fv.dt_entrega_cliente, 23)) AS ultimaCompra
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
        WHERE fv.cod_parc = ?
          AND fv.flag_devolucao = 0
          {add_cond}
        GROUP BY fv.cod_produto, dp.nome_produto, fv.nome_produto, fv.grupo_produto
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        int(cod_parc),
        *params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "codProduto": _int(row.codProduto),
            "nomeProduto": row.nomeProduto,
            "grupoProduto": row.grupoProduto,
            "faturamento": _number(row.faturamento),
            "volume": _number(row.volume),
            "pedidos": _int(row.pedidos),
            "ultimaCompra": _serialize_datetime(row.ultimaCompra),
        }
        for row in rows
    ]



# =============================================================================
# Dashboard Executivo — dados originais migrados para REST
# =============================================================================

def _dash_number(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def _dash_int(value: Any) -> int:
    return int(value or 0)


def _dash_shift_year(iso_date: str | None, delta: int = -1) -> str | None:
    if not iso_date:
        return None
    try:
        dt = datetime.strptime(str(iso_date)[:10], "%Y-%m-%d")
        return dt.replace(year=dt.year + delta).strftime("%Y-%m-%d")
    except ValueError:
        return iso_date


def _dash_split_filter(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, (list, tuple)) else str(value).split(",")
    return [str(item).strip() for item in raw_values if str(item).strip()]


def _dash_build_in_clause(column: str, values: list[str], params: list[Any]) -> str | None:
    if not values:
        return None
    params.extend(values)
    return f"{column} IN ({','.join(['?'] * len(values))})"


def _dash_normalize_filtros(filtros: dict | None) -> dict:
    filtros = filtros or {}
    return {
        "mercados": _dash_split_filter(filtros.get("mercados") or filtros.get("mercado")),
        "vendedores": _dash_split_filter(filtros.get("vendedores") or filtros.get("vendedor")),
        "projetos": _dash_split_filter(filtros.get("projetos") or filtros.get("projeto")),
        "gruposProduto": _dash_split_filter(filtros.get("gruposProduto") or filtros.get("grupoProduto")),
        "tiposReceita": _dash_split_filter(filtros.get("tiposReceita") or filtros.get("tipoReceita")),
        "dataInicio": filtros.get("dataInicio"),
        "dataFim": filtros.get("dataFim"),
        "codParc": filtros.get("codParc"),
        "codProduto": filtros.get("codProduto"),
        "uf": filtros.get("uf"),
    }


def _dash_build_fato_where(filtros: dict | None, alias: str = "fv", ignore_tipo_receita: bool = False) -> tuple[str, list[Any]]:
    """Replica o buildWhere original do backend Node/tRPC para fato_vendas."""
    f = _dash_normalize_filtros(filtros)
    parts: list[str] = []
    params: list[Any] = []

    for clause in [
        _dash_build_in_clause(f"{alias}.mercado_vendas", f["mercados"], params),
        _dash_build_in_clause(f"{alias}.nome_vendedor", f["vendedores"], params),
        _dash_build_in_clause(f"{alias}.projeto", f["projetos"], params),
        _dash_build_in_clause(f"{alias}.grupo_produto", f["gruposProduto"], params),
    ]:
        if clause:
            parts.append(clause)

    if not ignore_tipo_receita:
        tipos_receita = f["tiposReceita"]
        if "VENDA_FIRME" in tipos_receita and "DEVOLUCAO" not in tipos_receita:
            tipos_receita = [*tipos_receita, "DEVOLUCAO"]
        clause = _dash_build_in_clause(f"{alias}.tipo_receita", tipos_receita, params)
        if clause:
            parts.append(clause)

    if f["dataInicio"]:
        parts.append(f"{alias}.dt_entrega_cliente >= ?")
        params.append(f["dataInicio"])
    if f["dataFim"]:
        parts.append(f"{alias}.dt_entrega_cliente <= ?")
        params.append(f["dataFim"])
    if f["codParc"]:
        parts.append(f"{alias}.cod_parc = ?")
        params.append(int(f["codParc"]))
    if f["codProduto"]:
        parts.append(f"{alias}.cod_produto = ?")
        params.append(int(f["codProduto"]))
    if f["uf"]:
        parts.append(f"{alias}.uf = ?")
        params.append(f["uf"])

    parts.append(f"({alias}.cod_top IS NULL OR {alias}.cod_top != 1023)")
    parts.append(f"({alias}.[top] IS NULL OR {alias}.[top] NOT LIKE '%ESTOQUE MINIM%')")

    return "WHERE " + " AND ".join(parts), params


def _dash_build_orcamento_where(filtros: dict | None) -> tuple[str, list[Any]]:
    f = _dash_normalize_filtros(filtros)
    parts: list[str] = []
    params: list[Any] = []

    if f["dataInicio"]:
        parts.append("dt_prev_entrega_embarque >= ?")
        params.append(f["dataInicio"])
    if f["dataFim"]:
        parts.append("dt_prev_entrega_embarque <= ?")
        params.append(f["dataFim"])

    for column, values in [
        ("projeto", f["projetos"]),
        ("mercado_vendas", f["mercados"]),
        ("grupo_produto", f["gruposProduto"]),
    ]:
        clause = _dash_build_in_clause(column, values, params)
        if clause:
            parts.append(clause)

    return ("WHERE " + " AND ".join(parts), params) if parts else ("", params)


def _dash_fetch_all(sql_text: str, params: list[Any] | None = None) -> list[Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql_text, *(params or []))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def _dash_fetch_one(sql_text: str, params: list[Any] | None = None) -> Any:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql_text, *(params or []))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_dashboard_original_kpis(filtros: dict | None = None) -> dict:
    clause, params = _dash_build_fato_where(filtros)
    row = _dash_fetch_one(
        f"""
        SELECT
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento_bruto,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume_bruto,
            0 AS faturamento_devolucao,
            0 AS volume_devolucao,
            COUNT(DISTINCT fv.cod_parc) AS clientes_unicos,
            COUNT(DISTINCT fv.cod_produto) AS produtos_unicos,
            COUNT(*) AS total_registros
        FROM dbo.fato_vendas fv
        {clause}
        """,
        params,
    )
    faturamento_bruto = _dash_number(row.faturamento_bruto) if row else 0
    volume_bruto = _dash_number(row.volume_bruto) if row else 0
    faturamento_devolucao = _dash_number(row.faturamento_devolucao) if row else 0
    volume_devolucao = _dash_number(row.volume_devolucao) if row else 0
    faturamento_total = faturamento_bruto - faturamento_devolucao
    volume_total = volume_bruto - volume_devolucao
    return {
        "faturamentoTotal": faturamento_total,
        "volumeTotal": volume_total,
        "precoMedio": faturamento_total / volume_total if volume_total else 0,
        "faturamentoDevolucao": faturamento_devolucao,
        "volumeDevolucao": volume_devolucao,
        "clientesAtivos": _dash_int(row.clientes_unicos) if row else 0,
        "produtosVendidos": _dash_int(row.produtos_unicos) if row else 0,
        "totalRegistros": _dash_int(row.total_registros) if row else 0,
    }


def get_dashboard_original_kpis_ano_anterior(filtros: dict | None = None) -> dict:
    filtros_ant = dict(filtros or {})
    filtros_ant["dataInicio"] = _dash_shift_year(filtros_ant.get("dataInicio"))
    filtros_ant["dataFim"] = _dash_shift_year(filtros_ant.get("dataFim"))
    return get_dashboard_original_kpis(filtros_ant)


def list_dashboard_original_evolucao_mensal(filtros: dict | None = None) -> list[dict]:
    clause, params = _dash_build_fato_where(filtros)
    rows = _dash_fetch_all(
        f"""
        SELECT
            FORMAT(fv.dt_entrega_cliente, 'yyyy-MM') AS mes,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COALESCE(SUM(CASE WHEN fv.tipo_receita IN ('VENDA_FIRME','DEVOLUCAO') THEN fv.valor_pendente ELSE 0 END), 0) AS venda_firme,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'FORECAST' THEN fv.valor_pendente ELSE 0 END), 0) AS forecast,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'NOVO_PROJETO' THEN fv.valor_pendente ELSE 0 END), 0) AS novo_projeto
        FROM dbo.fato_vendas fv
        {clause}
        GROUP BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        ORDER BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        """,
        params,
    )
    return [
        {
            "mes": row.mes,
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
            "vendaFirme": _dash_number(row.venda_firme),
            "forecast": _dash_number(row.forecast),
            "novoProjeto": _dash_number(row.novo_projeto),
        }
        for row in rows
    ]


def list_dashboard_original_evolucao_ano_anterior(filtros: dict | None = None) -> list[dict]:
    filtros_ant = dict(filtros or {})
    filtros_ant["dataInicio"] = _dash_shift_year(filtros_ant.get("dataInicio"))
    filtros_ant["dataFim"] = _dash_shift_year(filtros_ant.get("dataFim"))
    clause, params = _dash_build_fato_where(filtros_ant)
    ano_atual = None
    if (filtros or {}).get("dataInicio"):
        try:
            ano_atual = datetime.strptime(str((filtros or {}).get("dataInicio"))[:10], "%Y-%m-%d").year
        except ValueError:
            ano_atual = None
    rows = _dash_fetch_all(
        f"""
        SELECT
            FORMAT(fv.dt_entrega_cliente, 'yyyy-MM') AS mes,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume
        FROM dbo.fato_vendas fv
        {clause}
        GROUP BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        ORDER BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        """,
        params,
    )
    result: list[dict] = []
    for row in rows:
        mes = row.mes
        mes_alinhado = f"{ano_atual}-{str(mes).split('-')[1]}" if ano_atual and mes else mes
        result.append({
            "mes": mes,
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
            "mesAlinhado": mes_alinhado,
            "mesOriginal": mes,
        })
    return result


def list_dashboard_original_kpis_por_tipo(filtros: dict | None = None) -> list[dict]:
    clause, params = _dash_build_fato_where(filtros, ignore_tipo_receita=True)
    rows = _dash_fetch_all(
        f"""
        SELECT
            CASE WHEN fv.tipo_receita = 'DEVOLUCAO' THEN 'VENDA_FIRME' ELSE fv.tipo_receita END AS tipo_receita,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.cod_parc) AS clientes,
            COUNT(*) AS registros
        FROM dbo.fato_vendas fv
        {clause}
        GROUP BY CASE WHEN fv.tipo_receita = 'DEVOLUCAO' THEN 'VENDA_FIRME' ELSE fv.tipo_receita END
        """,
        params,
    )
    return [
        {
            "tipoReceita": row.tipo_receita,
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
            "clientes": _dash_int(row.clientes),
            "registros": _dash_int(row.registros),
        }
        for row in rows
    ]


def get_dashboard_original_total_vendas() -> int:
    row = _dash_fetch_one("SELECT COUNT(*) AS total FROM dbo.fato_vendas")
    return _dash_int(row.total) if row else 0


def get_dashboard_original_orcamento_kpis(filtros: dict | None = None) -> dict:
    clause, params = _dash_build_orcamento_where(filtros)
    row = _dash_fetch_one(
        f"""
        SELECT
            COALESCE(SUM(valor_pendente), 0) AS faturamento_total,
            COALESCE(SUM(qtd_pendente_kg), 0) AS volume_total,
            COUNT(*) AS total_registros,
            COUNT(DISTINCT cod_parc) AS clientes_unicos,
            COUNT(DISTINCT cod_produto) AS produtos_unicos
        FROM dbo.orcamento_2026
        {clause}
        """,
        params,
    )
    return {
        "faturamentoTotal": _dash_number(row.faturamento_total) if row else 0,
        "volumeTotal": _dash_number(row.volume_total) if row else 0,
        "totalRegistros": _dash_int(row.total_registros) if row else 0,
        "clientesUnicos": _dash_int(row.clientes_unicos) if row else 0,
        "produtosUnicos": _dash_int(row.produtos_unicos) if row else 0,
    }


def list_dashboard_original_orcamento_mensal(filtros: dict | None = None) -> list[dict]:
    clause, params = _dash_build_orcamento_where(filtros)
    rows = _dash_fetch_all(
        f"""
        SELECT
            FORMAT(dt_prev_entrega_embarque, 'yyyy-MM') AS mes,
            COALESCE(SUM(valor_pendente), 0) AS faturamento,
            COALESCE(SUM(qtd_pendente_kg), 0) AS volume
        FROM dbo.orcamento_2026
        {clause}
        GROUP BY FORMAT(dt_prev_entrega_embarque, 'yyyy-MM')
        ORDER BY FORMAT(dt_prev_entrega_embarque, 'yyyy-MM')
        """,
        params,
    )
    return [{"mes": row.mes, "faturamento": _dash_number(row.faturamento), "volume": _dash_number(row.volume)} for row in rows]


def list_dashboard_original_segmentos(filtros: dict | None = None) -> list[dict]:
    clause, params = _dash_build_fato_where(filtros)
    rows = _dash_fetch_all(
        f"""
        SELECT
            fv.perfil_parceiro AS segmento,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.cod_parc) AS clientes,
            COUNT(DISTINCT fv.cod_produto) AS produtos
        FROM dbo.fato_vendas fv
        {clause}
        GROUP BY fv.perfil_parceiro
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        params,
    )
    return [
        {
            "segmento": row.segmento,
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
            "clientes": _dash_int(row.clientes),
            "produtos": _dash_int(row.produtos),
        }
        for row in rows
    ]


def list_dashboard_original_projetos(filtros: dict | None = None) -> list[dict]:
    clause, params = _dash_build_fato_where(filtros)
    rows = _dash_fetch_all(
        f"""
        SELECT
            fv.projeto AS projeto,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.cod_parc) AS clientes
        FROM dbo.fato_vendas fv
        {clause}
        GROUP BY fv.projeto
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        params,
    )
    return [
        {
            "projeto": row.projeto,
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
            "clientes": _dash_int(row.clientes),
        }
        for row in rows
    ]


def list_dashboard_original_clientes_top(filtros: dict | None = None, limit: int | None = None) -> list[dict]:
    clause, params = _dash_build_fato_where(filtros)
    safe_limit = int(limit or 0)
    top_clause = f"TOP ({max(1, min(safe_limit, 500))}) " if safe_limit > 0 else ""
    rows = _dash_fetch_all(
        f"""
        SELECT {top_clause}
            fv.cod_parc AS cod_parc,
            COALESCE(dc.razao_social, fv.RAZAOSOCIAL) AS razao_social,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.cod_produto) AS produtos
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
        {clause}
        GROUP BY fv.cod_parc, dc.razao_social, fv.RAZAOSOCIAL
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        params,
    )
    return [
        {
            "codParc": _dash_int(row.cod_parc),
            "razaoSocial": row.razao_social,
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
            "produtos": _dash_int(row.produtos),
        }
        for row in rows
    ]


def list_dashboard_original_drilldown(tipo_receita: str, filtros: dict | None = None) -> list[dict]:
    filtros_tipo = dict(filtros or {})
    filtros_tipo["tiposReceita"] = [tipo_receita]
    clause, params = _dash_build_fato_where(filtros_tipo)
    rows = _dash_fetch_all(
        f"""
        SELECT
            fv.cod_parc AS cod_parc,
            COALESCE(dc.razao_social, fv.RAZAOSOCIAL) AS razao_social,
            fv.cod_produto AS cod_produto,
            COALESCE(dp.nome_produto, fv.nome_produto) AS nome_produto,
            fv.grupo_produto AS grupo_produto,
            fv.nome_vendedor AS nome_vendedor,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(*) AS registros,
            MAX(CONVERT(VARCHAR, fv.dt_entrega_cliente, 23)) AS dt_prev_entrega
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
        LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
        {clause}
        GROUP BY fv.cod_parc, dc.razao_social, fv.RAZAOSOCIAL, fv.cod_produto, dp.nome_produto, fv.nome_produto, fv.grupo_produto, fv.nome_vendedor
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        params,
    )
    return [
        {
            "codParc": _dash_int(row.cod_parc),
            "razaoSocial": row.razao_social,
            "codProduto": _dash_int(row.cod_produto),
            "nomeProduto": row.nome_produto,
            "grupoProduto": row.grupo_produto,
            "nomeVendedor": row.nome_vendedor,
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
            "registros": _dash_int(row.registros),
            "dtPrevEntrega": row.dt_prev_entrega,
        }
        for row in rows
    ]


def list_dashboard_original_cliente_mix(cod_parc: int, filtros: dict | None = None, limit: int = 30) -> list[dict]:
    filtros_cliente = dict(filtros or {})
    filtros_cliente["codParc"] = cod_parc
    clause, params = _dash_build_fato_where(filtros_cliente)
    safe_limit = max(1, min(int(limit or 30), 200))
    rows = _dash_fetch_all(
        f"""
        SELECT TOP ({safe_limit})
            fv.cod_produto AS cod_produto,
            COALESCE(dp.nome_produto, fv.nome_produto) AS nome_produto,
            fv.grupo_produto AS grupo_produto,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
        {clause}
        GROUP BY fv.cod_produto, dp.nome_produto, fv.nome_produto, fv.grupo_produto
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        params,
    )
    return [
        {
            "codProduto": _dash_int(row.cod_produto),
            "nomeProduto": row.nome_produto,
            "grupoProduto": row.grupo_produto,
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
        }
        for row in rows
    ]


def get_dashboard_original_filtros_disponiveis() -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT mercado_vendas AS value FROM dbo.fato_vendas WHERE mercado_vendas IS NOT NULL ORDER BY mercado_vendas")
        mercados = [row.value for row in cursor.fetchall() if row.value]
        cursor.execute("SELECT DISTINCT nome_vendedor AS value FROM dbo.fato_vendas WHERE nome_vendedor IS NOT NULL ORDER BY nome_vendedor")
        vendedores = [row.value for row in cursor.fetchall() if row.value]
        cursor.execute("SELECT DISTINCT projeto AS value FROM dbo.fato_vendas WHERE projeto IS NOT NULL ORDER BY projeto")
        projetos = [row.value for row in cursor.fetchall() if row.value]
        cursor.execute("SELECT DISTINCT grupo_produto AS value FROM dbo.fato_vendas WHERE grupo_produto IS NOT NULL ORDER BY grupo_produto")
        grupos = [row.value for row in cursor.fetchall() if row.value]
        cursor.execute("SELECT cod_parc AS cod_parc, razao_social AS razao_social FROM dbo.dim_cliente ORDER BY razao_social")
        clientes = [{"codParc": _dash_int(row.cod_parc), "razaoSocial": row.razao_social} for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()
    return {"mercados": mercados, "vendedores": vendedores, "projetos": projetos, "grupos": grupos, "clientes": clientes}


def get_dashboard_original_resumo(filtros: dict | None = None, limit_clientes: int | None = None) -> dict:
    return {
        "kpis": get_dashboard_original_kpis(filtros),
        "kpisAnoAnterior": get_dashboard_original_kpis_ano_anterior(filtros),
        "evolucaoMensal": list_dashboard_original_evolucao_mensal(filtros),
        "evolucaoMensalAnoAnterior": list_dashboard_original_evolucao_ano_anterior(filtros),
        "kpisPorTipo": list_dashboard_original_kpis_por_tipo(filtros),
        "totalVendas": get_dashboard_original_total_vendas(),
        "segmentos": list_dashboard_original_segmentos(filtros),
        "projetos": list_dashboard_original_projetos(filtros),
        # Importante: sem limite por padrão. O frontend calcula o percentual usando a soma
        # da lista recebida, como no backend tRPC original. Limitar aqui infla a participação.
        "clientesTop": list_dashboard_original_clientes_top(filtros, limit_clientes),
        "orcamentoKpis": get_dashboard_original_orcamento_kpis(filtros),
        "orcamentoMensal": list_dashboard_original_orcamento_mensal(filtros),
    }
