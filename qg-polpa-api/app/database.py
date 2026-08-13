"""
Database layer completo da API QG Polpa Brasil.

Arquivo consolidado para substituir `app/database.py` na API Python/FastAPI local.
Inclui conexão SQL Server, autenticação/usuários, Metas 2026, B2B, Por Vendedor
original REST e Dashboard Executivo original REST.
"""

import os
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from typing import Any

import pyodbc
from dotenv import load_dotenv


load_dotenv()


def get_connection_string() -> str:
    driver = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
    server = os.getenv("DB_SERVER")
    port = os.getenv("DB_PORT", "1433")

    # Compatibilidade com o projeto antigo Node/tRPC anexado:
    # nele a variável do banco é DB_DATABASE=PolpaBrasil, enquanto
    # versões anteriores da API Python esperavam DB_NAME. Se a API
    # usar apenas DB_NAME, ela pode conectar no banco errado ou falhar
    # mesmo com o projeto antigo funcionando localmente.
    database = os.getenv("DB_NAME") or os.getenv("DB_DATABASE")

    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")

    missing_vars = []

    if not server:
        missing_vars.append("DB_SERVER")
    if not database:
        missing_vars.append("DB_NAME ou DB_DATABASE")
    if not user:
        missing_vars.append("DB_USER")
    if not password:
        missing_vars.append("DB_PASSWORD")

    if missing_vars:
        raise RuntimeError(
            "Variáveis ausentes no .env: " + ", ".join(missing_vars)
        )

    server_part = str(server).strip()
    port_part = str(port).strip() if port else ""
    # Para instância nomeada, ex.: localhost\SQLEXPRESS, não acrescenta ,1433
    # porque SQL Server Browser/instância nomeada pode resolver a porta sozinho.
    if port_part and "\\" not in server_part and "," not in server_part:
        server_part = f"{server_part},{port_part}"

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server_part};"
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


def _build_periodos_clause(alias: str, column: str, periodos: list[str], params: list) -> str | None:
    """periodos: lista de strings 'YYYY-MM'. Gera cláusula (ANO*100+MES) IN (...) que
    seleciona exatamente os pares ano/mês informados, permitindo combinar meses de
    anos distintos sem cair no produto cartesiano de anos × meses."""
    valores: list[int] = []
    for p in periodos or []:
        try:
            ano_str, mes_str = str(p).split("-")
            valores.append(int(ano_str) * 100 + int(mes_str))
        except (ValueError, AttributeError):
            continue
    if not valores:
        return None
    col_ref = f"{alias}.{column}" if alias else column
    placeholders = ", ".join(["?"] * len(valores))
    params.extend(valores)
    return f"(YEAR({col_ref}) * 100 + MONTH({col_ref})) IN ({placeholders})"


def _split_int_filter(value: int | str | list | tuple | None) -> list[int]:
    if value is None:
        return []
    raw_values = value if isinstance(value, (list, tuple)) else [value]
    result: list[int] = []
    for item in raw_values:
        if item is None or str(item).strip() == "":
            continue
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


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
        "periodos": _split_filter(filtros.get("periodos")),
        "codParc": filtros.get("codParc"),
        "codProduto": filtros.get("codProduto"),
        "codParcs": _split_int_filter(filtros.get("codParcs") or filtros.get("codParc")),
        "codProdutos": _split_int_filter(filtros.get("codProdutos") or filtros.get("codProduto")),
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

    periodos_clause = _build_periodos_clause(alias, "dt_entrega_cliente", f["periodos"], params)
    if periodos_clause:
        parts.append(periodos_clause)
    else:
        if f["dataInicio"]:
            parts.append(f"{alias}.dt_entrega_cliente >= ?")
            params.append(f["dataInicio"])
        if f["dataFim"]:
            parts.append(f"{alias}.dt_entrega_cliente <= ?")
            params.append(f["dataFim"])
    clause = _build_in_clause(f"{alias}.cod_parc", f["codParcs"], params)
    if clause:
        parts.append(clause)
    clause = _build_in_clause(f"{alias}.cod_produto", f["codProdutos"], params)
    if clause:
        parts.append(clause)
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

    periodos_clause = _build_periodos_clause("", "dt_prev_entrega_embarque", f["periodos"], params)
    if periodos_clause:
        parts.append(periodos_clause)
    else:
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
    filtros_sem_cliente.pop("codParcs", None)
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


def list_vendedores_cliente_produto_mensal_original(cod_parc: int, cod_produto: int, filtros: dict | None = None) -> list[dict]:
    """Detalhamento mês a mês de um produto dentro de um cliente (3º nível de expansão)."""
    filtros_sem_cliente = dict(filtros or {})
    filtros_sem_cliente.pop("codParc", None)
    filtros_sem_cliente.pop("codParcs", None)
    clause, params = build_fato_vendas_where(filtros_sem_cliente, "fv")
    add_cond = clause.replace("WHERE ", "AND ", 1) if clause else ""

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            FORMAT(fv.dt_entrega_cliente, 'yyyy-MM') AS mes,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS quantidade,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor
        FROM dbo.fato_vendas fv
        WHERE fv.cod_parc = ?
          AND fv.cod_produto = ?
          AND fv.flag_devolucao = 0
          {add_cond}
        GROUP BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        ORDER BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        """,
        int(cod_parc),
        int(cod_produto),
        *params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "mes": row.mes,
            "quantidade": _number(row.quantidade),
            "valor": _number(row.valor),
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
        "periodos": _dash_split_filter(filtros.get("periodos")),
        "codParc": filtros.get("codParc"),
        "codProduto": filtros.get("codProduto"),
        "codParcs": _split_int_filter(filtros.get("codParcs") or filtros.get("codParc")),
        "codProdutos": _split_int_filter(filtros.get("codProdutos") or filtros.get("codProduto")),
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

    periodos_clause = _build_periodos_clause(alias, "dt_entrega_cliente", f["periodos"], params)
    if periodos_clause:
        parts.append(periodos_clause)
    else:
        if f["dataInicio"]:
            parts.append(f"{alias}.dt_entrega_cliente >= ?")
            params.append(f["dataInicio"])
        if f["dataFim"]:
            parts.append(f"{alias}.dt_entrega_cliente <= ?")
            params.append(f["dataFim"])
    clause = _dash_build_in_clause(f"{alias}.cod_parc", f["codParcs"], params)
    if clause:
        parts.append(clause)
    clause = _dash_build_in_clause(f"{alias}.cod_produto", f["codProdutos"], params)
    if clause:
        parts.append(clause)
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

    periodos_clause = _build_periodos_clause("", "dt_prev_entrega_embarque", f["periodos"], params)
    if periodos_clause:
        parts.append(periodos_clause)
    else:
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
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'NOVO_PROJETO' THEN fv.valor_pendente ELSE 0 END), 0) AS novo_projeto,
            COALESCE(SUM(CASE WHEN fv.tipo_receita IN ('VENDA_FIRME','DEVOLUCAO') THEN fv.qtd_pendente_kg ELSE 0 END), 0) AS volume_venda_firme,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'FORECAST' THEN fv.qtd_pendente_kg ELSE 0 END), 0) AS volume_forecast,
            COALESCE(SUM(CASE WHEN fv.tipo_receita = 'NOVO_PROJETO' THEN fv.qtd_pendente_kg ELSE 0 END), 0) AS volume_novo_projeto
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
            "volumeVendaFirme": _dash_number(row.volume_venda_firme),
            "volumeForecast": _dash_number(row.volume_forecast),
            "volumeNovoProjeto": _dash_number(row.volume_novo_projeto),
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


# =============================================================================
# Dashboard Executivo — Top Produtos (espelha Top Clientes, eixo invertido)
# =============================================================================

def list_dashboard_original_produtos_top(filtros: dict | None = None, limit: int | None = None) -> list[dict]:
    clause, params = _dash_build_fato_where(filtros)
    safe_limit = int(limit or 0)
    top_clause = f"TOP ({max(1, min(safe_limit, 500))}) " if safe_limit > 0 else ""
    rows = _dash_fetch_all(
        f"""
        SELECT {top_clause}
            fv.cod_produto AS cod_produto,
            COALESCE(dp.nome_produto, fv.nome_produto) AS nome_produto,
            fv.grupo_produto AS grupo_produto,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.cod_parc) AS clientes
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
            "clientes": _dash_int(row.clientes),
        }
        for row in rows
    ]


def list_dashboard_original_produto_mix(cod_produto: int, filtros: dict | None = None, limit: int = 30) -> list[dict]:
    """Para um produto, lista os clientes que o compraram (inverso de list_dashboard_original_cliente_mix)."""
    filtros_produto = dict(filtros or {})
    filtros_produto["codProduto"] = cod_produto
    clause, params = _dash_build_fato_where(filtros_produto)
    safe_limit = max(1, min(int(limit or 30), 200))
    rows = _dash_fetch_all(
        f"""
        SELECT TOP ({safe_limit})
            fv.cod_parc AS cod_parc,
            COALESCE(dc.razao_social, fv.RAZAOSOCIAL) AS razao_social,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume
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
        }
        for row in rows
    ]


# =============================================================================
# Dashboard Executivo — Top Regiões (Norte/Nordeste/Centro-Oeste/Sudeste/Sul)
# =============================================================================

REGIOES_BRASIL: dict[str, list[str]] = {
    "Norte": ["AC", "AP", "AM", "PA", "RO", "RR", "TO"],
    "Nordeste": ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "Centro-Oeste": ["GO", "MT", "MS", "DF"],
    "Sudeste": ["ES", "MG", "RJ", "SP"],
    "Sul": ["PR", "RS", "SC"],
}

NOMES_ESTADOS: dict[str, str] = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí",
    "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul",
    "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins",
}


def _regiao_case_sql(alias: str = "fv") -> str:
    """CASE SQL que mapeia fv.uf para a região do Brasil correspondente."""
    partes = []
    for regiao, ufs in REGIOES_BRASIL.items():
        ufs_sql = ",".join(f"'{uf}'" for uf in ufs)
        partes.append(f"WHEN {alias}.uf IN ({ufs_sql}) THEN '{regiao}'")
    return "CASE " + " ".join(partes) + " ELSE NULL END"


def list_dashboard_original_regioes_top(filtros: dict | None = None) -> list[dict]:
    clause, params = _dash_build_fato_where(filtros)
    regiao_expr = _regiao_case_sql("fv")
    rows = _dash_fetch_all(
        f"""
        SELECT
            {regiao_expr} AS regiao,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.cod_parc) AS clientes,
            COUNT(DISTINCT fv.uf) AS estados
        FROM dbo.fato_vendas fv
        {clause}
        GROUP BY {regiao_expr}
        """,
        params,
    )
    resultado = [
        {
            "regiao": row.regiao,
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
            "clientes": _dash_int(row.clientes),
            "estados": _dash_int(row.estados),
        }
        for row in rows
        if row.regiao
    ]
    resultado.sort(key=lambda r: r["faturamento"], reverse=True)
    return resultado


def list_dashboard_original_regiao_mix(regiao: str, filtros: dict | None = None) -> list[dict]:
    """Para uma região, lista os estados (UF) que a compõem com faturamento/volume."""
    ufs = REGIOES_BRASIL.get(regiao, [])
    if not ufs:
        return []
    clause, params = _dash_build_fato_where(filtros)
    ufs_placeholders = ",".join(["?"] * len(ufs))
    rows = _dash_fetch_all(
        f"""
        SELECT
            fv.uf AS uf,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.cod_parc) AS clientes
        FROM dbo.fato_vendas fv
        {clause}
        AND fv.uf IN ({ufs_placeholders})
        GROUP BY fv.uf
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        [*params, *ufs],
    )
    return [
        {
            "uf": row.uf,
            "nomeEstado": NOMES_ESTADOS.get((row.uf or "").strip().upper(), row.uf),
            "faturamento": _dash_number(row.faturamento),
            "volume": _dash_number(row.volume),
            "clientes": _dash_int(row.clientes),
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
        cursor.execute(
            """
            SELECT
                fv.cod_parc AS cod_parc,
                COALESCE(MAX(dc.razao_social), MAX(fv.RAZAOSOCIAL), CAST(fv.cod_parc AS NVARCHAR(20))) AS razao_social
            FROM dbo.fato_vendas fv
            LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
            WHERE fv.cod_parc IS NOT NULL
            GROUP BY fv.cod_parc
            ORDER BY razao_social
            """
        )
        clientes = [{"codParc": _dash_int(row.cod_parc), "razaoSocial": row.razao_social} for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT
                fv.grupo_produto AS grupo_produto,
                CAST(fv.cod_produto AS VARCHAR(20)) AS cod_produto,
                COALESCE(MAX(dp.nome_produto), MAX(fv.nome_produto), CAST(fv.cod_produto AS NVARCHAR(20))) AS nome_produto
            FROM dbo.fato_vendas fv
            LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
            WHERE fv.grupo_produto IS NOT NULL AND fv.cod_produto IS NOT NULL
            GROUP BY fv.grupo_produto, fv.cod_produto
            ORDER BY fv.grupo_produto, nome_produto
            """
        )
        produtos_por_grupo: dict[str, list[dict]] = {}
        for row in cursor.fetchall():
            grupo = row.grupo_produto
            if not grupo:
                continue
            produtos_por_grupo.setdefault(grupo, []).append(
                {"codProduto": row.cod_produto, "nomeProduto": row.nome_produto}
            )
    finally:
        cursor.close()
        conn.close()
    return {
        "mercados": mercados,
        "vendedores": vendedores,
        "projetos": projetos,
        "grupos": grupos,
        "clientes": clientes,
        "produtosPorGrupo": produtos_por_grupo,
    }


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
        "produtosTop": list_dashboard_original_produtos_top(filtros, limit_clientes),
        "regioesTop": list_dashboard_original_regioes_top(filtros),
        "orcamentoKpis": get_dashboard_original_orcamento_kpis(filtros),
        "orcamentoMensal": list_dashboard_original_orcamento_mensal(filtros),
    }


# ============================================================
# Novos Projetos (/projetos) - API REST
# ============================================================

"""
Trechos para adicionar em app/database.py.

Objetivo: expor, na API Python/FastAPI, as mesmas fontes que a tela original
"Novos Projetos" (/projetos) usava via tRPC, preservando filtros globais,
exclusões globais, cálculo de ciclo M1-M12 e formato esperado pelo frontend.

Observação: este arquivo pressupõe que app/database.py já possui get_connection().
"""

from decimal import Decimal
from typing import Any


def _np_number(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def _np_int(value: Any) -> int:
    return int(value or 0)


def _np_split_filter(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, (list, tuple)) else str(value).split(",")
    return [str(item).strip() for item in raw_values if str(item).strip()]


def _np_build_in_clause(column: str, values: list[str], params: list[Any]) -> str | None:
    if not values:
        return None
    params.extend(values)
    return f"{column} IN ({','.join(['?'] * len(values))})"


def _np_normalize_filtros(filtros: dict | None) -> dict:
    filtros = filtros or {}
    return {
        "mercados": _np_split_filter(filtros.get("mercados") or filtros.get("mercado")),
        "vendedores": _np_split_filter(filtros.get("vendedores") or filtros.get("vendedor")),
        # A página Novos Projetos força a fonte para NOVOS PROJETOS/TESTE INDUSTRIAL.
        # Portanto, não aplicamos filtros["projetos"] para não esvaziar a base.
        "projetos": [],
        "gruposProduto": _np_split_filter(filtros.get("gruposProduto") or filtros.get("grupoProduto")),
        "tiposReceita": _np_split_filter(filtros.get("tiposReceita") or filtros.get("tipoReceita")),
        "dataInicio": filtros.get("dataInicio"),
        "dataFim": filtros.get("dataFim"),
        "periodos": _np_split_filter(filtros.get("periodos")),
        "codParc": filtros.get("codParc"),
        "codProduto": filtros.get("codProduto"),
        "codParcs": _split_int_filter(filtros.get("codParcs") or filtros.get("codParc")),
        "codProdutos": _split_int_filter(filtros.get("codProdutos") or filtros.get("codProduto")),
        "uf": filtros.get("uf"),
    }


def _np_build_fato_where(filtros: dict | None, alias: str = "fv", include_date: bool = True) -> tuple[str, list[Any]]:
    """Replica o buildWhere original do backend Node/tRPC para a tela Novos Projetos."""
    f = _np_normalize_filtros(filtros)
    parts: list[str] = []
    params: list[Any] = []

    for clause in [
        _np_build_in_clause(f"{alias}.mercado_vendas", f["mercados"], params),
        _np_build_in_clause(f"{alias}.nome_vendedor", f["vendedores"], params),
        _np_build_in_clause(f"{alias}.grupo_produto", f["gruposProduto"], params),
    ]:
        if clause:
            parts.append(clause)

    tipos_receita = f["tiposReceita"]
    if "VENDA_FIRME" in tipos_receita and "DEVOLUCAO" not in tipos_receita:
        tipos_receita = [*tipos_receita, "DEVOLUCAO"]
    clause = _np_build_in_clause(f"{alias}.tipo_receita", tipos_receita, params)
    if clause:
        parts.append(clause)

    if include_date:
        periodos_clause = _build_periodos_clause(alias, "dt_entrega_cliente", f["periodos"], params)
        if periodos_clause:
            parts.append(periodos_clause)
        else:
            if f["dataInicio"]:
                parts.append(f"{alias}.dt_entrega_cliente >= ?")
                params.append(f["dataInicio"])
            if f["dataFim"]:
                parts.append(f"{alias}.dt_entrega_cliente <= ?")
                params.append(f["dataFim"])
    clause = _np_build_in_clause(f"{alias}.cod_parc", f["codParcs"], params)
    if clause:
        parts.append(clause)
    clause = _np_build_in_clause(f"{alias}.cod_produto", f["codProdutos"], params)
    if clause:
        parts.append(clause)
    if f["uf"]:
        parts.append(f"{alias}.uf = ?")
        params.append(f["uf"])

    parts.append(f"{alias}.projeto IN ('NOVOS PROJETOS', 'TESTE INDUSTRIAL')")
    parts.append(f"({alias}.cod_top IS NULL OR {alias}.cod_top != 1023)")
    parts.append(f"({alias}.[top] IS NULL OR {alias}.[top] NOT LIKE '%ESTOQUE MINIM%')")

    return "WHERE " + " AND ".join(parts), params


def _np_fetch_all(sql_text: str, params: list[Any] | None = None) -> list[Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql_text, *(params or []))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def _np_fetch_one(sql_text: str, params: list[Any] | None = None) -> Any:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql_text, *(params or []))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


_NP_PRIMEIROS_SQL = """
WITH primeiros AS (
    SELECT cod_parc, cod_produto, MIN(dt_entrega_cliente) AS dt_primeiro
    FROM dbo.fato_vendas
    WHERE projeto IN ('NOVOS PROJETOS', 'TESTE INDUSTRIAL')
      AND dt_entrega_cliente IS NOT NULL
      AND (cod_top IS NULL OR cod_top != 1023)
      AND ([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')
    GROUP BY cod_parc, cod_produto
)
"""


_NP_PROJETO_SELECT = """
    SELECT
        fv.cod_parc AS codParc,
        COALESCE(MAX(dc.razao_social), MAX(fv.RAZAOSOCIAL), CAST(fv.cod_parc AS NVARCHAR(20))) AS razaoSocial,
        CAST(fv.cod_produto AS VARCHAR(20)) AS codProduto,
        COALESCE(MAX(dp.nome_produto), MAX(fv.nome_produto), CAST(fv.cod_produto AS NVARCHAR(20))) AS nomeProduto,
        MAX(fv.nome_vendedor) AS nomeVendedor,
        FORMAT(MIN(p.dt_primeiro), 'yyyy-MM') AS dtPrimeiro,
        DATEDIFF(MONTH, MIN(p.dt_primeiro), GETDATE()) + 1 AS mesAtualCiclo,
        FORMAT(MAX(fv.dt_entrega_cliente), 'yyyy-MM-dd') AS ultimaCompra,
        COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volumeTotal,
        COALESCE(SUM(fv.valor_pendente), 0) AS faturamentoTotal,
        CASE WHEN DATEDIFF(MONTH, MIN(p.dt_primeiro), GETDATE()) + 1 <= 12
            THEN 'Novo Projeto' ELSE 'Recorrente' END AS status,
        CASE WHEN MAX(CASE WHEN fv.projeto = 'TESTE INDUSTRIAL' THEN 1 ELSE 0 END) = 1
            THEN 'TESTE INDUSTRIAL' ELSE 'NOVOS PROJETOS' END AS origem
    FROM dbo.fato_vendas fv
    JOIN primeiros p ON fv.cod_parc = p.cod_parc AND fv.cod_produto = p.cod_produto
    LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
    LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
"""


def get_novos_projetos_kpis(filtros: dict | None = None, modo_card: str | None = None) -> dict:
    f = _np_normalize_filtros(filtros)
    clause, params = _np_build_fato_where(f)

    d_params: list[Any] = []
    p_ini_cond = ""
    p_fim_cond = ""
    p_ini_condp = ""
    p_fim_condp = ""
    if f["dataInicio"]:
        d_params.append(f["dataInicio"])
        p_ini_cond = "AND dt_primeiro >= ?"
        p_ini_condp = "AND p.dt_primeiro >= ?"
    if f["dataFim"]:
        d_params.append(f["dataFim"])
        p_fim_cond = "AND dt_primeiro <= ?"
        p_fim_condp = "AND p.dt_primeiro <= ?"

    abertos_extra = f"{p_ini_condp} {p_fim_condp}" if modo_card == "abertos" else ""
    m12_count_cond = "AND DATEDIFF(MONTH, p.dt_primeiro, fv.dt_entrega_cliente) + 1 <= 12" if modo_card != "abertos" else ""
    m12_fat_cond = "AND DATEDIFF(MONTH, p.dt_primeiro, fv.dt_entrega_cliente) + 1 <= 12" if modo_card == "totais" else ""
    active_params = [*params, *d_params] if modo_card == "abertos" else params

    r1 = _np_fetch_one(
        f"""
        {_NP_PRIMEIROS_SQL}
        SELECT COUNT(*) AS total FROM primeiros
        WHERE 1=1 {p_ini_cond} {p_fim_cond}
        """,
        d_params,
    )

    r2 = _np_fetch_one(
        f"""
        {_NP_PRIMEIROS_SQL}
        SELECT COUNT(DISTINCT CAST(fv.cod_parc AS VARCHAR(20)) + '-' + CAST(fv.cod_produto AS VARCHAR(20))) AS total
        FROM dbo.fato_vendas fv
        JOIN primeiros p ON fv.cod_parc = p.cod_parc AND fv.cod_produto = p.cod_produto
        {clause}
        AND fv.dt_entrega_cliente IS NOT NULL
        {m12_count_cond}
        {abertos_extra}
        """,
        active_params,
    )

    if modo_card:
        r2b = _np_fetch_one(
            f"""
            {_NP_PRIMEIROS_SQL}
            SELECT COALESCE(SUM(fv.valor_pendente), 0) AS faturamento
            FROM dbo.fato_vendas fv
            JOIN primeiros p ON fv.cod_parc = p.cod_parc AND fv.cod_produto = p.cod_produto
            {clause}
            AND fv.dt_entrega_cliente IS NOT NULL
            {m12_fat_cond}
            {abertos_extra}
            """,
            active_params,
        )
    else:
        r2b = _np_fetch_one(
            f"""
            SELECT COALESCE(SUM(fv.valor_pendente), 0) AS faturamento
            FROM dbo.fato_vendas fv
            {clause}
            AND fv.dt_entrega_cliente IS NOT NULL
            """,
            params,
        )

    r3 = _np_fetch_one(
        f"""
        WITH primeiros AS (
            SELECT fv.cod_parc, fv.cod_produto, MIN(fv.dt_entrega_cliente) AS dt_primeiro
            FROM dbo.fato_vendas fv
            {clause}
            AND fv.dt_entrega_cliente IS NOT NULL
            GROUP BY fv.cod_parc, fv.cod_produto
        ),
        elegiveis AS (
            SELECT cod_parc, cod_produto, dt_primeiro FROM primeiros
            WHERE DATEDIFF(MONTH, dt_primeiro, GETDATE()) >= 12
              {p_ini_cond} {p_fim_cond}
        )
        SELECT
            (SELECT COUNT(*) FROM elegiveis) AS total,
            (SELECT COUNT(*)
             FROM elegiveis e
             WHERE EXISTS (
                SELECT 1 FROM dbo.fato_vendas fv
                WHERE fv.cod_parc = e.cod_parc AND fv.cod_produto = e.cod_produto
                  AND fv.dt_entrega_cliente IS NOT NULL
                  AND DATEDIFF(MONTH, e.dt_primeiro, fv.dt_entrega_cliente) + 1 >= 13
             )) AS convertidos
        """,
        [*params, *d_params],
    )

    projetos_abertos = _np_int(r1.total) if r1 else 0
    projetos_totais = _np_int(r2.total) if r2 else 0
    faturamento_total = _np_number(r2b.faturamento) if r2b else 0
    taxa_total = _np_int(r3.total) if r3 else 0
    taxa_convertidos = _np_int(r3.convertidos) if r3 else 0
    taxa_conversao = (taxa_convertidos / taxa_total * 100) if taxa_total else 0
    ticket_medio = faturamento_total / projetos_totais if projetos_totais else 0

    return {
        "projetosAbertos": projetos_abertos,
        "projetosTotais": projetos_totais,
        "faturamentoTotal": faturamento_total,
        "taxaConversao": taxa_conversao,
        "taxaConversaoTotal": taxa_total,
        "taxaConversaoConvertidos": taxa_convertidos,
        "ticketMedio": ticket_medio,
    }


def list_novos_projetos_por_mes(filtros: dict | None = None, modo_card: str | None = None) -> list[dict]:
    f = _np_normalize_filtros(filtros)
    clause, params = _np_build_fato_where(f)
    d_params: list[Any] = []
    p_ini_cond = ""
    p_fim_cond = ""
    if f["dataInicio"]:
        d_params.append(f["dataInicio"])
        p_ini_cond = "AND p.dt_primeiro >= ?"
    if f["dataFim"]:
        d_params.append(f["dataFim"])
        p_fim_cond = "AND p.dt_primeiro <= ?"
    extra_cond = f"{p_ini_cond} {p_fim_cond}" if modo_card == "abertos" else ""
    all_params = [*params, *d_params] if modo_card == "abertos" else params

    rows = _np_fetch_all(
        f"""
        {_NP_PRIMEIROS_SQL}
        SELECT
            FORMAT(fv.dt_entrega_cliente, 'yyyy-MM') AS mes,
            COUNT(DISTINCT CAST(fv.cod_parc AS VARCHAR(20)) + '-' + CAST(fv.cod_produto AS VARCHAR(20))) AS projetos,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento
        FROM dbo.fato_vendas fv
        JOIN primeiros p ON fv.cod_parc = p.cod_parc AND fv.cod_produto = p.cod_produto
        {clause}
        AND fv.dt_entrega_cliente IS NOT NULL
        AND DATEDIFF(MONTH, p.dt_primeiro, fv.dt_entrega_cliente) + 1 <= 12
        {extra_cond}
        GROUP BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        ORDER BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        """,
        all_params,
    )
    return [
        {"mes": str(r.mes), "projetos": _np_int(r.projetos), "faturamento": _np_number(r.faturamento)}
        for r in rows
    ]


def _np_row_to_projeto(row: Any) -> dict:
    return {
        "codParc": _np_int(row.codParc),
        "razaoSocial": str(row.razaoSocial or ""),
        "codProduto": str(row.codProduto or ""),
        "nomeProduto": str(row.nomeProduto or ""),
        "nomeVendedor": str(row.nomeVendedor or ""),
        "dtPrimeiro": str(row.dtPrimeiro or ""),
        "mesAtualCiclo": _np_int(row.mesAtualCiclo),
        "ultimaCompra": str(row.ultimaCompra or ""),
        "volumeTotal": _np_number(row.volumeTotal),
        "faturamentoTotal": _np_number(row.faturamentoTotal),
        "status": str(row.status or ""),
        "origem": str(row.origem or ""),
    }


def list_novos_projetos(filtros: dict | None = None, modo_card: str | None = None) -> list[dict]:
    f = _np_normalize_filtros(filtros)
    clause, params = _np_build_fato_where(f)
    d_params: list[Any] = []
    p_ini_cond = ""
    p_fim_cond = ""
    if f["dataInicio"]:
        d_params.append(f["dataInicio"])
        p_ini_cond = "AND p.dt_primeiro >= ?"
    if f["dataFim"]:
        d_params.append(f["dataFim"])
        p_fim_cond = "AND p.dt_primeiro <= ?"
    extra_cond = f"{p_ini_cond} {p_fim_cond}" if modo_card == "abertos" else ""
    all_params = [*params, *d_params] if modo_card == "abertos" else params

    rows = _np_fetch_all(
        f"""
        {_NP_PRIMEIROS_SQL}
        {_NP_PROJETO_SELECT}
        {clause}
        AND fv.dt_entrega_cliente IS NOT NULL
        AND DATEDIFF(MONTH, p.dt_primeiro, fv.dt_entrega_cliente) + 1 <= 12
        {extra_cond}
        GROUP BY fv.cod_parc, fv.cod_produto
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        all_params,
    )
    return [_np_row_to_projeto(r) for r in rows]


def list_novos_projetos_recorrentes_convertidos(filtros: dict | None = None) -> list[dict]:
    """Lista os projetos (cliente+produto) que atingiram M13+ — mesma população usada
    no cálculo da Taxa de Conversão (taxaConversaoConvertidos), e não a 'lista' de
    Novos Projetos (que só enxerga vendas dentro da janela M1-M12 e do período filtrado)."""
    f = _np_normalize_filtros(filtros)
    clause, params = _np_build_fato_where(f)
    d_params: list[Any] = []
    p_ini_cond = ""
    p_fim_cond = ""
    if f["dataInicio"]:
        d_params.append(f["dataInicio"])
        p_ini_cond = "AND dt_primeiro >= ?"
    if f["dataFim"]:
        d_params.append(f["dataFim"])
        p_fim_cond = "AND dt_primeiro <= ?"

    rows = _np_fetch_all(
        f"""
        WITH primeiros AS (
            SELECT fv.cod_parc, fv.cod_produto, MIN(fv.dt_entrega_cliente) AS dt_primeiro
            FROM dbo.fato_vendas fv
            {clause}
            AND fv.dt_entrega_cliente IS NOT NULL
            GROUP BY fv.cod_parc, fv.cod_produto
        ),
        elegiveis AS (
            SELECT cod_parc, cod_produto, dt_primeiro FROM primeiros
            WHERE DATEDIFF(MONTH, dt_primeiro, GETDATE()) >= 12
              {p_ini_cond} {p_fim_cond}
        ),
        convertidos AS (
            SELECT e.cod_parc, e.cod_produto, e.dt_primeiro
            FROM elegiveis e
            WHERE EXISTS (
                SELECT 1 FROM dbo.fato_vendas fv2
                WHERE fv2.cod_parc = e.cod_parc AND fv2.cod_produto = e.cod_produto
                  AND fv2.dt_entrega_cliente IS NOT NULL
                  AND DATEDIFF(MONTH, e.dt_primeiro, fv2.dt_entrega_cliente) + 1 >= 13
            )
        )
        SELECT
            c.cod_parc AS codParc,
            COALESCE(MAX(dc.razao_social), MAX(fv.RAZAOSOCIAL), CAST(c.cod_parc AS NVARCHAR(20))) AS razaoSocial,
            CAST(c.cod_produto AS VARCHAR(20)) AS codProduto,
            COALESCE(MAX(dp.nome_produto), MAX(fv.nome_produto), CAST(c.cod_produto AS NVARCHAR(20))) AS nomeProduto,
            FORMAT(c.dt_primeiro, 'yyyy-MM') AS dtPrimeiro,
            DATEDIFF(MONTH, c.dt_primeiro, GETDATE()) + 1 AS mesAtualCiclo,
            FORMAT(MAX(fv.dt_entrega_cliente), 'yyyy-MM-dd') AS ultimaCompra,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volumeTotal,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamentoTotal
        FROM convertidos c
        JOIN dbo.fato_vendas fv ON fv.cod_parc = c.cod_parc AND fv.cod_produto = c.cod_produto
        LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
        LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
        GROUP BY c.cod_parc, c.cod_produto, c.dt_primeiro
        ORDER BY faturamentoTotal DESC
        """,
        [*params, *d_params],
    )
    return [
        {
            "codParc": _np_int(r.codParc),
            "razaoSocial": str(r.razaoSocial or ""),
            "codProduto": str(r.codProduto or ""),
            "nomeProduto": str(r.nomeProduto or ""),
            "dtPrimeiro": str(r.dtPrimeiro or ""),
            "mesAtualCiclo": _np_int(r.mesAtualCiclo),
            "ultimaCompra": str(r.ultimaCompra or ""),
            "volumeTotal": _np_number(r.volumeTotal),
            "faturamentoTotal": _np_number(r.faturamentoTotal),
        }
        for r in rows
    ]


def list_novos_projetos_drilldown(mes: str, filtros: dict | None = None) -> list[dict]:
    # O drilldown original ignora dataInicio/dataFim e usa apenas o mês clicado.
    f = dict(filtros or {})
    f["dataInicio"] = None
    f["dataFim"] = None
    clause, params = _np_build_fato_where(f, include_date=False)
    full_clause = f"{clause} AND FORMAT(fv.dt_entrega_cliente, 'yyyy-MM') = ?"
    all_params = [*params, mes]

    rows = _np_fetch_all(
        f"""
        {_NP_PRIMEIROS_SQL}
        {_NP_PROJETO_SELECT}
        {full_clause}
        AND fv.dt_entrega_cliente IS NOT NULL
        AND DATEDIFF(MONTH, p.dt_primeiro, fv.dt_entrega_cliente) + 1 <= 12
        GROUP BY fv.cod_parc, fv.cod_produto
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        all_params,
    )
    return [_np_row_to_projeto(r) for r in rows]


# ============================================================
# Histórico Clientes / Produtos (/historico-clientes) - API REST
# ============================================================


def _hc_as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str) and "," in item:
                out.extend([p.strip() for p in item.split(",") if p.strip()])
            elif str(item).strip() != "":
                out.append(item)
        return out
    if isinstance(value, str) and "," in value:
        return [p.strip() for p in value.split(",") if p.strip()]
    return [value] if str(value).strip() != "" else []


def _hc_int_list(value):
    out = []
    for item in _hc_as_list(value):
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _hc_str_list(value):
    return [str(item).strip() for item in _hc_as_list(value) if str(item).strip()]


def _hc_normalize_filtros(filtros: dict | None = None) -> dict:
    filtros = filtros or {}
    current_year = datetime.now().year
    data_inicio = filtros.get("dataInicio")
    data_fim = filtros.get("dataFim")
    anos = _hc_int_list(filtros.get("anos"))
    if not anos and not data_inicio and not data_fim:
        anos = [current_year]
    return {
        "anos": anos,
        "meses": _hc_int_list(filtros.get("meses")),
        "dataInicio": data_inicio,
        "dataFim": data_fim,
        "codParcs": _hc_int_list(filtros.get("codParcs")),
        "mercados": _hc_str_list(filtros.get("mercados")),
        "gruposProduto": _hc_str_list(filtros.get("gruposProduto")),
        "vendedores": _hc_str_list(filtros.get("vendedores")),
        "ufs": _hc_str_list(filtros.get("ufs")),
        "codProdutos": _hc_str_list(filtros.get("codProdutos")),
        "projetos": _hc_str_list(filtros.get("projetos") or filtros.get("projeto")),
        "periodos": _hc_str_list(filtros.get("periodos")),
        "perfis": _hc_str_list(filtros.get("perfis")),
    }


def _hc_add_in_clause(parts: list[str], params: list, column: str, values: list):
    if not values:
        return
    placeholders = ", ".join(["?"] * len(values))
    parts.append(f"{column} IN ({placeholders})")
    params.extend(values)


def _hc_build_where(filtros: dict | None = None, alias: str = "fv") -> tuple[str, tuple]:
    f = _hc_normalize_filtros(filtros)
    parts = [
        f"{alias}.tipo_receita IN ('VENDA_FIRME', 'DEVOLUCAO')",
        f"({alias}.cod_top IS NULL OR {alias}.cod_top != 1023)",
        f"({alias}.[top] IS NULL OR {alias}.[top] NOT LIKE '%ESTOQUE MINIM%')",
        f"{alias}.dt_entrega_cliente IS NOT NULL",
    ]
    params: list = []

    periodos_clause = _build_periodos_clause(alias, "dt_entrega_cliente", f["periodos"], params)
    if periodos_clause:
        parts.append(periodos_clause)
    else:
        if f["dataInicio"] or f["dataFim"]:
            if f["dataInicio"]:
                parts.append(f"{alias}.dt_entrega_cliente >= ?")
                params.append(f["dataInicio"])
            if f["dataFim"]:
                parts.append(f"{alias}.dt_entrega_cliente <= ?")
                params.append(f["dataFim"])
        else:
            _hc_add_in_clause(parts, params, f"YEAR({alias}.dt_entrega_cliente)", f["anos"])
        _hc_add_in_clause(parts, params, f"MONTH({alias}.dt_entrega_cliente)", f["meses"])
    _hc_add_in_clause(parts, params, f"{alias}.cod_parc", f["codParcs"])
    _hc_add_in_clause(parts, params, f"{alias}.mercado_vendas", f["mercados"])
    _hc_add_in_clause(parts, params, f"{alias}.grupo_produto", f["gruposProduto"])
    _hc_add_in_clause(parts, params, f"{alias}.nome_vendedor", f["vendedores"])
    _hc_add_in_clause(parts, params, f"{alias}.uf", f["ufs"])
    _hc_add_in_clause(parts, params, f"CAST({alias}.cod_produto AS NVARCHAR(50))", f["codProdutos"])
    _hc_add_in_clause(parts, params, f"{alias}.projeto", f["projetos"])
    _hc_add_in_clause(parts, params, f"{alias}.perfil_parceiro", f["perfis"])

    return "WHERE " + " AND ".join(parts), tuple(params)


def _hc_number(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _hc_int(value, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _hc_iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_historico_clientes_filtros() -> dict:
    anos = fetch_all(
        """
        SELECT DISTINCT YEAR(dt_entrega_cliente) AS ano
        FROM fato_vendas
        WHERE dt_entrega_cliente IS NOT NULL
          AND tipo_receita IN ('VENDA_FIRME','DEVOLUCAO')
          AND (cod_top IS NULL OR cod_top != 1023)
          AND ([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')
        ORDER BY ano DESC
        """
    )
    clientes = fetch_all(
        """
        SELECT
            fv.cod_parc AS codParc,
            COALESCE(MAX(dc.razao_social), MAX(fv.RAZAOSOCIAL)) AS razaoSocial
        FROM fato_vendas fv
        LEFT JOIN dim_cliente dc ON fv.cod_parc = dc.cod_parc
        WHERE fv.tipo_receita IN ('VENDA_FIRME','DEVOLUCAO')
          AND (fv.cod_top IS NULL OR fv.cod_top != 1023)
          AND (fv.[top] IS NULL OR fv.[top] NOT LIKE '%ESTOQUE MINIM%')
        GROUP BY fv.cod_parc
        ORDER BY razaoSocial
        """
    )
    mercados = fetch_all(
        """
        SELECT DISTINCT mercado_vendas AS mercado
        FROM fato_vendas
        WHERE mercado_vendas IS NOT NULL
          AND tipo_receita IN ('VENDA_FIRME','DEVOLUCAO')
          AND (cod_top IS NULL OR cod_top != 1023)
          AND ([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')
        ORDER BY mercado
        """
    )
    grupos = fetch_all(
        """
        SELECT DISTINCT grupo_produto AS grupo
        FROM fato_vendas
        WHERE grupo_produto IS NOT NULL
          AND tipo_receita IN ('VENDA_FIRME','DEVOLUCAO')
          AND (cod_top IS NULL OR cod_top != 1023)
          AND ([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')
        ORDER BY grupo
        """
    )
    vendedores = fetch_all(
        """
        SELECT DISTINCT nome_vendedor AS vendedor
        FROM fato_vendas
        WHERE nome_vendedor IS NOT NULL
          AND tipo_receita IN ('VENDA_FIRME','DEVOLUCAO')
          AND (cod_top IS NULL OR cod_top != 1023)
          AND ([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')
        ORDER BY vendedor
        """
    )

    return {
        "anos": [_hc_int(r.get("ano")) for r in anos],
        "clientes": [
            {"codParc": _hc_int(r.get("codParc")), "razaoSocial": r.get("razaoSocial") or ""}
            for r in clientes
        ],
        "mercados": [r.get("mercado") for r in mercados if r.get("mercado")],
        "gruposProduto": [r.get("grupo") for r in grupos if r.get("grupo")],
        "vendedores": [r.get("vendedor") for r in vendedores if r.get("vendedor")],
    }


def get_historico_clientes_kpis(filtros: dict | None = None) -> dict:
    clause, params = _hc_build_where(filtros)
    f = _hc_normalize_filtros(filtros)
    base_filtros = {
        "anos": f["anos"],
        "meses": f["meses"],
        "mercados": f["mercados"],
        "gruposProduto": f["gruposProduto"],
        "vendedores": f["vendedores"],
        "projetos": f["projetos"],
        "periodos": f["periodos"],
    }
    base_clause, base_params = _hc_build_where(base_filtros)

    main_rows = fetch_all(
        f"""
        SELECT
            COALESCE(SUM(fv.valor_pendente), 0) AS totalValor,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS totalVolume,
            CASE WHEN COALESCE(SUM(fv.qtd_pendente_kg), 0) > 0
                THEN SUM(fv.valor_pendente) / SUM(fv.qtd_pendente_kg)
                ELSE 0 END AS precoMedio,
            COUNT(DISTINCT fv.cod_produto) AS qtdProdutos,
            COUNT(DISTINCT fv.cod_parc) AS qtdClientes
        FROM fato_vendas fv
        {clause}
        """,
        params,
    )
    base_rows = fetch_all(
        f"""
        SELECT
            COALESCE(SUM(fv.valor_pendente), 0) AS totalValor,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS totalVolume
        FROM fato_vendas fv
        {base_clause}
        """,
        base_params,
    )

    row = main_rows[0] if main_rows else {}
    base = base_rows[0] if base_rows else {}
    total_valor = _hc_number(row.get("totalValor"))
    total_volume = _hc_number(row.get("totalVolume"))
    base_valor = _hc_number(base.get("totalValor"))
    base_volume = _hc_number(base.get("totalVolume"))

    return {
        "totalValor": total_valor,
        "totalVolume": total_volume,
        "precoMedio": _hc_number(row.get("precoMedio")),
        "qtdProdutos": _hc_int(row.get("qtdProdutos")),
        "qtdClientes": _hc_int(row.get("qtdClientes")),
        "pctFaturamento": (total_valor / base_valor * 100) if base_valor > 0 else 100,
        "pctVolume": (total_volume / base_volume * 100) if base_volume > 0 else 100,
    }


def list_historico_clientes(filtros: dict | None = None) -> list[dict]:
    clause, params = _hc_build_where(filtros)
    rows = fetch_all(
        f"""
        SELECT
            fv.cod_parc AS codParc,
            COALESCE(MAX(dc.razao_social), MAX(fv.RAZAOSOCIAL)) AS razaoSocial,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            CASE WHEN COALESCE(SUM(fv.qtd_pendente_kg), 0) > 0
                THEN SUM(fv.valor_pendente) / SUM(fv.qtd_pendente_kg)
                ELSE 0 END AS precoMedio,
            COUNT(DISTINCT fv.cod_produto) AS qtdProdutos,
            MAX(fv.dt_entrega_cliente) AS ultimaCompra
        FROM fato_vendas fv
        LEFT JOIN dim_cliente dc ON fv.cod_parc = dc.cod_parc
        {clause}
        GROUP BY fv.cod_parc
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        params,
    )
    total_valor = sum(_hc_number(r.get("valor")) for r in rows)
    total_volume = sum(_hc_number(r.get("volume")) for r in rows)
    return [
        {
            "codParc": _hc_int(r.get("codParc")),
            "razaoSocial": r.get("razaoSocial") or "",
            "valor": _hc_number(r.get("valor")),
            "volume": _hc_number(r.get("volume")),
            "precoMedio": _hc_number(r.get("precoMedio")),
            "qtdProdutos": _hc_int(r.get("qtdProdutos")),
            "pctValor": (_hc_number(r.get("valor")) / total_valor * 100) if total_valor > 0 else 0,
            "pctVolume": (_hc_number(r.get("volume")) / total_volume * 100) if total_volume > 0 else 0,
            "ultimaCompra": _hc_iso(r.get("ultimaCompra")),
        }
        for r in rows
    ]


def list_historico_clientes_evolucao_mensal(filtros: dict | None = None) -> list[dict]:
    clause, params = _hc_build_where(filtros)
    rows = fetch_all(
        f"""
        SELECT
            MONTH(fv.dt_entrega_cliente) AS mes,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            CASE WHEN COALESCE(SUM(fv.qtd_pendente_kg), 0) > 0
                THEN SUM(fv.valor_pendente) / SUM(fv.qtd_pendente_kg)
                ELSE 0 END AS precoMedio,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor
        FROM fato_vendas fv
        {clause}
        GROUP BY MONTH(fv.dt_entrega_cliente)
        ORDER BY mes
        """,
        params,
    )
    return [
        {
            "mes": _hc_int(r.get("mes")),
            "volume": _hc_number(r.get("volume")),
            "precoMedio": _hc_number(r.get("precoMedio")),
            "valor": _hc_number(r.get("valor")),
        }
        for r in rows
    ]


def list_historico_clientes_por_estado(filtros: dict | None = None) -> list[dict]:
    clause, params = _hc_build_where(filtros)
    rows = fetch_all(
        f"""
        SELECT
            fv.uf AS uf,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume
        FROM fato_vendas fv
        {clause}
        GROUP BY fv.uf
        ORDER BY valor DESC
        """,
        params,
    )
    filtered = [r for r in rows if r.get("uf")]
    total = sum(_hc_number(r.get("valor")) for r in filtered)
    return [
        {
            "uf": r.get("uf"),
            "valor": _hc_number(r.get("valor")),
            "volume": _hc_number(r.get("volume")),
            "pct": (_hc_number(r.get("valor")) / total * 100) if total > 0 else 0,
        }
        for r in filtered
    ]


def list_historico_clientes_por_segmento(filtros: dict | None = None) -> list[dict]:
    clause, params = _hc_build_where(filtros)
    rows = fetch_all(
        f"""
        SELECT
            fv.grupo_produto AS segmento,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume
        FROM fato_vendas fv
        {clause}
        GROUP BY fv.grupo_produto
        ORDER BY valor DESC
        """,
        params,
    )
    filtered = [r for r in rows if r.get("segmento")]
    total = sum(_hc_number(r.get("valor")) for r in filtered)
    return [
        {
            "segmento": r.get("segmento"),
            "valor": _hc_number(r.get("valor")),
            "volume": _hc_number(r.get("volume")),
            "pct": (_hc_number(r.get("valor")) / total * 100) if total > 0 else 0,
        }
        for r in filtered
    ]


def list_historico_clientes_por_perfil(filtros: dict | None = None) -> list[dict]:
    clause, params = _hc_build_where(filtros)
    rows = fetch_all(
        f"""
        SELECT
            fv.perfil_parceiro AS perfil,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume
        FROM fato_vendas fv
        {clause}
        GROUP BY fv.perfil_parceiro
        ORDER BY valor DESC
        """,
        params,
    )
    filtered = [r for r in rows if r.get("perfil")]
    total = sum(_hc_number(r.get("valor")) for r in filtered)
    return [
        {
            "perfil": r.get("perfil"),
            "valor": _hc_number(r.get("valor")),
            "volume": _hc_number(r.get("volume")),
            "pct": (_hc_number(r.get("valor")) / total * 100) if total > 0 else 0,
        }
        for r in filtered
    ]


def list_historico_cliente_produtos(cod_parc: int, filtros: dict | None = None) -> list[dict]:
    f = dict(filtros or {})
    f["codParcs"] = [cod_parc]
    clause, params = _hc_build_where(f)
    rows = fetch_all(
        f"""
        SELECT
            CAST(fv.cod_produto AS NVARCHAR(50)) AS codProduto,
            COALESCE(MAX(dp.nome_produto), MAX(fv.nome_produto), CAST(fv.cod_produto AS NVARCHAR(50))) AS nomeProduto,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor,
            CASE WHEN COALESCE(SUM(fv.qtd_pendente_kg), 0) > 0
                THEN COALESCE(SUM(fv.valor_pendente), 0) / SUM(fv.qtd_pendente_kg)
                ELSE 0 END AS precoMedio,
            MAX(fv.dt_entrega_cliente) AS dtUltimaCompra
        FROM fato_vendas fv
        LEFT JOIN dim_produto dp ON fv.cod_produto = dp.cod_produto
        {clause}
        GROUP BY fv.cod_produto
        ORDER BY volume DESC
        """,
        params,
    )
    return [
        {
            "codProduto": str(r.get("codProduto") or ""),
            "nomeProduto": r.get("nomeProduto") or str(r.get("codProduto") or ""),
            "volume": _hc_number(r.get("volume")),
            "valor": _hc_number(r.get("valor")),
            "precoMedio": _hc_number(r.get("precoMedio")),
            "dtUltimaCompra": _hc_iso(r.get("dtUltimaCompra")),
        }
        for r in rows
    ]


def list_historico_cliente_produto_mensal(cod_parc: int, cod_produto: str, filtros: dict | None = None) -> list[dict]:
    """Detalhamento mês a mês de um produto dentro de um cliente (3º nível de expansão)."""
    f = dict(filtros or {})
    f["codParcs"] = [cod_parc]
    f.pop("codProdutos", None)
    clause, params = _hc_build_where(f)
    rows = fetch_all(
        f"""
        SELECT
            FORMAT(fv.dt_entrega_cliente, 'yyyy-MM') AS mes,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS quantidade,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor
        FROM fato_vendas fv
        {clause}
        AND CAST(fv.cod_produto AS NVARCHAR(50)) = ?
        GROUP BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        ORDER BY FORMAT(fv.dt_entrega_cliente, 'yyyy-MM')
        """,
        (*params, str(cod_produto)),
    )
    return [
        {
            "mes": r.get("mes"),
            "quantidade": _hc_number(r.get("quantidade")),
            "valor": _hc_number(r.get("valor")),
        }
        for r in rows
    ]


# =============================================================================
# Comparativo Semanal / Snapshot — dados originais migrados para REST
# =============================================================================


def _date_yyyy_mm_dd(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _build_snapshot_hist_where(filtros: dict | None, alias: str = "fs") -> tuple[str, list[Any]]:
    """Reproduz o buildSnapHistWhere original para forecast_snapshots."""
    f = _normalize_filtros(filtros)
    parts: list[str] = []
    params: list[Any] = []

    # DATEDIFF(DAY, 0, data) % 7 é independente de idioma/DATEFIRST: 1900-01-01 foi
    # uma segunda-feira, então 0=segunda ... 2=quarta. So aceitamos snapshots de quarta,
    # descartando qualquer resquicio de outros dias (ex.: sexta-feira do cron legado).
    parts.append(f"DATEDIFF(DAY, 0, {alias}.snapshot_date) % 7 = 2")

    periodos_clause = _build_periodos_clause(alias, "dt_entrega_cliente", f["periodos"], params)
    if periodos_clause:
        parts.append(periodos_clause)
    else:
        if f["dataInicio"]:
            parts.append(f"{alias}.dt_entrega_cliente >= ?")
            params.append(f["dataInicio"])
        if f["dataFim"]:
            parts.append(f"{alias}.dt_entrega_cliente <= ?")
            params.append(f["dataFim"])

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

    clause = _build_in_clause(f"{alias}.cod_parc", f["codParcs"], params)
    if clause:
        parts.append(clause)
    clause = _build_in_clause(f"{alias}.cod_produto", f["codProdutos"], params)
    if clause:
        parts.append(clause)
    if f["uf"]:
        parts.append(f"{alias}.uf = ?")
        params.append(f["uf"])

    return ("WHERE " + " AND ".join(parts), params) if parts else ("", params)


def get_snapshot_datas() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            CONVERT(VARCHAR(10), snapshot_date, 23) AS snapshotDate,
            COUNT(*) AS totalRows
        FROM dbo.forecast_snapshots
        WHERE DATEDIFF(DAY, 0, snapshot_date) % 7 = 2
        GROUP BY CONVERT(VARCHAR(10), snapshot_date, 23)
        ORDER BY snapshotDate DESC
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "snapshotDate": _date_yyyy_mm_dd(row.snapshotDate),
            "totalRows": _int(row.totalRows),
        }
        for row in rows
    ]


def get_snapshot_historico(filtros: dict | None = None) -> dict:
    snap_clause, snap_params = _build_snapshot_hist_where(filtros, alias="fs")
    curr_clause, curr_params = build_fato_vendas_where(filtros, alias="fv")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"""
        SELECT
            fs.cod_parc AS codParc,
            MAX(fs.razao_social) AS razaoSocial,
            CONVERT(VARCHAR(10), fs.snapshot_date, 23) AS snapshotDate,
            COALESCE(SUM(fs.valor_pendente), 0) AS valor,
            COALESCE(SUM(fs.qtd_pendente_kg), 0) AS volume
        FROM dbo.forecast_snapshots fs
        {snap_clause}
        GROUP BY fs.cod_parc, fs.snapshot_date
        """,
        *snap_params,
    )
    snap_rows = cursor.fetchall()

    cursor.execute(
        f"""
        SELECT
            fv.cod_parc AS codParc,
            COALESCE(MAX(dc.razao_social), MAX(fv.RAZAOSOCIAL)) AS razaoSocial,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            MIN(CONVERT(VARCHAR(10), fv.dt_entrega_cliente, 23)) AS dtEntrega
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
        {curr_clause}
        GROUP BY fv.cod_parc
        """,
        *curr_params,
    )
    curr_rows = cursor.fetchall()
    cursor.close()
    conn.close()

    dates = sorted({_date_yyyy_mm_dd(row.snapshotDate) for row in snap_rows if _date_yyyy_mm_dd(row.snapshotDate)})

    snap_by_parc: dict[int, dict] = {}
    for row in snap_rows:
        cod_parc = _int(row.codParc)
        snapshot_date = _date_yyyy_mm_dd(row.snapshotDate)
        if not snapshot_date:
            continue
        if cod_parc not in snap_by_parc:
            snap_by_parc[cod_parc] = {"razao": row.razaoSocial, "byDate": {}}
        snap_by_parc[cod_parc]["razao"] = row.razaoSocial
        snap_by_parc[cod_parc]["byDate"][snapshot_date] = {
            "valor": _number(row.valor),
            "volume": _number(row.volume),
        }

    curr_by_parc = {_int(row.codParc): row for row in curr_rows}
    all_parcs = set(snap_by_parc.keys()) | set(curr_by_parc.keys())

    rows = []
    for cod_parc in all_parcs:
        snap = snap_by_parc.get(cod_parc)
        curr = curr_by_parc.get(cod_parc)
        rows.append(
            {
                "codParc": cod_parc,
                "razaoSocial": getattr(curr, "razaoSocial", None) if curr else (snap or {}).get("razao") or f"Cliente {cod_parc}",
                "snapshots": (snap or {}).get("byDate", {}),
                "currValor": _number(getattr(curr, "valor", 0)) if curr else 0,
                "currVolume": _number(getattr(curr, "volume", 0)) if curr else 0,
                "dtEntrega": _date_yyyy_mm_dd(getattr(curr, "dtEntrega", None)) if curr else None,
            }
        )

    rows.sort(key=lambda item: item["currValor"], reverse=True)
    return {"dates": dates, "rows": rows}


def get_snapshot_historico_produtos(cod_parc: int, filtros: dict | None = None) -> dict:
    filtros_com_cliente = {**(filtros or {}), "codParc": cod_parc, "codParcs": [cod_parc]}
    snap_clause, snap_params = _build_snapshot_hist_where(filtros_com_cliente, alias="fs")
    curr_clause, curr_params = build_fato_vendas_where(filtros_com_cliente, alias="fv")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"""
        SELECT
            fs.cod_produto AS codProduto,
            MAX(fs.nome_produto) AS nomeProduto,
            CONVERT(VARCHAR(10), fs.snapshot_date, 23) AS snapshotDate,
            COALESCE(SUM(fs.valor_pendente), 0) AS valor,
            COALESCE(SUM(fs.qtd_pendente_kg), 0) AS volume
        FROM dbo.forecast_snapshots fs
        {snap_clause}
        GROUP BY fs.cod_produto, fs.snapshot_date
        """,
        *snap_params,
    )
    snap_rows = cursor.fetchall()

    cursor.execute(
        f"""
        SELECT
            fv.cod_produto AS codProduto,
            COALESCE(MAX(dp.nome_produto), MAX(fv.nome_produto)) AS nomeProduto,
            COALESCE(SUM(fv.valor_pendente), 0) AS valor,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            MIN(CONVERT(VARCHAR(10), fv.dt_entrega_cliente, 23)) AS dtEntrega
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
        {curr_clause}
        GROUP BY fv.cod_produto
        """,
        *curr_params,
    )
    curr_rows = cursor.fetchall()
    cursor.close()
    conn.close()

    dates = sorted({_date_yyyy_mm_dd(row.snapshotDate) for row in snap_rows if _date_yyyy_mm_dd(row.snapshotDate)})

    snap_by_prod: dict[int, dict] = {}
    for row in snap_rows:
        cod_produto = _int(row.codProduto)
        snapshot_date = _date_yyyy_mm_dd(row.snapshotDate)
        if not snapshot_date:
            continue
        if cod_produto not in snap_by_prod:
            snap_by_prod[cod_produto] = {"nome": row.nomeProduto, "byDate": {}}
        snap_by_prod[cod_produto]["nome"] = row.nomeProduto
        snap_by_prod[cod_produto]["byDate"][snapshot_date] = {
            "valor": _number(row.valor),
            "volume": _number(row.volume),
        }

    curr_by_prod = {_int(row.codProduto): row for row in curr_rows}
    all_produtos = set(snap_by_prod.keys()) | set(curr_by_prod.keys())

    rows = []
    for cod_produto in all_produtos:
        snap = snap_by_prod.get(cod_produto)
        curr = curr_by_prod.get(cod_produto)
        rows.append(
            {
                "codProduto": cod_produto,
                "nomeProduto": getattr(curr, "nomeProduto", None) if curr else (snap or {}).get("nome") or f"Produto {cod_produto}",
                "snapshots": (snap or {}).get("byDate", {}),
                "currValor": _number(getattr(curr, "valor", 0)) if curr else 0,
                "currVolume": _number(getattr(curr, "volume", 0)) if curr else 0,
                "dtEntrega": _date_yyyy_mm_dd(getattr(curr, "dtEntrega", None)) if curr else None,
            }
        )

    rows.sort(key=lambda item: item["currValor"], reverse=True)
    return {"dates": dates, "rows": rows}


def criar_forecast_snapshot() -> dict:
    snapshot_date = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO dbo.forecast_snapshots
            (snapshot_date, cod_parc, razao_social, cod_produto, nome_produto, grupo_produto,
             projeto, mercado_vendas, nome_vendedor, tipo_receita, uf,
             valor_pendente, qtd_pendente_kg, dt_entrega_cliente)
        SELECT
            ?,
            fv.cod_parc,
            COALESCE(dc.razao_social, fv.RAZAOSOCIAL),
            fv.cod_produto,
            COALESCE(dp.nome_produto, fv.nome_produto),
            fv.grupo_produto,
            fv.projeto,
            fv.mercado_vendas,
            fv.nome_vendedor,
            fv.tipo_receita,
            fv.uf,
            COALESCE(SUM(fv.valor_pendente), 0),
            COALESCE(SUM(fv.qtd_pendente_kg), 0),
            fv.dt_entrega_cliente
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
        LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
        WHERE (fv.cod_top IS NULL OR fv.cod_top != 1023)
          AND (fv.[top] IS NULL OR fv.[top] NOT LIKE '%ESTOQUE MINIM%')
        GROUP BY fv.cod_parc, dc.razao_social, fv.RAZAOSOCIAL, fv.cod_produto,
                 dp.nome_produto, fv.nome_produto, fv.grupo_produto, fv.projeto,
                 fv.mercado_vendas, fv.nome_vendedor, fv.tipo_receita, fv.uf,
                 fv.dt_entrega_cliente
        """,
        snapshot_date,
    )
    inserted = cursor.rowcount if cursor.rowcount is not None and cursor.rowcount >= 0 else 0
    conn.commit()
    cursor.close()
    conn.close()
    return {"inserted": inserted, "snapshotDate": snapshot_date}


# =============================================================================
# Recorrentes R x O — dados originais migrados para REST
# =============================================================================


def _build_recorrentes_real_where(filtros: dict | None, alias: str = "fv") -> tuple[str, list[Any]]:
    f = _normalize_filtros(filtros)
    parts: list[str] = [
        f"{alias}.projeto = 'RECORRENTES'",
        f"({alias}.cod_top IS NULL OR {alias}.cod_top != 1023)",
        f"({alias}.[top] IS NULL OR {alias}.[top] NOT LIKE '%ESTOQUE MINIM%')",
    ]
    params: list[Any] = []

    periodos_clause = _build_periodos_clause(alias, "dt_entrega_cliente", f["periodos"], params)
    if periodos_clause:
        parts.append(periodos_clause)
    else:
        if f["dataInicio"]:
            parts.append(f"{alias}.dt_entrega_cliente >= ?")
            params.append(f["dataInicio"])
        if f["dataFim"]:
            parts.append(f"{alias}.dt_entrega_cliente <= ?")
            params.append(f["dataFim"])
    if f["mercados"]:
        placeholders = ", ".join("?" for _ in f["mercados"])
        parts.append(f"{alias}.mercado_vendas IN ({placeholders})")
        params.extend(f["mercados"])
    if f["vendedores"]:
        placeholders = ", ".join("?" for _ in f["vendedores"])
        parts.append(f"{alias}.nome_vendedor IN ({placeholders})")
        params.extend(f["vendedores"])
    clause = _build_in_clause(f"{alias}.cod_parc", f["codParcs"], params)
    if clause:
        parts.append(clause)
    clause = _build_in_clause(f"{alias}.cod_produto", f["codProdutos"], params)
    if clause:
        parts.append(clause)
    clause = _build_in_clause(f"{alias}.grupo_produto", f["gruposProduto"], params)
    if clause:
        parts.append(clause)

    return " AND ".join(parts), params


def _build_recorrentes_orcamento_where(filtros: dict | None, alias: str = "o") -> tuple[str, list[Any]]:
    f = _normalize_filtros(filtros)
    parts: list[str] = [f"{alias}.projeto = 'RECORRENTES'"]
    params: list[Any] = []

    periodos_clause = _build_periodos_clause(alias, "dt_prev_entrega_embarque", f["periodos"], params)
    if periodos_clause:
        parts.append(periodos_clause)
    else:
        if f["dataInicio"]:
            parts.append(f"{alias}.dt_prev_entrega_embarque >= ?")
            params.append(f["dataInicio"])
        if f["dataFim"]:
            parts.append(f"{alias}.dt_prev_entrega_embarque <= ?")
            params.append(f["dataFim"])
    if f["mercados"]:
        placeholders = ", ".join("?" for _ in f["mercados"])
        parts.append(f"{alias}.mercado_vendas IN ({placeholders})")
        params.extend(f["mercados"])
    clause = _build_in_clause(f"{alias}.cod_parc", f["codParcs"], params)
    if clause:
        parts.append(clause)
    clause = _build_in_clause(f"{alias}.cod_produto", f["codProdutos"], params)
    if clause:
        parts.append(clause)
    clause = _build_in_clause(f"{alias}.grupo_produto", f["gruposProduto"], params)
    if clause:
        parts.append(clause)

    return " AND ".join(parts), params


def get_recorrentes_kpis(filtros: dict | None = None) -> dict:
    real_where, real_params = _build_recorrentes_real_where(filtros, alias="fv")
    orc_where, orc_params = _build_recorrentes_orcamento_where(filtros, alias="o")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(fv.valor_pendente), 0) AS fatAtual,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volAtual
        FROM dbo.fato_vendas fv
        WHERE {real_where}
        """,
        *real_params,
    )
    real_row = cursor.fetchone()

    cursor.execute(
        f"""
        SELECT
            COALESCE(SUM(o.valor_pendente), 0) AS orcVal,
            COALESCE(SUM(o.qtd_pendente_kg), 0) AS orcKg
        FROM dbo.orcamento_2026 o
        WHERE {orc_where}
        """,
        *orc_params,
    )
    orc_row = cursor.fetchone()

    cursor.close()
    conn.close()

    return {
        "fatAtual": _number(getattr(real_row, "fatAtual", 0)),
        "volAtual": _number(getattr(real_row, "volAtual", 0)),
        "orcVal": _number(getattr(orc_row, "orcVal", 0)),
        "orcKg": _number(getattr(orc_row, "orcKg", 0)),
    }


def list_recorrentes_tabela(filtros: dict | None = None) -> list[dict]:
    real_where, real_params = _build_recorrentes_real_where(filtros, alias="fv")
    orc_where, orc_params = _build_recorrentes_orcamento_where(filtros, alias="o")

    rows = fetch_all(
        f"""
        WITH real_data AS (
            SELECT
                fv.cod_parc,
                MAX(COALESCE(dcr.razao_social, fv.RAZAOSOCIAL)) AS razaoSocial,
                COALESCE(SUM(fv.valor_pendente), 0) AS fatAtual,
                COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volAtual
            FROM dbo.fato_vendas fv
            LEFT JOIN dbo.dim_cliente dcr ON fv.cod_parc = dcr.cod_parc
            WHERE {real_where}
            GROUP BY fv.cod_parc
        ),
        orc_data AS (
            SELECT
                o.cod_parc,
                MAX(COALESCE(dco.razao_social, fany.RAZAOSOCIAL, o.razao_social)) AS orcRazaoSocial,
                COALESCE(SUM(o.valor_pendente), 0) AS orcVal,
                COALESCE(SUM(o.qtd_pendente_kg), 0) AS orcKg
            FROM dbo.orcamento_2026 o
            LEFT JOIN dbo.dim_cliente dco ON o.cod_parc = dco.cod_parc
            LEFT JOIN (
                SELECT cod_parc, MAX(RAZAOSOCIAL) AS RAZAOSOCIAL
                FROM dbo.fato_vendas
                WHERE RAZAOSOCIAL IS NOT NULL
                GROUP BY cod_parc
            ) fany ON o.cod_parc = fany.cod_parc
            WHERE {orc_where}
            GROUP BY o.cod_parc
        )
        SELECT
            COALESCE(r.cod_parc, od.cod_parc) AS codParc,
            COALESCE(
                dc.razao_social,
                r.razaoSocial,
                od.orcRazaoSocial,
                'Cliente ' + CAST(COALESCE(r.cod_parc, od.cod_parc) AS VARCHAR)
            ) AS razaoSocial,
            COALESCE(r.volAtual, 0) AS volAtual,
            COALESCE(od.orcKg, 0) AS orcKg,
            COALESCE(r.fatAtual, 0) AS fatAtual,
            COALESCE(od.orcVal, 0) AS orcVal
        FROM real_data r
        FULL OUTER JOIN orc_data od ON r.cod_parc = od.cod_parc
        LEFT JOIN dbo.dim_cliente dc ON COALESCE(r.cod_parc, od.cod_parc) = dc.cod_parc
        ORDER BY COALESCE(r.volAtual, 0) DESC
        """,
        tuple(real_params + orc_params),
    )

    return [
        {
            "codParc": _int(row.get("codParc")),
            "razaoSocial": row.get("razaoSocial") or f"Cliente {_int(row.get('codParc'))}",
            "volAtual": _number(row.get("volAtual")),
            "orcKg": _number(row.get("orcKg")),
            "fatAtual": _number(row.get("fatAtual")),
            "orcVal": _number(row.get("orcVal")),
        }
        for row in rows
    ]


def list_recorrentes_produtos(cod_parc: int, filtros: dict | None = None) -> list[dict]:
    filtros_cliente = {**(filtros or {}), "codParc": cod_parc, "codParcs": [cod_parc]}
    real_where, real_params = _build_recorrentes_real_where(filtros_cliente, alias="fv")
    orc_where, orc_params = _build_recorrentes_orcamento_where(filtros_cliente, alias="o")

    rows = fetch_all(
        f"""
        WITH real_p AS (
            SELECT
                fv.cod_produto,
                MAX(COALESCE(dp.nome_produto, fv.nome_produto, CAST(fv.cod_produto AS VARCHAR))) AS nomeProduto,
                COALESCE(SUM(fv.valor_pendente), 0) AS fatAtual,
                COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volAtual
            FROM dbo.fato_vendas fv
            LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
            WHERE {real_where}
            GROUP BY fv.cod_produto
        ),
        orc_p AS (
            SELECT
                o.cod_produto,
                MAX(COALESCE(dp.nome_produto, fany.nome_produto)) AS orcNomeProduto,
                COALESCE(SUM(o.valor_pendente), 0) AS orcVal,
                COALESCE(SUM(o.qtd_pendente_kg), 0) AS orcKg
            FROM dbo.orcamento_2026 o
            LEFT JOIN dbo.dim_produto dp ON o.cod_produto = dp.cod_produto
            LEFT JOIN (
                SELECT cod_produto, MAX(nome_produto) AS nome_produto
                FROM dbo.fato_vendas
                WHERE nome_produto IS NOT NULL
                GROUP BY cod_produto
            ) fany ON o.cod_produto = fany.cod_produto
            WHERE {orc_where}
            GROUP BY o.cod_produto
        )
        SELECT
            COALESCE(r.cod_produto, op.cod_produto) AS codProduto,
            COALESCE(
                r.nomeProduto,
                op.orcNomeProduto,
                'Produto ' + CAST(COALESCE(r.cod_produto, op.cod_produto) AS VARCHAR)
            ) AS nomeProduto,
            COALESCE(r.volAtual, 0) AS volAtual,
            COALESCE(op.orcKg, 0) AS orcKg,
            COALESCE(r.fatAtual, 0) AS fatAtual,
            COALESCE(op.orcVal, 0) AS orcVal
        FROM real_p r
        FULL OUTER JOIN orc_p op ON r.cod_produto = op.cod_produto
        ORDER BY COALESCE(r.volAtual, 0) DESC
        """,
        tuple(real_params + orc_params),
    )

    return [
        {
            "codProduto": _int(row.get("codProduto")),
            "nomeProduto": row.get("nomeProduto") or f"Produto {_int(row.get('codProduto'))}",
            "volAtual": _number(row.get("volAtual")),
            "orcKg": _number(row.get("orcKg")),
            "fatAtual": _number(row.get("fatAtual")),
            "orcVal": _number(row.get("orcVal")),
        }
        for row in rows
    ]


def get_recorrentes_filtros() -> dict:
    vendedores = fetch_all(
        """
        SELECT DISTINCT nome_vendedor AS nome
        FROM dbo.fato_vendas
        WHERE projeto = 'RECORRENTES'
          AND nome_vendedor IS NOT NULL
        ORDER BY nome_vendedor
        """
    )
    mercados = fetch_all(
        """
        SELECT DISTINCT mercado_vendas AS nome
        FROM dbo.fato_vendas
        WHERE projeto = 'RECORRENTES'
          AND mercado_vendas IS NOT NULL
        ORDER BY mercado_vendas
        """
    )
    return {
        "vendedores": [row["nome"] for row in vendedores if row.get("nome")],
        "mercados": [row["nome"] for row in mercados if row.get("nome")],
    }

# =============================================================================
# Funil de Vendas — dados CRM migrados para REST
# =============================================================================

FUNIL_PIPELINE_BLACKLIST = (15, 23, 25)
FUNIL_PIPELINE_LABELS = {
    0: "Comercial",
    31: "Marca Própria - Private Label",
}


def _build_funil_pipeline_filter(column_expr: str, pipeline_ids: list[int] | tuple[int, ...] | None = None) -> tuple[str, tuple]:
    ids: list[int] = []
    for value in pipeline_ids or []:
        try:
            pipeline_id = int(value)
        except (TypeError, ValueError):
            continue
        if pipeline_id not in FUNIL_PIPELINE_BLACKLIST and pipeline_id not in ids:
            ids.append(pipeline_id)

    if ids:
        placeholders = ", ".join("?" for _ in ids)
        return f"AND {column_expr} IN ({placeholders})", tuple(ids)

    placeholders = ", ".join("?" for _ in FUNIL_PIPELINE_BLACKLIST)
    return f"AND {column_expr} NOT IN ({placeholders})", tuple(FUNIL_PIPELINE_BLACKLIST)


def _build_funil_user_filter(column_expr: str, user_id: int | None = None) -> tuple[str, tuple]:
    if user_id is None or user_id == "":
        return "", ()
    return f"AND {column_expr} = ?", (int(user_id),)


def _funil_filters(pipeline_ids: list[int] | tuple[int, ...] | None = None, user_id: int | None = None, alias: str = "") -> tuple[str, tuple]:
    prefix = f"{alias}." if alias else ""
    category_expr = f"CAST(COALESCE({prefix}category_id, '0') AS INT)"
    pipeline_clause, pipeline_params = _build_funil_pipeline_filter(category_expr, pipeline_ids)
    user_clause, user_params = _build_funil_user_filter(f"{prefix}assigned_by_id", user_id)
    return f"{pipeline_clause} {user_clause}", pipeline_params + user_params


def _funil_pipeline_name_sql(alias: str = "d") -> str:
    category_expr = f"CAST(COALESCE({alias}.category_id, '0') AS INT)"
    return (
        "CASE "
        f"WHEN {category_expr} = 31 THEN 'Marca Própria - Private Label' "
        f"WHEN {category_expr} = 0 THEN 'Comercial' "
        "ELSE COALESCE(p.name, 'Comercial') END"
    )


def list_funil_vendas_vendedores() -> list[dict]:
    rows = fetch_all(
        f"""
        SELECT DISTINCT
            u.id AS id,
            LTRIM(RTRIM(u.name + ' ' + COALESCE(u.last_name, ''))) AS nome
        FROM dbo.crm_users u
        JOIN dbo.crm_deals d ON d.assigned_by_id = u.id
        WHERE CAST(COALESCE(d.category_id, '0') AS INT) NOT IN ({', '.join('?' for _ in FUNIL_PIPELINE_BLACKLIST)})
        ORDER BY nome
        """,
        tuple(FUNIL_PIPELINE_BLACKLIST),
    )
    return [{"id": _int(row.get("id")), "nome": row.get("nome") or ""} for row in rows]


def get_funil_vendas_kpis(pipeline_ids: list[int] | tuple[int, ...] | None = None, user_id: int | None = None) -> list[dict]:
    filtros, params = _funil_filters(pipeline_ids, user_id)
    rows = fetch_all(
        f"""
        SELECT
            SUM(CASE WHEN stage_semantic_id = 'P' THEN 1 ELSE 0 END) AS emAndamento,
            COALESCE(SUM(CASE WHEN stage_semantic_id = 'P' THEN opportunity ELSE 0 END), 0) AS valorPipeline,
            SUM(CASE WHEN stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS ganhos,
            COALESCE(SUM(CASE WHEN stage_semantic_id = 'S' THEN opportunity ELSE 0 END), 0) AS valorGanho,
            SUM(CASE WHEN stage_semantic_id = 'F' THEN 1 ELSE 0 END) AS perdidos,
            CASE
                WHEN SUM(CASE WHEN stage_semantic_id IN ('S','F') THEN 1 ELSE 0 END) = 0 THEN 0
                ELSE CAST(SUM(CASE WHEN stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS FLOAT)
                    / SUM(CASE WHEN stage_semantic_id IN ('S','F') THEN 1 ELSE 0 END) * 100
            END AS taxaConversao,
            COALESCE(AVG(CASE
                WHEN stage_semantic_id = 'S' AND closedate IS NOT NULL AND date_create IS NOT NULL
                THEN DATEDIFF(day, TRY_CAST(date_create AS DATE), TRY_CAST(closedate AS DATE))
                ELSE NULL
            END), 0) AS diasMedioFechamento
        FROM dbo.crm_deals
        WHERE 1 = 1 {filtros}
        """,
        params,
    )
    row = rows[0] if rows else {}
    return [{
        "emAndamento": _int(row.get("emAndamento")),
        "valorPipeline": _number(row.get("valorPipeline")),
        "ganhos": _int(row.get("ganhos")),
        "valorGanho": _number(row.get("valorGanho")),
        "perdidos": _int(row.get("perdidos")),
        "taxaConversao": _number(row.get("taxaConversao")),
        "diasMedioFechamento": _number(row.get("diasMedioFechamento")),
    }]


def list_funil_vendas_por_etapa(pipeline_ids: list[int] | tuple[int, ...] | None = None, user_id: int | None = None) -> list[dict]:
    filtros, params = _funil_filters(pipeline_ids, user_id, alias="d")
    pipeline_name = _funil_pipeline_name_sql("d")
    rows = fetch_all(
        f"""
        SELECT
            ds.name AS etapa,
            {pipeline_name} AS pipeline,
            COUNT(*) AS total,
            COALESCE(SUM(d.opportunity), 0) AS valorTotal,
            ds.semantic AS semantic,
            CAST(COALESCE(d.category_id, '0') AS INT) AS pipelineId,
            ds.status_id AS stageId
        FROM dbo.crm_deals d
        LEFT JOIN dbo.crm_deal_stages ds ON d.stage_id = ds.status_id
        LEFT JOIN dbo.crm_pipelines p ON CAST(COALESCE(d.category_id, '0') AS INT) = p.id
        WHERE d.stage_semantic_id = 'P'
          {filtros}
        GROUP BY ds.name, {pipeline_name}, ds.semantic, CAST(COALESCE(d.category_id, '0') AS INT), ds.status_id
        ORDER BY CAST(COALESCE(d.category_id, '0') AS INT), ds.status_id
        """,
        params,
    )
    return [
        {
            "etapa": row.get("etapa") or "Sem etapa",
            "pipeline": row.get("pipeline") or "Comercial",
            "total": _int(row.get("total")),
            "valorTotal": _number(row.get("valorTotal")),
            "semantic": row.get("semantic") or "",
            "pipelineId": _int(row.get("pipelineId")),
            "stageId": row.get("stageId") or "",
        }
        for row in rows
    ]


def list_funil_vendas_por_pipeline(pipeline_ids: list[int] | tuple[int, ...] | None = None, user_id: int | None = None) -> list[dict]:
    filtros, params = _funil_filters(pipeline_ids, user_id, alias="d")
    pipeline_name = _funil_pipeline_name_sql("d")
    rows = fetch_all(
        f"""
        SELECT
            {pipeline_name} AS pipeline,
            CAST(COALESCE(d.category_id, '0') AS INT) AS pipelineId,
            SUM(CASE WHEN d.stage_semantic_id = 'P' THEN 1 ELSE 0 END) AS emAndamento,
            SUM(CASE WHEN d.stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS ganhos,
            SUM(CASE WHEN d.stage_semantic_id = 'F' THEN 1 ELSE 0 END) AS perdidos,
            COALESCE(SUM(CASE WHEN d.stage_semantic_id = 'P' THEN d.opportunity ELSE 0 END), 0) AS valorPipeline,
            CASE
                WHEN SUM(CASE WHEN d.stage_semantic_id IN ('S','F') THEN 1 ELSE 0 END) = 0 THEN 0
                ELSE CAST(SUM(CASE WHEN d.stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS FLOAT)
                    / SUM(CASE WHEN d.stage_semantic_id IN ('S','F') THEN 1 ELSE 0 END) * 100
            END AS taxaConversao
        FROM dbo.crm_deals d
        LEFT JOIN dbo.crm_pipelines p ON CAST(COALESCE(d.category_id, '0') AS INT) = p.id
        WHERE 1 = 1 {filtros}
        GROUP BY {pipeline_name}, CAST(COALESCE(d.category_id, '0') AS INT)
        ORDER BY valorPipeline DESC
        """,
        params,
    )
    return [
        {
            "pipeline": row.get("pipeline") or "Comercial",
            "pipelineId": _int(row.get("pipelineId")),
            "emAndamento": _int(row.get("emAndamento")),
            "ganhos": _int(row.get("ganhos")),
            "perdidos": _int(row.get("perdidos")),
            "valorPipeline": _number(row.get("valorPipeline")),
            "taxaConversao": _number(row.get("taxaConversao")),
        }
        for row in rows
    ]


def list_funil_vendas_top_vendedores(pipeline_ids: list[int] | tuple[int, ...] | None = None, user_id: int | None = None) -> list[dict]:
    filtros, params = _funil_filters(pipeline_ids, user_id, alias="d")
    rows = fetch_all(
        f"""
        SELECT TOP 10
            LTRIM(RTRIM(u.name + ' ' + COALESCE(u.last_name, ''))) AS nome,
            SUM(CASE WHEN d.stage_semantic_id = 'P' THEN 1 ELSE 0 END) AS emAndamento,
            SUM(CASE WHEN d.stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS ganhos,
            SUM(CASE WHEN d.stage_semantic_id = 'F' THEN 1 ELSE 0 END) AS perdidos,
            COALESCE(SUM(CASE WHEN d.stage_semantic_id = 'P' THEN d.opportunity ELSE 0 END), 0) AS valorPipeline,
            CASE
                WHEN SUM(CASE WHEN d.stage_semantic_id IN ('S','F') THEN 1 ELSE 0 END) = 0 THEN 0
                ELSE CAST(SUM(CASE WHEN d.stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS FLOAT)
                    / SUM(CASE WHEN d.stage_semantic_id IN ('S','F') THEN 1 ELSE 0 END) * 100
            END AS taxaConversao
        FROM dbo.crm_deals d
        JOIN dbo.crm_users u ON d.assigned_by_id = u.id
        WHERE 1 = 1 {filtros}
        GROUP BY d.assigned_by_id, u.name, u.last_name
        ORDER BY valorPipeline DESC
        """,
        params,
    )
    return [
        {
            "nome": row.get("nome") or "",
            "emAndamento": _int(row.get("emAndamento")),
            "ganhos": _int(row.get("ganhos")),
            "perdidos": _int(row.get("perdidos")),
            "valorPipeline": _number(row.get("valorPipeline")),
            "taxaConversao": _number(row.get("taxaConversao")),
        }
        for row in rows
    ]


def list_funil_vendas_evolucao_mensal(pipeline_ids: list[int] | tuple[int, ...] | None = None, user_id: int | None = None) -> list[dict]:
    filtros, params = _funil_filters(pipeline_ids, user_id)
    rows = fetch_all(
        f"""
        SELECT
            FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM') AS mes,
            SUM(CASE WHEN stage_semantic_id = 'P' THEN 1 ELSE 0 END) AS abertos,
            SUM(CASE WHEN stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS ganhos,
            SUM(CASE WHEN stage_semantic_id = 'F' THEN 1 ELSE 0 END) AS perdidos
        FROM dbo.crm_deals
        WHERE date_create IS NOT NULL
          AND TRY_CAST(date_create AS DATE) >= DATEADD(month, -12, GETDATE())
          {filtros}
        GROUP BY FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM')
        ORDER BY mes
        """,
        params,
    )
    return [
        {
            "mes": row.get("mes") or "",
            "abertos": _int(row.get("abertos")),
            "ganhos": _int(row.get("ganhos")),
            "perdidos": _int(row.get("perdidos")),
        }
        for row in rows
    ]


# =============================================================================
# Panorama CRM — dados originais migrados para REST
# =============================================================================

PANORAMA_CRM_ORIGENS_VALIDAS = {"leads", "base", "total"}
PANORAMA_CRM_VISOES_VALIDAS = {"calendario", "coorte"}


def _panorama_pipeline_clause(pipeline_id: int | None) -> str:
    if pipeline_id == 31:
        return "category_id = '31'"
    if pipeline_id is None:
        return f"CAST(COALESCE(category_id, '0') AS INT) NOT IN ({','.join(str(x) for x in PIPELINE_BLACKLIST)})"
    return "(category_id = '0' OR category_id IS NULL)"


def _panorama_origem_clause(origem: str | None) -> str:
    origem_normalizada = origem if origem in PANORAMA_CRM_ORIGENS_VALIDAS else "total"
    if origem_normalizada == "leads":
        return "AND lead_id IS NOT NULL"
    if origem_normalizada == "base":
        return "AND lead_id IS NULL"
    return ""


def _panorama_user_clause(user_id: int | None, params: list) -> str:
    if user_id is None:
        return ""
    params.append(int(user_id))
    return "AND assigned_by_id = ?"


def _panorama_validar_visao(visao: str | None) -> str:
    return visao if visao in PANORAMA_CRM_VISOES_VALIDAS else "calendario"


def list_panorama_crm_vendedores() -> list[dict]:
    return list_crm_mapping_vendedores_original()


def get_panorama_leads_snapshot() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) AS em_andamento
        FROM dbo.crm_leads
        WHERE status_semantic_id = 'P'
    """)
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return _int(row.em_andamento) if row else 0


def get_panorama_deals_snapshot(pipeline_id: int | None = None, origem: str = "total", user_id: int | None = None) -> dict:
    params: list = []
    pipeline_clause = _panorama_pipeline_clause(pipeline_id)
    origem_clause = _panorama_origem_clause(origem)
    user_clause = _panorama_user_clause(user_id, params)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS em_andamento,
            COALESCE(SUM(opportunity), 0) AS valor_em_andamento
        FROM dbo.crm_deals
        WHERE stage_semantic_id = 'P'
          AND {pipeline_clause}
          {origem_clause}
          {user_clause}
        """,
        *params,
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    return {
        "emAndamento": _int(row.em_andamento) if row else 0,
        "valorEmAndamento": _number(row.valor_em_andamento) if row else 0,
    }


def get_panorama_leads(date_ini: str, date_fim: str, visao: str = "calendario") -> dict:
    visao_normalizada = _panorama_validar_visao(visao)
    conn = get_connection()
    cursor = conn.cursor()

    if visao_normalizada == "calendario":
        cursor.execute(
            """
            SELECT
                FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM') AS periodo,
                COUNT(*) AS criados,
                SUM(CASE WHEN TRY_CAST(moved_time AS DATE) BETWEEN ? AND ? THEN 1 ELSE 0 END) AS com_movimentacao
            FROM dbo.crm_leads
            WHERE TRY_CAST(date_create AS DATE) BETWEEN ? AND ?
            GROUP BY FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM')
            ORDER BY periodo
            """,
            date_ini,
            date_fim,
            date_ini,
            date_fim,
        )
        criados_rows = cursor.fetchall()
        criados = [
            {
                "periodo": row.periodo,
                "criados": _int(row.criados),
                "comMovimentacao": _int(row.com_movimentacao),
            }
            for row in criados_rows
        ]

        cursor.execute(
            """
            SELECT
                FORMAT(TRY_CAST(date_closed AS DATE), 'yyyy-MM') AS periodo,
                SUM(CASE WHEN status_id = 'CONVERTED' THEN 1 ELSE 0 END) AS convertidos,
                SUM(CASE WHEN status_semantic_id = 'F' THEN 1 ELSE 0 END) AS perdidos,
                AVG(DATEDIFF(day, TRY_CAST(date_create AS DATE), TRY_CAST(date_closed AS DATE))) AS ciclo_medio
            FROM dbo.crm_leads
            WHERE TRY_CAST(date_closed AS DATE) BETWEEN ? AND ?
              AND status_semantic_id IN ('S', 'F')
            GROUP BY FORMAT(TRY_CAST(date_closed AS DATE), 'yyyy-MM')
            ORDER BY periodo
            """,
            date_ini,
            date_fim,
        )
        fechados_rows = cursor.fetchall()
        fechados = [
            {
                "periodo": row.periodo,
                "convertidos": _int(row.convertidos),
                "perdidos": _int(row.perdidos),
                "cicloMedio": _number(row.ciclo_medio) if row.ciclo_medio is not None else None,
            }
            for row in fechados_rows
        ]

        cursor.close()
        conn.close()
        return {"criados": criados, "fechados": fechados}

    cursor.execute(
        """
        SELECT
            FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM') AS periodo,
            COUNT(*) AS criados,
            SUM(CASE WHEN TRY_CAST(moved_time AS DATE) BETWEEN ? AND ? THEN 1 ELSE 0 END) AS com_movimentacao,
            SUM(CASE WHEN status_semantic_id = 'P' AND (date_closed IS NULL OR TRY_CAST(date_closed AS DATE) > ?) THEN 1 ELSE 0 END) AS em_andamento,
            SUM(CASE WHEN status_id = 'CONVERTED' THEN 1 ELSE 0 END) AS convertidos,
            SUM(CASE WHEN status_semantic_id = 'F' THEN 1 ELSE 0 END) AS perdidos,
            CAST(SUM(CASE WHEN status_id = 'CONVERTED' THEN 1 ELSE 0 END) AS FLOAT)
              / NULLIF(
                  SUM(CASE WHEN status_semantic_id = 'P' AND (date_closed IS NULL OR TRY_CAST(date_closed AS DATE) > ?) THEN 1 ELSE 0 END)
                + SUM(CASE WHEN status_id = 'CONVERTED' THEN 1 ELSE 0 END)
                + SUM(CASE WHEN status_semantic_id = 'F' THEN 1 ELSE 0 END),
                0
              ) * 100 AS taxa_conv,
            AVG(CASE WHEN date_closed IS NOT NULL THEN DATEDIFF(day, TRY_CAST(date_create AS DATE), TRY_CAST(date_closed AS DATE)) END) AS ciclo_medio
        FROM dbo.crm_leads
        WHERE TRY_CAST(date_create AS DATE) BETWEEN ? AND ?
        GROUP BY FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM')
        ORDER BY periodo
        """,
        date_ini,
        date_fim,
        date_fim,
        date_fim,
        date_ini,
        date_fim,
    )
    rows_raw = cursor.fetchall()
    cursor.close()
    conn.close()

    return {
        "rows": [
            {
                "periodo": row.periodo,
                "criados": _int(row.criados),
                "comMovimentacao": _int(row.com_movimentacao),
                "emAndamento": _int(row.em_andamento),
                "convertidos": _int(row.convertidos),
                "perdidos": _int(row.perdidos),
                "taxaConv": _number(row.taxa_conv) if row.taxa_conv is not None else None,
                "cicloMedio": _number(row.ciclo_medio) if row.ciclo_medio is not None else None,
            }
            for row in rows_raw
        ]
    }


def get_panorama_deals(
    date_ini: str,
    date_fim: str,
    visao: str = "calendario",
    pipeline_id: int | None = None,
    origem: str = "total",
    user_id: int | None = None,
) -> dict:
    visao_normalizada = _panorama_validar_visao(visao)
    pipeline_clause = _panorama_pipeline_clause(pipeline_id)
    origem_clause = _panorama_origem_clause(origem)

    conn = get_connection()
    cursor = conn.cursor()

    if visao_normalizada == "calendario":
        params_criados: list = [date_ini, date_fim]
        user_clause_criados = _panorama_user_clause(user_id, params_criados)
        cursor.execute(
            f"""
            SELECT
                FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM') AS periodo,
                COUNT(*) AS criados
            FROM dbo.crm_deals
            WHERE TRY_CAST(date_create AS DATE) BETWEEN ? AND ?
              AND {pipeline_clause}
              {origem_clause}
              {user_clause_criados}
            GROUP BY FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM')
            ORDER BY periodo
            """,
            *params_criados,
        )
        criados_rows = cursor.fetchall()
        criados = [
            {"periodo": row.periodo, "criados": _int(row.criados)}
            for row in criados_rows
        ]

        params_fechados: list = [date_ini, date_fim]
        user_clause_fechados = _panorama_user_clause(user_id, params_fechados)
        cursor.execute(
            f"""
            SELECT
                FORMAT(TRY_CAST(closedate AS DATE), 'yyyy-MM') AS periodo,
                SUM(CASE WHEN stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS ganhos,
                COALESCE(SUM(CASE WHEN stage_semantic_id = 'S' THEN opportunity END), 0) AS valor_ganhos,
                SUM(CASE WHEN stage_semantic_id = 'F' THEN 1 ELSE 0 END) AS perdidos,
                AVG(DATEDIFF(day, TRY_CAST(date_create AS DATE), TRY_CAST(closedate AS DATE))) AS ciclo_total,
                AVG(CASE WHEN stage_semantic_id = 'S' THEN DATEDIFF(day, TRY_CAST(date_create AS DATE), TRY_CAST(closedate AS DATE)) END) AS ciclo_ganhos
            FROM dbo.crm_deals
            WHERE TRY_CAST(closedate AS DATE) BETWEEN ? AND ?
              AND stage_semantic_id IN ('S', 'F')
              AND {pipeline_clause}
              {origem_clause}
              {user_clause_fechados}
            GROUP BY FORMAT(TRY_CAST(closedate AS DATE), 'yyyy-MM')
            ORDER BY periodo
            """,
            *params_fechados,
        )
        fechados_rows = cursor.fetchall()
        fechados = [
            {
                "periodo": row.periodo,
                "ganhos": _int(row.ganhos),
                "valorGanhos": _number(row.valor_ganhos),
                "perdidos": _int(row.perdidos),
                "cicloTotal": _number(row.ciclo_total) if row.ciclo_total is not None else None,
                "cicloGanhos": _number(row.ciclo_ganhos) if row.ciclo_ganhos is not None else None,
            }
            for row in fechados_rows
        ]

        cursor.close()
        conn.close()
        return {"criados": criados, "fechados": fechados}

    params: list = [date_fim, date_fim, date_fim, date_ini, date_fim]
    user_clause = _panorama_user_clause(user_id, params)
    cursor.execute(
        f"""
        SELECT
            FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM') AS periodo,
            COUNT(*) AS criados,
            SUM(CASE WHEN stage_semantic_id = 'P' AND (closedate IS NULL OR TRY_CAST(closedate AS DATE) > ?) THEN 1 ELSE 0 END) AS em_andamento,
            COALESCE(SUM(CASE WHEN stage_semantic_id = 'P' AND (closedate IS NULL OR TRY_CAST(closedate AS DATE) > ?) THEN opportunity END), 0) AS valor_em_andamento,
            SUM(CASE WHEN stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS ganhos,
            COALESCE(SUM(CASE WHEN stage_semantic_id = 'S' THEN opportunity END), 0) AS valor_ganhos,
            SUM(CASE WHEN stage_semantic_id = 'F' THEN 1 ELSE 0 END) AS perdidos,
            CAST(SUM(CASE WHEN stage_semantic_id = 'S' THEN 1 ELSE 0 END) AS FLOAT)
              / NULLIF(
                  SUM(CASE WHEN stage_semantic_id = 'P' AND (closedate IS NULL OR TRY_CAST(closedate AS DATE) > ?) THEN 1 ELSE 0 END)
                + SUM(CASE WHEN stage_semantic_id = 'S' THEN 1 ELSE 0 END)
                + SUM(CASE WHEN stage_semantic_id = 'F' THEN 1 ELSE 0 END),
                0
              ) * 100 AS taxa_conv,
            AVG(CASE WHEN stage_semantic_id IN ('S', 'F') AND closedate IS NOT NULL THEN DATEDIFF(day, TRY_CAST(date_create AS DATE), TRY_CAST(closedate AS DATE)) END) AS ciclo_total,
            AVG(CASE WHEN stage_semantic_id = 'S' AND closedate IS NOT NULL THEN DATEDIFF(day, TRY_CAST(date_create AS DATE), TRY_CAST(closedate AS DATE)) END) AS ciclo_ganhos
        FROM dbo.crm_deals
        WHERE TRY_CAST(date_create AS DATE) BETWEEN ? AND ?
          AND {pipeline_clause}
          {origem_clause}
          {user_clause}
        GROUP BY FORMAT(TRY_CAST(date_create AS DATE), 'yyyy-MM')
        ORDER BY periodo
        """,
        *params,
    )
    rows_raw = cursor.fetchall()
    cursor.close()
    conn.close()

    return {
        "rows": [
            {
                "periodo": row.periodo,
                "criados": _int(row.criados),
                "emAndamento": _int(row.em_andamento),
                "valorEmAndamento": _number(row.valor_em_andamento),
                "ganhos": _int(row.ganhos),
                "valorGanhos": _number(row.valor_ganhos),
                "perdidos": _int(row.perdidos),
                "taxaConv": _number(row.taxa_conv) if row.taxa_conv is not None else None,
                "cicloTotal": _number(row.ciclo_total) if row.ciclo_total is not None else None,
                "cicloGanhos": _number(row.ciclo_ganhos) if row.ciclo_ganhos is not None else None,
            }
            for row in rows_raw
        ]
    }

# =============================================================================
# Agente IA / Chatbot — persistência e ferramenta SQL Server de produção
# =============================================================================

def _chat_datetime_to_iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _chat_value_to_json(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def ensure_chat_messages_table() -> None:
    """Garante a existência da tabela usada pelo Agente IA."""
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            IF OBJECT_ID('dbo.chat_messages', 'U') IS NULL
            BEGIN
                CREATE TABLE dbo.chat_messages (
                    id INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                    session_id NVARCHAR(64) NOT NULL,
                    user_id INT NULL,
                    role NVARCHAR(20) NOT NULL,
                    content NVARCHAR(MAX) NOT NULL,
                    created_at DATETIME2 NOT NULL CONSTRAINT DF_chat_messages_created_at DEFAULT SYSUTCDATETIME()
                );
            END;

            IF NOT EXISTS (
                SELECT 1
                FROM sys.indexes
                WHERE name = 'IX_chat_messages_session_created'
                  AND object_id = OBJECT_ID('dbo.chat_messages')
            )
            BEGIN
                CREATE INDEX IX_chat_messages_session_created
                ON dbo.chat_messages (session_id, created_at);
            END;

            IF NOT EXISTS (
                SELECT 1
                FROM sys.indexes
                WHERE name = 'IX_chat_messages_user_session'
                  AND object_id = OBJECT_ID('dbo.chat_messages')
            )
            BEGIN
                CREATE INDEX IX_chat_messages_user_session
                ON dbo.chat_messages (user_id, session_id);
            END;
            """
        )
        connection.commit()


def _serialize_chat_message(row: dict) -> dict:
    return {
        "id": int(row.get("id")) if row.get("id") is not None else None,
        "session_id": row.get("session_id"),
        "role": row.get("role"),
        "content": row.get("content"),
        "created_at": _chat_datetime_to_iso(row.get("created_at")),
    }


def _serialize_chat_session(row: dict) -> dict:
    return {
        "session_id": row.get("session_id"),
        "title": row.get("title"),
        "last_at": _chat_datetime_to_iso(row.get("last_at")),
        "message_count": int(row.get("message_count") or 0),
    }


def get_chat_history(session_id: str, limit: int = 50) -> list[dict]:
    ensure_chat_messages_table()
    safe_limit = max(1, min(int(limit or 50), 200))
    rows = fetch_all(
        f"""
        SELECT TOP ({safe_limit})
            id,
            session_id,
            role,
            content,
            created_at
        FROM dbo.chat_messages
        WHERE session_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (session_id,),
    )
    return [_serialize_chat_message(row) for row in rows]


def save_chat_message(session_id: str, user_id: int | None, role: str, content: str) -> dict:
    ensure_chat_messages_table()
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO dbo.chat_messages (session_id, user_id, role, content)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, user_id, role, content),
        )
        connection.commit()
    return {"success": True}


def clear_chat_history(session_id: str) -> dict:
    ensure_chat_messages_table()
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            "DELETE FROM dbo.chat_messages WHERE session_id = ?",
            (session_id,),
        )
        connection.commit()
    return {"success": True}


def get_chat_sessions(user_id: int) -> list[dict]:
    ensure_chat_messages_table()
    rows = fetch_all(
        """
        SELECT
            m.session_id,
            MIN(CASE WHEN m.role = 'user' THEN m.content ELSE NULL END) AS title,
            MAX(m.created_at) AS last_at,
            COUNT(*) AS message_count
        FROM dbo.chat_messages m
        WHERE m.session_id IN (
            SELECT DISTINCT session_id
            FROM dbo.chat_messages
            WHERE user_id = ?
        )
        GROUP BY m.session_id
        ORDER BY MAX(m.created_at) DESC
        """,
        (user_id,),
    )
    return [_serialize_chat_session(row) for row in rows]



def _agent_find_table_schema(table_name: str) -> str | None:
    """Localiza tabela ou view por nome, sem depender do schema dbo nem de maiúsculas/minúsculas."""
    rows = fetch_all(
        """
        SELECT TOP (1) TABLE_SCHEMA AS table_schema
        FROM INFORMATION_SCHEMA.TABLES
        WHERE LOWER(TABLE_NAME) = LOWER(?)
        ORDER BY
            CASE WHEN TABLE_SCHEMA = 'dbo' THEN 0 ELSE 1 END,
            CASE WHEN TABLE_TYPE = 'BASE TABLE' THEN 0 ELSE 1 END,
            TABLE_SCHEMA
        """,
        (table_name,),
    )
    if not rows:
        return None
    schema = rows[0].get("table_schema")
    return str(schema) if schema else None


def _agent_table_columns(table_schema: str, table_name: str) -> set[str]:
    rows = fetch_all(
        """
        SELECT COLUMN_NAME AS column_name
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ?
          AND LOWER(TABLE_NAME) = LOWER(?)
        """,
        (table_schema, table_name),
    )
    return {str(row.get("column_name")) for row in rows if row.get("column_name")}


def _agent_table_inventory(limit: int = 120) -> list[dict]:
    return fetch_all(
        f"""
        SELECT TOP ({max(1, min(int(limit or 120), 500))})
            t.TABLE_SCHEMA AS table_schema,
            t.TABLE_NAME AS table_name,
            t.TABLE_TYPE AS table_type,
            COUNT(c.COLUMN_NAME) AS column_count
        FROM INFORMATION_SCHEMA.TABLES t
        LEFT JOIN INFORMATION_SCHEMA.COLUMNS c
          ON c.TABLE_SCHEMA = t.TABLE_SCHEMA
         AND c.TABLE_NAME = t.TABLE_NAME
        GROUP BY t.TABLE_SCHEMA, t.TABLE_NAME, t.TABLE_TYPE
        ORDER BY
            CASE
                WHEN LOWER(t.TABLE_NAME) LIKE '%fato%venda%' THEN 0
                WHEN LOWER(t.TABLE_NAME) LIKE '%venda%' THEN 1
                WHEN LOWER(t.TABLE_NAME) LIKE '%b2b%' THEN 2
                WHEN LOWER(t.TABLE_NAME) LIKE '%orc%' THEN 3
                WHEN LOWER(t.TABLE_NAME) LIKE '%pedido%' THEN 4
                WHEN LOWER(t.TABLE_NAME) LIKE '%nota%' THEN 5
                ELSE 9
            END,
            t.TABLE_SCHEMA,
            t.TABLE_NAME
        """
    )


def _agent_quote_identifier(identifier: str) -> str:
    return "[" + str(identifier).replace("]", "]]" ) + "]"


def _agent_normalize_tipo_receita(tipo_receita) -> str:
    raw = str(tipo_receita or "").strip()
    upper = raw.upper()
    if "VENDA" in upper and "FIRME" in upper:
        return "Vendas Firmes"
    if upper in {"VENDA", "VENDAS", "VENDA_FIRME", "VENDAS_FIRMES"} or "FIRME" in upper:
        return "Vendas Firmes"
    if "FORECAST" in upper or "PREV" in upper or "ORC" in upper:
        return "Forecast"
    if "NOVO" in upper or "PROJETO" in upper:
        return "Projetos"
    # Regra do projeto original local: DEVOLUCAO não aparece como linha separada.
    # Ela compõe Vendas Firmes para reproduzir o total exibido na base de teste.
    if "DEVOL" in upper:
        return "Vendas Firmes"
    return raw or "Sem categoria"


def _agent_fetch_rows(query: str, params: tuple | list = ()) -> list[dict]:
    """Executa SELECT interno e devolve lista de dict para rotinas determinísticas."""
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(query, tuple(params or ()))
        if cursor.description is None:
            return []
        columns = [column[0] for column in cursor.description]
        fetched = cursor.fetchall()
    return [
        {columns[i]: _chat_value_to_json(value) for i, value in enumerate(row)}
        for row in fetched
    ]


def _agent_aggregate_revenue_rows(raw_rows: list[dict]) -> tuple[list[dict], float]:
    aggregated: dict[str, dict] = {}
    for row in raw_rows:
        categoria_raw = row.get("categoria") or row.get("tipo_receita")
        origem = row.get("origem") or row.get("tipo_receita") or categoria_raw
        categoria = _agent_normalize_tipo_receita(categoria_raw)
        total_value = float(row.get("total") or 0)
        origem_text = f"{categoria_raw or ''} {origem or ''}".upper()
        if "DEVOL" in origem_text:
            total_value = abs(total_value)
        current = aggregated.setdefault(
            categoria,
            {"categoria": categoria, "tipo_receita_origem": [], "total": 0.0, "percentual": 0.0},
        )
        if origem is not None and str(origem) not in current["tipo_receita_origem"]:
            current["tipo_receita_origem"].append(str(origem))
        current["total"] += total_value

    preferred_order = {"Vendas Firmes": 0, "Forecast": 1, "Projetos": 2}
    rows = sorted(
        aggregated.values(),
        key=lambda item: (preferred_order.get(item["categoria"], 99), -float(item["total"] or 0)),
    )
    total_geral = sum(float(item["total"] or 0) for item in rows)
    for item in rows:
        item["percentual"] = (float(item["total"] or 0) / total_geral * 100.0) if total_geral else 0.0
        item["total"] = round(float(item["total"] or 0), 2)
        item["percentual"] = round(float(item["percentual"] or 0), 2)
    return rows, round(total_geral, 2)


def _agent_get_exact_table_name(schema: str, desired_name: str) -> str:
    rows = fetch_all(
        """
        SELECT TOP (1) TABLE_NAME AS table_name
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = ? AND LOWER(TABLE_NAME) = LOWER(?)
        ORDER BY CASE WHEN TABLE_TYPE = 'BASE TABLE' THEN 0 ELSE 1 END, TABLE_NAME
        """,
        (schema, desired_name),
    )
    return str(rows[0].get("table_name")) if rows else desired_name


def _agent_query_faturamento_fato_vendas(ano_int: int) -> dict | None:
    schema = _agent_find_table_schema("fato_vendas")
    if not schema:
        return None

    table_name = _agent_get_exact_table_name(schema, "fato_vendas")
    columns = _agent_table_columns(schema, table_name)
    required = {"dt_entrega_cliente", "tipo_receita", "valor_pendente"}
    missing = sorted(required - columns)
    if missing:
        return {
            "success": False,
            "source_found": f"{schema}.{table_name}",
            "error": "Colunas obrigatórias ausentes em fato_vendas: " + ", ".join(missing),
            "available_columns": sorted(columns),
            "rows": [],
            "total": 0.0,
        }

    filters = ["dt_entrega_cliente >= ?", "dt_entrega_cliente < ?"]
    params: list = [f"{ano_int}-01-01", f"{ano_int + 1}-01-01"]
    # No resultado original da base local, o chat não removia cod_top=1023 nem TOP contendo
    # ESTOQUE MINIM; por isso estes filtros não são aplicados neste cálculo determinístico.

    table_ref = f"{_agent_quote_identifier(schema)}.{_agent_quote_identifier(table_name)}"
    query = f"""
        SELECT
            tipo_receita AS categoria,
            tipo_receita AS origem,
            SUM(COALESCE(valor_pendente, 0)) AS total
        FROM {table_ref}
        WHERE {' AND '.join(filters)}
        GROUP BY tipo_receita
        ORDER BY total DESC
    """
    raw_rows = _agent_fetch_rows(query, params)
    rows, total_geral = _agent_aggregate_revenue_rows(raw_rows)
    return {
        "success": True,
        "ano": ano_int,
        "source": "fato_vendas",
        "rows": rows,
        "total": total_geral,
        "query_context": {
            "table": f"{schema}.{table_name}",
            "date_filter": f"dt_entrega_cliente >= {ano_int}-01-01 AND < {ano_int + 1}-01-01",
            "observacao": "Fonte analítica principal encontrada no banco como tabela ou view.",
        },
    }


def _agent_query_faturamento_base_local(ano_int: int) -> dict | None:
    raw_rows: list[dict] = []
    fontes: list[str] = []
    erros: list[str] = []

    b2b_schema = _agent_find_table_schema("B2B")
    if b2b_schema:
        b2b_table = _agent_get_exact_table_name(b2b_schema, "B2B")
        b2b_columns = _agent_table_columns(b2b_schema, b2b_table)
        valor_col = next((col for col in ("ValorPendente", "valor_pendente", "VLRNOTA", "VLRDESDOB", "VALOR", "valor") if col in b2b_columns), None)
        date_col = next((col for col in ("DTMOV", "DTNEG", "dt_mov", "dtneg", "data", "DATA") if col in b2b_columns), None)
        if valor_col and date_col:
            projeto_expr = _agent_quote_identifier("PROJETO") if "PROJETO" in b2b_columns else (_agent_quote_identifier("projeto") if "projeto" in b2b_columns else "NULL")
            table_ref = f"{_agent_quote_identifier(b2b_schema)}.{_agent_quote_identifier(b2b_table)}"
            query = f"""
                SELECT
                    CASE
                        WHEN UPPER(COALESCE(CAST({projeto_expr} AS varchar(255)), '')) LIKE '%NOVO%' OR UPPER(COALESCE(CAST({projeto_expr} AS varchar(255)), '')) LIKE '%PROJETO%' THEN 'Projetos'
                        ELSE 'Vendas Firmes'
                    END AS categoria,
                    ? AS origem,
                    SUM(COALESCE(TRY_CONVERT(float, {_agent_quote_identifier(valor_col)}), 0)) AS total
                FROM {table_ref}
                WHERE TRY_CONVERT(date, {_agent_quote_identifier(date_col)}) >= ?
                  AND TRY_CONVERT(date, {_agent_quote_identifier(date_col)}) < ?
                GROUP BY CASE
                        WHEN UPPER(COALESCE(CAST({projeto_expr} AS varchar(255)), '')) LIKE '%NOVO%' OR UPPER(COALESCE(CAST({projeto_expr} AS varchar(255)), '')) LIKE '%PROJETO%' THEN 'Projetos'
                        ELSE 'Vendas Firmes'
                    END
            """
            try:
                rows = _agent_fetch_rows(query, [b2b_table, f"{ano_int}-01-01", f"{ano_int + 1}-01-01"])
                raw_rows.extend(rows)
                fontes.append(f"{b2b_schema}.{b2b_table}")
            except Exception as exc:
                erros.append(f"{b2b_table}: {exc}")

    for table_name in ("orcamento_2026", "orcamento", "orcamentos"):
        schema = _agent_find_table_schema(table_name)
        if not schema:
            continue
        exact_table = _agent_get_exact_table_name(schema, table_name)
        columns = _agent_table_columns(schema, exact_table)
        value_col = next((col for col in ("valor_pendente", "ValorPendente", "valor", "VALOR", "vlr_total", "VLR_TOTAL") if col in columns), None)
        date_col = next((col for col in ("dt_prev_entrega_embarque", "dt_entrega_cliente", "DTMOV", "DTNEG", "data", "DATA") if col in columns), None)
        if not value_col or not date_col:
            erros.append(f"{exact_table}: não encontrei coluna de valor/data compatível")
            continue
        projeto_expr = _agent_quote_identifier("projeto") if "projeto" in columns else (_agent_quote_identifier("PROJETO") if "PROJETO" in columns else "NULL")
        table_ref = f"{_agent_quote_identifier(schema)}.{_agent_quote_identifier(exact_table)}"
        query = f"""
            SELECT
                CASE
                    WHEN UPPER(COALESCE(CAST({projeto_expr} AS varchar(255)), '')) LIKE '%NOVO%' OR UPPER(COALESCE(CAST({projeto_expr} AS varchar(255)), '')) LIKE '%PROJETO%' THEN 'Projetos'
                    ELSE 'Forecast'
                END AS categoria,
                ? AS origem,
                SUM(COALESCE(TRY_CONVERT(float, {_agent_quote_identifier(value_col)}), 0)) AS total
            FROM {table_ref}
            WHERE TRY_CONVERT(date, {_agent_quote_identifier(date_col)}) >= ?
              AND TRY_CONVERT(date, {_agent_quote_identifier(date_col)}) < ?
            GROUP BY CASE
                    WHEN UPPER(COALESCE(CAST({projeto_expr} AS varchar(255)), '')) LIKE '%NOVO%' OR UPPER(COALESCE(CAST({projeto_expr} AS varchar(255)), '')) LIKE '%PROJETO%' THEN 'Projetos'
                    ELSE 'Forecast'
                END
        """
        try:
            rows = _agent_fetch_rows(query, [exact_table, f"{ano_int}-01-01", f"{ano_int + 1}-01-01"])
            raw_rows.extend(rows)
            fontes.append(f"{schema}.{exact_table}")
        except Exception as exc:
            erros.append(f"{exact_table}: {exc}")

    if not fontes:
        return None

    rows, total_geral = _agent_aggregate_revenue_rows(raw_rows)
    return {
        "success": True,
        "ano": ano_int,
        "source": "base_local_fallback",
        "rows": rows,
        "total": total_geral,
        "query_context": {
            "table": ", ".join(fontes),
            "date_filter": f"ano {ano_int}",
            "observacao": "fato_vendas não foi encontrada; usei fallback da base local com tabelas/views operacionais.",
            "warnings": erros,
        },
    }


def _agent_score_value_column(column: str) -> int:
    c = column.lower()
    if any(bad in c for bad in ("qtd", "quant", "kg", "peso", "volume", "percent", "perc")):
        return -100
    score = 0
    if c in ("valor_pendente", "valorpending", "valorpendente"):
        score += 100
    if "valor" in c or c.startswith("vlr") or "vlr" in c:
        score += 50
    if "receita" in c or "fatur" in c or "total" in c:
        score += 40
    if "opportunity" in c or "oportun" in c:
        score += 20
    return score


def _agent_score_date_column(column: str) -> int:
    c = column.lower()
    score = 0
    if c in ("dt_entrega_cliente", "dtmov", "dtneg", "dt_prev_entrega_embarque"):
        score += 100
    if c.startswith("dt") or "data" in c or "date" in c:
        score += 50
    if c in ("ano", "year") or c.endswith("_ano"):
        score += 20
    return score


def _agent_discover_candidate_sources() -> list[dict]:
    rows = fetch_all(
        """
        SELECT
            t.TABLE_SCHEMA AS table_schema,
            t.TABLE_NAME AS table_name,
            t.TABLE_TYPE AS table_type,
            c.COLUMN_NAME AS column_name,
            c.DATA_TYPE AS data_type
        FROM INFORMATION_SCHEMA.TABLES t
        JOIN INFORMATION_SCHEMA.COLUMNS c
          ON c.TABLE_SCHEMA = t.TABLE_SCHEMA
         AND c.TABLE_NAME = t.TABLE_NAME
        WHERE t.TABLE_SCHEMA NOT IN ('sys', 'INFORMATION_SCHEMA')
        ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME, c.ORDINAL_POSITION
        """
    )
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (str(row.get("table_schema")), str(row.get("table_name")), str(row.get("table_type") or ""))
        grouped.setdefault(key, []).append(row)

    candidates: list[dict] = []
    for (schema, table, table_type), cols in grouped.items():
        col_names = [str(col.get("column_name")) for col in cols]
        value_cols = sorted([(col, _agent_score_value_column(col)) for col in col_names], key=lambda item: item[1], reverse=True)
        date_cols = sorted([(col, _agent_score_date_column(col)) for col in col_names], key=lambda item: item[1], reverse=True)
        value_cols = [item for item in value_cols if item[1] > 0]
        date_cols = [item for item in date_cols if item[1] > 0]
        if not value_cols or not date_cols:
            continue
        table_l = table.lower()
        table_score = 0
        if "fato" in table_l and "venda" in table_l:
            table_score += 100
        if "venda" in table_l or "receita" in table_l or "fatur" in table_l:
            table_score += 60
        if "b2b" in table_l:
            table_score += 50
        if "orc" in table_l or "forecast" in table_l:
            table_score += 40
        if "pedido" in table_l or "nota" in table_l or "mov" in table_l:
            table_score += 25
        if table_l.startswith("crm_"):
            table_score -= 50
        total_score = table_score + value_cols[0][1] + date_cols[0][1]
        category_col = next((col for col in col_names if col.lower() in ("tipo_receita", "tipo", "categoria", "projeto", "mercado_vendas", "status")), None)
        candidates.append({
            "schema": schema,
            "table": table,
            "table_type": table_type,
            "value_col": value_cols[0][0],
            "date_col": date_cols[0][0],
            "category_col": category_col,
            "score": total_score,
            "columns_sample": col_names[:20],
        })
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _agent_query_faturamento_discovery(ano_int: int) -> dict | None:
    candidates = _agent_discover_candidate_sources()
    erros: list[str] = []
    tried: list[str] = []
    for candidate in candidates[:12]:
        schema = candidate["schema"]
        table = candidate["table"]
        value_col = candidate["value_col"]
        date_col = candidate["date_col"]
        category_col = candidate.get("category_col")
        table_ref = f"{_agent_quote_identifier(schema)}.{_agent_quote_identifier(table)}"
        value_expr = f"TRY_CONVERT(float, {_agent_quote_identifier(value_col)})"
        date_expr = f"TRY_CONVERT(date, {_agent_quote_identifier(date_col)})"
        if str(date_col).lower() in ("ano", "year") or str(date_col).lower().endswith("_ano"):
            where_expr = f"TRY_CONVERT(int, {_agent_quote_identifier(date_col)}) = ?"
            params = [ano_int]
        else:
            where_expr = f"{date_expr} >= ? AND {date_expr} < ?"
            params = [f"{ano_int}-01-01", f"{ano_int + 1}-01-01"]

        if category_col:
            cat_expr = f"CAST({_agent_quote_identifier(category_col)} AS varchar(255))"
            category_sql = f"""CASE
                    WHEN UPPER(COALESCE({cat_expr}, '')) LIKE '%DEVOL%' THEN 'Vendas Firmes'
                    WHEN UPPER(COALESCE({cat_expr}, '')) LIKE '%FORECAST%' OR UPPER(COALESCE({cat_expr}, '')) LIKE '%ORC%' OR UPPER(COALESCE({cat_expr}, '')) LIKE '%PREV%' THEN 'Forecast'
                    WHEN UPPER(COALESCE({cat_expr}, '')) LIKE '%NOVO%' OR UPPER(COALESCE({cat_expr}, '')) LIKE '%PROJETO%' THEN 'Projetos'
                    ELSE 'Vendas Firmes'
                END"""
        else:
            table_l = str(table).lower()
            default_cat = "Forecast" if ("orc" in table_l or "forecast" in table_l) else "Vendas Firmes"
            category_sql = f"'{default_cat}'"

        query = f"""
            SELECT
                {category_sql} AS categoria,
                ? AS origem,
                SUM(COALESCE({value_expr}, 0)) AS total
            FROM {table_ref}
            WHERE {where_expr}
            GROUP BY {category_sql}
            HAVING SUM(COALESCE({value_expr}, 0)) <> 0
            ORDER BY total DESC
        """
        try:
            rows = _agent_fetch_rows(query, [f"{schema}.{table}", *params])
            tried.append(f"{schema}.{table}({value_col}/{date_col})")
            if rows:
                normalized_rows, total_geral = _agent_aggregate_revenue_rows(rows)
                return {
                    "success": True,
                    "ano": ano_int,
                    "source": "descoberta_automatica",
                    "rows": normalized_rows,
                    "total": total_geral,
                    "query_context": {
                        "table": f"{schema}.{table}",
                        "date_filter": f"ano {ano_int}",
                        "observacao": "Usei descoberta automática porque os nomes esperados de tabela não foram encontrados.",
                        "value_col": value_col,
                        "date_col": date_col,
                        "category_col": category_col,
                        "tried_sources": tried,
                    },
                }
        except Exception as exc:
            tried.append(f"{schema}.{table}({value_col}/{date_col})")
            erros.append(f"{schema}.{table}: {exc}")
    if candidates:
        return {
            "success": False,
            "error": "Encontrei possíveis tabelas de faturamento, mas nenhuma retornou valor para o ano informado",
            "candidate_sources": candidates[:15],
            "tried_sources": tried,
            "warnings": erros[:10],
            "rows": [],
            "total": 0.0,
        }
    return None


def get_faturamento_anual_por_categoria(ano: int) -> dict:
    """Consulta determinística para faturamento anual por categoria.

    Ordem de fontes:
    1. fato_vendas, tabela ou view.
    2. B2B + orcamento_2026/orcamento/orcamentos, tabela ou view.
    3. Descoberta automática por colunas prováveis de valor e data.
    """
    try:
        ano_int = int(ano)
    except Exception:
        return {"success": False, "error": "Ano inválido", "rows": [], "total": 0.0}

    if ano_int < 2000 or ano_int > 2100:
        return {"success": False, "error": "Ano fora do intervalo permitido", "rows": [], "total": 0.0}

    try:
        fato_result = _agent_query_faturamento_fato_vendas(ano_int)
        if fato_result and (not fato_result.get("success") or fato_result.get("rows")):
            return fato_result

        fallback_result = _agent_query_faturamento_base_local(ano_int)
        if fallback_result and fallback_result.get("rows"):
            return fallback_result

        discovery_result = _agent_query_faturamento_discovery(ano_int)
        if discovery_result:
            return discovery_result

        inventory = _agent_table_inventory(120)
        available = [
            f"{row.get('table_schema')}.{row.get('table_name')} ({row.get('table_type')}, {row.get('column_count')} cols)"
            for row in inventory
        ]
        return {
            "success": False,
            "error": "O banco conectado não expôs nenhuma tabela/view com colunas prováveis de valor e data para calcular faturamento",
            "available_tables_sample": available,
            "rows": [],
            "total": 0.0,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "rows": [], "total": 0.0}

def get_agent_database_schema() -> str:
    """Retorna um resumo textual seguro do schema usado pelo Agente IA.

    O agente antigo funcionava porque recebia contexto estrutural do banco antes de gerar
    consultas. Aqui fazemos o mesmo sobre SQL Server de produção, priorizando as tabelas
    analíticas `fato_vendas` e CRM `crm_*` sincronizadas do Bitrix24.
    """
    try:
        tables = fetch_all(
            """
            SELECT TABLE_SCHEMA AS table_schema, TABLE_NAME AS table_name
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')
              AND (
                    TABLE_NAME = 'fato_vendas'
                 OR TABLE_NAME LIKE 'crm[_]%'
                 OR TABLE_NAME LIKE 'dim[_]%'
                 OR TABLE_NAME IN ('users', 'metas', 'metas_2026', 'orcamento_2026')
              )
            ORDER BY
              CASE WHEN TABLE_NAME = 'fato_vendas' THEN 0
                   WHEN TABLE_NAME LIKE 'dim[_]%' THEN 1
                   WHEN TABLE_NAME = 'orcamento_2026' THEN 2
                   WHEN TABLE_NAME LIKE 'crm[_]%' THEN 3
                   ELSE 4 END,
              TABLE_SCHEMA,
              TABLE_NAME
            """
        )
    except Exception as exc:
        return f"Erro ao consultar INFORMATION_SCHEMA.TABLES: {exc}"

    if not tables:
        return (
            "Nenhuma tabela analítica esperada foi encontrada por INFORMATION_SCHEMA. "
            "Verifique se a API está conectada ao banco correto e se existem fato_vendas e/ou crm_*.")

    parts: list[str] = []
    for table in tables[:40]:
        schema = table.get("table_schema") or "dbo"
        name = table.get("table_name")
        try:
            columns = fetch_all(
                """
                SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
                ORDER BY ORDINAL_POSITION
                """,
                (schema, name),
            )
        except Exception as exc:
            parts.append(f"- {schema}.{name}: erro ao ler colunas: {exc}")
            continue

        col_text = ", ".join(
            f"{col.get('column_name')} {col.get('data_type')}"
            for col in columns[:80]
        )
        if len(columns) > 80:
            col_text += f", ... (+{len(columns) - 80} colunas)"
        parts.append(f"- {schema}.{name}: {col_text}")

    return "\n".join(parts)


def _validate_agent_sql(query: str) -> str:
    import re

    sql = (query or "").strip()
    sql = re.sub(r";\s*$", "", sql).strip()
    if not sql:
        raise ValueError("Consulta SQL vazia")
    if ";" in sql:
        raise ValueError("A ferramenta aceita apenas uma consulta por vez")

    normalized = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    normalized = re.sub(r"--.*?(\n|$)", " ", normalized)
    normalized_l = normalized.lower().strip()

    if not (normalized_l.startswith("select") or normalized_l.startswith("with")):
        raise ValueError("Somente consultas SELECT ou WITH são permitidas")

    forbidden = re.compile(
        r"\b(insert|update|delete|drop|alter|truncate|merge|exec|execute|create|grant|revoke|backup|restore|xp_|sp_|openrowset|opendatasource)\b",
        re.I,
    )
    if forbidden.search(normalized):
        raise ValueError("A consulta contém comando não permitido")

    return sql


def execute_agent_sql(query: str, max_rows: int = 200) -> dict:
    """Executa SELECT/WITH seguro no SQL Server para o Agente IA."""
    try:
        sql = _validate_agent_sql(query)
    except Exception as exc:
        return {"success": False, "error": str(exc), "rows": [], "row_count": 0}

    safe_max_rows = max(1, min(int(max_rows or 200), 500))
    try:
        with get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute(sql)
            if cursor.description is None:
                return {
                    "success": False,
                    "error": "A consulta não retornou um recordset. Use apenas SELECT/WITH.",
                    "rows": [],
                    "row_count": 0,
                }
            columns = [column[0] for column in cursor.description]
            fetched = cursor.fetchmany(safe_max_rows + 1)
    except Exception as exc:
        return {"success": False, "error": str(exc), "query": sql, "rows": [], "row_count": 0}

    limited = len(fetched) > safe_max_rows
    rows = [
        {columns[i]: _chat_value_to_json(value) for i, value in enumerate(row)}
        for row in fetched[:safe_max_rows]
    ]
    return {
        "success": True,
        "query": sql,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "limited": limited,
        "limit": safe_max_rows,
    }


# =============================================================================
# Placar Funil Comercial — CRM (crm_deals / crm_deal_stage_history / crm_activities)
# =============================================================================
# Fonte da verdade das regras/números: SPEC_BACKEND.md (validado contra Bitrix24 e produção).

FUNIL_SCORECARD_VENDEDORES = [
    {"id": 151, "nome": "Julia Alberti"},
    {"id": 289, "nome": "Talia Stefani Scain"},
    {"id": 365, "nome": "Jennifer Anacleto"},
    {"id": 397, "nome": "Tatiana Evangelista"},
]
FUNIL_SCORECARD_USER_IDS = (151, 289, 365, 397)

# SLA por fase (dias), Perfil A = opportunity < 150 mil, Perfil B = >= 150 mil
FUNIL_SCORECARD_SLA = {
    "Qualificacao": {"A": 10, "B": 15},
    "Proposta e Amostra": {"A": 20, "B": 20},
    "Avaliacao no Cliente": {"A": 60, "B": 90},
    "Homologacao e Teste Industrial": {"A": 60, "B": 120},
    "Fechamento": {"A": 10, "B": 15},
}

_SC_MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
_SC_MESES_NOME = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _sc_sort_case_sql(col: str) -> str:
    """Posição de cada etapa no funil (só pra saber se um negócio "avançou")."""
    return (
        f"CASE {col} "
        "WHEN 'UC_IJG2LW' THEN 10 "
        "WHEN 'NEW' THEN 20 "
        "WHEN 'UC_RWSOLQ' THEN 45 "
        "WHEN 'UC_XFS4CF' THEN 50 "
        "WHEN 'UC_1VRZTH' THEN 60 "
        "WHEN '7' THEN 70 "
        "WHEN 'UC_M8BBII' THEN 85 "
        "WHEN '1' THEN 90 "
        "WHEN 'WON' THEN 100 "
        "WHEN 'LOSE' THEN 110 "
        "WHEN '3' THEN 120 "
        "WHEN '8' THEN 130 "
        "ELSE NULL END"
    )


def _sc_fase_case_sql(col: str) -> str:
    """Agrupa os stage_id do Bitrix nos 5 buckets de fase usados pro SLA."""
    return (
        f"CASE {col} "
        "WHEN 'UC_IJG2LW' THEN 'Qualificacao' "
        "WHEN 'NEW' THEN 'Proposta e Amostra' "
        "WHEN 'UC_XFS4CF' THEN 'Avaliacao no Cliente' "
        "WHEN 'UC_RWSOLQ' THEN 'Avaliacao no Cliente' "
        "WHEN 'UC_1VRZTH' THEN 'Homologacao e Teste Industrial' "
        "WHEN '7' THEN 'Homologacao e Teste Industrial' "
        "WHEN '1' THEN 'Fechamento' "
        "WHEN 'UC_M8BBII' THEN 'Fechamento' "
        "ELSE 'SEM_MAPEAMENTO' END"
    )


def _sc_fuso_sql(col: str) -> str:
    """Converte um nvarchar ISO com offset do Bitrix (+03:00) pra data no fuso do Brasil (-03:00).

    TRY_CONVERT em vez de CONVERT: uma string malformada isolada vira NULL (exclui a linha das
    comparações) em vez de derrubar a query inteira.
    """
    return f"CAST(SWITCHOFFSET(TRY_CONVERT(datetimeoffset(0), {col}), '-03:00') AS date)"


def _sc_agora_brasil() -> date:
    return (datetime.now(timezone.utc) - timedelta(hours=3)).date()


def _sc_add_months(d: date, months: int) -> date:
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


def _sc_label_semana(start, end) -> str:
    fim_incl = end - timedelta(days=1)
    return f"{start.strftime('%d/%m')} a {fim_incl.strftime('%d/%m')}"


def _sc_label_mes(start) -> str:
    return f"{_SC_MESES_NOME[start.month - 1]}/{start.year}"


def get_funil_scorecard_periodos(hoje: date | None = None) -> dict:
    hoje = hoje or _sc_agora_brasil()
    segunda = hoje - timedelta(days=hoje.weekday())  # date.weekday(): 0=segunda, já ISO

    sa_start, sa_end = segunda, segunda + timedelta(days=7)
    sant_start, sant_end = segunda - timedelta(days=7), segunda
    sret_start, sret_end = segunda - timedelta(days=14), segunda - timedelta(days=7)

    mes_ini = date(hoje.year, hoje.month, 1)
    ma_start, ma_end = mes_ini, _sc_add_months(mes_ini, 1)
    mant_start, mant_end = _sc_add_months(mes_ini, -1), mes_ini

    quarter_start_month = ((hoje.month - 1) // 3) * 3 + 1
    tri_inicio = date(hoje.year, quarter_start_month, 1)
    tri_fim = _sc_add_months(tri_inicio, 3)
    tri_meses = [f"{hoje.year}-{(quarter_start_month + i):02d}" for i in range(3)]
    quarter_num = (quarter_start_month - 1) // 3 + 1
    tri_label = (
        f"T{quarter_num}/{hoje.year} "
        f"({_SC_MESES_ABREV[quarter_start_month - 1]}-{_SC_MESES_ABREV[quarter_start_month + 1]})"
    )

    return {
        "semana_atual": {"start": sa_start.isoformat(), "end": sa_end.isoformat(), "label": _sc_label_semana(sa_start, sa_end)},
        "semana_anterior": {"start": sant_start.isoformat(), "end": sant_end.isoformat(), "label": _sc_label_semana(sant_start, sant_end)},
        "semana_retrasada": {"start": sret_start.isoformat(), "end": sret_end.isoformat(), "label": _sc_label_semana(sret_start, sret_end)},
        "mes_atual": {"start": ma_start.isoformat(), "end": ma_end.isoformat(), "label": _sc_label_mes(ma_start)},
        "mes_anterior": {"start": mant_start.isoformat(), "end": mant_end.isoformat(), "label": _sc_label_mes(mant_start)},
        "ano": hoje.year,
        "trimestre": {"label": tri_label, "meses": tri_meses, "inicio": tri_inicio.isoformat(), "fim": tri_fim.isoformat()},
    }


_SC_COD_TOP_FILTER = "(cod_top IS NULL OR cod_top <> 1023) AND ([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')"


def get_funil_scorecard_resultado(ano: int, meses_trimestre: list[str], inicio_tri: str, fim_tri: str) -> dict:
    meta_ano_rows = fetch_all("SELECT COALESCE(SUM(valor_meta), 0) AS v FROM dbo.metas_2026")
    meta_ano = _number(meta_ano_rows[0]["v"]) if meta_ano_rows else 0.0

    placeholders = ",".join("?" for _ in meses_trimestre)
    meta_tri_rows = fetch_all(
        f"SELECT COALESCE(SUM(valor_meta), 0) AS v FROM dbo.metas_2026 WHERE mes IN ({placeholders})",
        tuple(meses_trimestre),
    )
    meta_tri = _number(meta_tri_rows[0]["v"]) if meta_tri_rows else 0.0

    real_ano_rows = fetch_all(
        f"""
        SELECT COALESCE(SUM(valor_pendente), 0) AS v
        FROM dbo.fato_vendas
        WHERE YEAR(dt_entrega_cliente) = ?
          AND tipo_receita IN ('VENDA_FIRME', 'FORECAST', 'DEVOLUCAO')
          AND {_SC_COD_TOP_FILTER}
        """,
        (ano,),
    )
    realizado_ano = _number(real_ano_rows[0]["v"]) if real_ano_rows else 0.0

    real_tri_rows = fetch_all(
        f"""
        SELECT COALESCE(SUM(valor_pendente), 0) AS v
        FROM dbo.fato_vendas
        WHERE dt_entrega_cliente >= ? AND dt_entrega_cliente < ?
          AND tipo_receita IN ('VENDA_FIRME', 'FORECAST', 'DEVOLUCAO')
          AND {_SC_COD_TOP_FILTER}
        """,
        (inicio_tri, fim_tri),
    )
    realizado_tri = _number(real_tri_rows[0]["v"]) if real_tri_rows else 0.0

    return {
        "metaAno": meta_ano, "realizadoAno": realizado_ano,
        "metaTri": meta_tri, "realizadoTri": realizado_tri,
    }


def get_funil_scorecard_cadencia_range(start: str, end: str) -> list[dict]:
    ids_placeholders = ",".join("?" for _ in FUNIL_SCORECARD_USER_IDS)
    fuso_create = _sc_fuso_sql("d.date_create")
    fuso_close = _sc_fuso_sql("d.closedate")

    contagens = fetch_all(
        f"""
        SELECT d.assigned_by_id AS userId,
          SUM(CASE WHEN {fuso_create} >= ? AND {fuso_create} < ? THEN 1 ELSE 0 END) AS abertos,
          SUM(CASE WHEN d.stage_semantic_id = 'S' AND {fuso_close} >= ? AND {fuso_close} < ? THEN 1 ELSE 0 END) AS ganhos,
          SUM(CASE WHEN d.stage_id IN ('LOSE','3','8') AND {fuso_close} >= ? AND {fuso_close} < ? THEN 1 ELSE 0 END) AS perdidos
        FROM dbo.crm_deals d
        WHERE d.assigned_by_id IN ({ids_placeholders})
          AND (d.category_id = '0' OR d.category_id IS NULL)
        GROUP BY d.assigned_by_id
        """,
        (start, end, start, end, start, end) + FUNIL_SCORECARD_USER_IDS,
    )

    sort_case = _sc_sort_case_sql("h.stage_id")
    fuso_hist = _sc_fuso_sql("created_time")
    avancados = fetch_all(
        f"""
        WITH hist AS (
            SELECT h.deal_id, d.assigned_by_id, h.created_time,
                   {sort_case} AS sort_atual,
                   LAG({sort_case}) OVER (PARTITION BY h.deal_id ORDER BY h.created_time) AS sort_anterior
            FROM dbo.crm_deal_stage_history h
            JOIN dbo.crm_deals d ON d.id = h.deal_id
            WHERE d.assigned_by_id IN ({ids_placeholders})
              AND (d.category_id = '0' OR d.category_id IS NULL)
        )
        SELECT assigned_by_id AS userId, COUNT(DISTINCT deal_id) AS avancaram
        FROM hist
        WHERE {fuso_hist} >= ? AND {fuso_hist} < ?
          AND sort_anterior IS NOT NULL AND sort_atual > sort_anterior
        GROUP BY assigned_by_id
        """,
        FUNIL_SCORECARD_USER_IDS + (start, end),
    )

    por_vendedor: dict[int, dict] = {
        uid: {"userId": uid, "abertos": 0, "ganhos": 0, "perdidos": 0, "avancaram": 0}
        for uid in FUNIL_SCORECARD_USER_IDS
    }
    for row in contagens:
        uid = _int(row.get("userId"))
        if uid in por_vendedor:
            por_vendedor[uid]["abertos"] = _int(row.get("abertos"))
            por_vendedor[uid]["ganhos"] = _int(row.get("ganhos"))
            por_vendedor[uid]["perdidos"] = _int(row.get("perdidos"))
    for row in avancados:
        uid = _int(row.get("userId"))
        if uid in por_vendedor:
            por_vendedor[uid]["avancaram"] = _int(row.get("avancaram"))

    for v in por_vendedor.values():
        v["saldo"] = v["abertos"] - (v["ganhos"] + v["perdidos"])

    return list(por_vendedor.values())


def get_funil_scorecard_saude_raw() -> list[dict]:
    fase_case = _sc_fase_case_sql("d.stage_id")
    entrada_fuso = _sc_fuso_sql("COALESCE(ef.entrada, d.date_create)")
    deadline_fuso = _sc_fuso_sql("deadline")

    hoje_iso = _sc_agora_brasil().isoformat()

    rows = fetch_all(
        f"""
        WITH entrada_fase AS (
            SELECT h.deal_id, MAX(h.created_time) AS entrada
            FROM dbo.crm_deal_stage_history h
            JOIN dbo.crm_deals d ON d.id = h.deal_id AND d.stage_id = h.stage_id
            GROUP BY h.deal_id
        ), followup AS (
            SELECT DISTINCT owner_id
            FROM dbo.crm_activities
            WHERE owner_type_id = 2
              AND deadline NOT LIKE '9999%'
              AND (provider_id = 'CRM_TODO' OR (provider_id = 'CRM_TASKS_TASK' AND completed = 0))
              AND {deadline_fuso} >= ?
        )
        SELECT d.id AS id, d.title AS title, d.assigned_by_id AS assignedById,
               {fase_case} AS fase, d.opportunity AS opportunity,
               {entrada_fuso} AS entradaFase,
               CASE WHEN f.owner_id IS NULL THEN 0 ELSE 1 END AS temFollowup
        FROM dbo.crm_deals d
        LEFT JOIN entrada_fase ef ON ef.deal_id = d.id
        LEFT JOIN followup f ON f.owner_id = d.id
        WHERE (d.category_id = '0' OR d.category_id IS NULL)
          AND d.stage_semantic_id = 'P'
          AND d.stage_id NOT IN ('8', 'UC_PNH69S')
        """,
        (hoje_iso,),
    )
    return [
        {
            "id": _int(row.get("id")),
            "title": row.get("title") or "",
            "assignedById": _int(row.get("assignedById")),
            "fase": row.get("fase") or "SEM_MAPEAMENTO",
            "opportunity": _number(row.get("opportunity")),
            "entradaFase": row.get("entradaFase"),
            "temFollowup": bool(row.get("temFollowup")),
        }
        for row in rows
    ]


def get_funil_scorecard_estagnado() -> int:
    rows = fetch_all(
        """
        SELECT COUNT(*) AS v FROM dbo.crm_deals
        WHERE (category_id = '0' OR category_id IS NULL) AND stage_id = 'UC_PNH69S'
        """
    )
    return _int(rows[0]["v"]) if rows else 0


# ─── Semáforos e veredito (lógica pura, sem I/O) ───────────────────────────────

def _sc_cor_abertos(n: int, escopo: str) -> str:
    if escopo == "semana":
        if n >= 5:
            return "verde"
        return "amarelo" if n >= 3 else "vermelho"
    if n >= 22:
        return "verde"
    return "amarelo" if n >= 15 else "vermelho"


def _sc_cor_ganhos(atual: int, ref_retrasada: int, escopo: str) -> str:
    if escopo == "semana":
        if atual >= 1:
            return "verde"
        return "amarelo" if ref_retrasada >= 1 else "vermelho"
    if atual >= 5:
        return "verde"
    return "amarelo" if atual >= 3 else "vermelho"


def _sc_cor_saldo(n: int, escopo: str) -> str:
    if escopo == "semana":
        if n > 0:
            return "verde"
        return "amarelo" if n == 0 else "vermelho"
    if n >= 5:
        return "verde"
    return "amarelo" if n >= 1 else "vermelho"


def _sc_cor_taxa_perda(pct: float, escopo: str) -> str:
    if escopo == "semana":
        if pct < 3:
            return "verde"
        return "amarelo" if pct <= 6 else "vermelho"
    if pct < 5:
        return "verde"
    return "amarelo" if pct <= 12 else "vermelho"


def _sc_cor_pct_saude(pct: float | None, tipo: str) -> str | None:
    if pct is None:
        return None
    if tipo == "sla":
        if pct < 30:
            return "verde"
        return "amarelo" if pct <= 50 else "vermelho"
    if pct < 30:
        return "verde"
    return "amarelo" if pct <= 60 else "vermelho"


def _sc_cor_pct_atingido(pct: float) -> str:
    if pct >= 100:
        return "verde"
    return "amarelo" if pct >= 85 else "vermelho"


def _sc_gerar_veredito(luzes: dict, saude_agregada: dict, numeros: dict) -> str:
    abertos_cor = luzes["abertos"]
    ganhos_cor = luzes["ganhos"]
    saldo_cor = luzes["saldo"]
    taxa_perda_cor = luzes["perdidos"]
    pct_sla_cor = saude_agregada.get("corSla")
    pct_fu_cor = saude_agregada.get("corFu")

    cadencia_toda_verde = abertos_cor == "verde" and ganhos_cor == "verde" and saldo_cor == "verde"
    cadencia_toda_vermelha = abertos_cor == "vermelho" and ganhos_cor == "vermelho" and saldo_cor == "vermelho"
    saude_tem_vermelho = pct_sla_cor == "vermelho" or pct_fu_cor == "vermelho"
    saude_toda_verde = pct_sla_cor == "verde" and pct_fu_cor == "verde"

    abertos = numeros["abertos"]
    ganhos = numeros["ganhos"]
    perdidos = numeros["perdidos"]
    saldo = numeros["saldo"]
    taxa_perda = numeros["taxaPerda"]
    pct_sla = saude_agregada["pctSlaAgregado"]
    pct_fu = saude_agregada["pctFuAgregado"]

    if cadencia_toda_verde and saude_tem_vermelho:
        return (
            f"Motor de entrada girando bem ({abertos} abertos, {ganhos} ganhos, saldo {saldo:+d}) "
            f"— mas o problema não é o topo do funil, é o meio: {pct_sla:.0f}% fora do SLA e "
            f"{pct_fu:.0f}% sem follow-up agendado."
        )

    if saldo_cor == "vermelho" and taxa_perda_cor in ("amarelo", "vermelho"):
        texto = (
            f"A máquina gira devagar e vaza: {perdidos} perdidos (taxa de {taxa_perda:.1f}% do funil ativo) "
            f"contra {ganhos} ganhos (saldo {saldo:+d}) — o problema principal é a saída, não a entrada ({abertos} abertos)."
        )
        if pct_fu_cor != "verde":
            texto += f" O funil ativo também carrega {pct_fu:.0f}% sem follow-up, o que agrava o risco."
        return texto

    if abertos_cor == "vermelho":
        return f"Geração de negócios fraca ({abertos} abertos) — saldo {saldo:+d}. Se não reagir, o funil começa a secar."

    if ganhos_cor == "vermelho":
        return f"Conversão fraca: só {ganhos} ganho(s) — poucos negócios fechando apesar do funil girar."

    if cadencia_toda_verde and saude_toda_verde:
        return "Tudo girando bem: cadência no alvo e funil saudável. Manter o ritmo."

    if cadencia_toda_vermelha and saude_tem_vermelho:
        return "Situação crítica: entrada fraca e funil travado ao mesmo tempo — atenção total."

    return "Sinais mistos: sem crise clara, mas vale atenção pontual nos itens amarelos/vermelhos."


# ─── Orquestrador ───────────────────────────────────────────────────────────────

def get_funil_scorecard(recorte_selecionado: str) -> dict:
    hoje = _sc_agora_brasil()
    periodos = get_funil_scorecard_periodos(hoje)

    resultado_raw = get_funil_scorecard_resultado(
        periodos["ano"], periodos["trimestre"]["meses"],
        periodos["trimestre"]["inicio"], periodos["trimestre"]["fim"],
    )
    pct_ano = (resultado_raw["realizadoAno"] / resultado_raw["metaAno"] * 100) if resultado_raw["metaAno"] else 0.0
    pct_tri = (resultado_raw["realizadoTri"] / resultado_raw["metaTri"] * 100) if resultado_raw["metaTri"] else 0.0
    resultado = {
        "ano": periodos["ano"],
        "metaAno": resultado_raw["metaAno"], "realizadoAno": resultado_raw["realizadoAno"], "pctAno": pct_ano,
        "trimestreLabel": periodos["trimestre"]["label"],
        "metaTri": resultado_raw["metaTri"], "realizadoTri": resultado_raw["realizadoTri"], "pctTri": pct_tri,
    }

    recortes_cadencia = ("semana_atual", "semana_anterior", "semana_retrasada", "mes_atual", "mes_anterior")
    cadencia_raw = {
        r: get_funil_scorecard_cadencia_range(periodos[r]["start"], periodos[r]["end"])
        for r in recortes_cadencia
    }

    nomes_por_id = {v["id"]: v["nome"] for v in FUNIL_SCORECARD_VENDEDORES}

    cadencia: dict[str, dict] = {}
    for r in recortes_cadencia:
        vendedores_linha = []
        totais = {"abertos": 0, "ganhos": 0, "perdidos": 0, "avancaram": 0, "saldo": 0}
        for row in cadencia_raw[r]:
            linha = {
                "nome": nomes_por_id.get(row["userId"], "?"),
                "abertos": row["abertos"], "ganhos": row["ganhos"],
                "perdidos": row["perdidos"], "avancaram": row["avancaram"], "saldo": row["saldo"],
            }
            vendedores_linha.append(linha)
            for k in totais:
                totais[k] += linha[k]
        vendedores_linha.sort(key=lambda v: v["nome"])
        cadencia[r] = {"label": periodos[r]["label"], "vendedores": vendedores_linha, "totais": totais}

    saude_raw = get_funil_scorecard_saude_raw()
    estagnado = get_funil_scorecard_estagnado()

    def _dias_na_fase(entrada_fase) -> int:
        if entrada_fase is None:
            return 0
        if isinstance(entrada_fase, datetime):
            entrada_fase = entrada_fase.date()
        elif isinstance(entrada_fase, str):
            entrada_fase = datetime.fromisoformat(entrada_fase).date()
        return max((hoje - entrada_fase).days, 0)

    enriquecidos = []
    for d in saude_raw:
        dias = _dias_na_fase(d["entradaFase"])
        perfil = "B" if d["opportunity"] >= 150000 else "A"
        sla_fase = FUNIL_SCORECARD_SLA.get(d["fase"])
        sla = sla_fase[perfil] if sla_fase else None
        fora_do_sla = sla is not None and dias > sla
        enriquecidos.append({**d, "diasNaFase": dias, "perfil": perfil, "sla": sla, "foraDoSla": fora_do_sla})

    def _pct(parte: int, total: int) -> float | None:
        return (parte / total * 100) if total else None

    grupos = {v["id"]: {"nome": v["nome"], "ativos": 0, "foraSla": 0, "semFollowup": 0} for v in FUNIL_SCORECARD_VENDEDORES}
    outros = {"nome": "Outros (fora do placar)", "ativos": 0, "foraSla": 0, "semFollowup": 0}
    for d in enriquecidos:
        alvo = grupos.get(d["assignedById"], outros)
        alvo["ativos"] += 1
        if d["foraDoSla"]:
            alvo["foraSla"] += 1
        if not d["temFollowup"]:
            alvo["semFollowup"] += 1

    saude_lista = []
    total_ativos = total_fora_sla = total_sem_fu = 0
    for v in FUNIL_SCORECARD_VENDEDORES:
        g = grupos[v["id"]]
        saude_lista.append({
            "nome": g["nome"], "ativos": g["ativos"], "foraSla": g["foraSla"], "semFollowup": g["semFollowup"],
            "pctSla": _pct(g["foraSla"], g["ativos"]), "pctFu": _pct(g["semFollowup"], g["ativos"]),
        })
        total_ativos += g["ativos"]; total_fora_sla += g["foraSla"]; total_sem_fu += g["semFollowup"]

    # "Outros (fora do placar)" -- soma pro total bater
    saude_lista.append({
        "nome": outros["nome"], "ativos": outros["ativos"], "foraSla": outros["foraSla"],
        "semFollowup": outros["semFollowup"],
        "pctSla": _pct(outros["foraSla"], outros["ativos"]), "pctFu": _pct(outros["semFollowup"], outros["ativos"]),
    })
    total_ativos += outros["ativos"]; total_fora_sla += outros["foraSla"]; total_sem_fu += outros["semFollowup"]

    pct_sla_agregado = _pct(total_fora_sla, total_ativos) or 0.0
    pct_fu_agregado = _pct(total_sem_fu, total_ativos) or 0.0

    acao_candidatos = [
        d for d in enriquecidos
        if d["assignedById"] in nomes_por_id and d["foraDoSla"] and not d["temFollowup"]
    ]
    acao_candidatos.sort(key=lambda d: d["diasNaFase"], reverse=True)
    acao_total = len(acao_candidatos)
    acao = [
        {
            "titulo": d["title"], "vendedor": nomes_por_id.get(d["assignedById"], "?"),
            "fase": d["fase"], "dias": d["diasNaFase"], "sla": d["sla"],
        }
        for d in acao_candidatos[:20]
    ]

    if recorte_selecionado == "semana_atual":
        luzes = None
        t = cadencia["semana_atual"]["totais"]
        veredito = (
            f"Acompanhamento da semana em andamento (sem veredito de cobrança): "
            f"{t['abertos']} abertos, {t['ganhos']} ganhos, {t['perdidos']} perdidos, saldo {t['saldo']:+d} até agora."
        )
    else:
        escopo = "semana" if recorte_selecionado == "semana_anterior" else "mes"
        t = cadencia[recorte_selecionado]["totais"]
        ref_retrasada_ganhos = (
            cadencia["semana_retrasada"]["totais"]["ganhos"] if recorte_selecionado == "semana_anterior" else 0
        )
        taxa_perda = _pct(t["perdidos"], total_ativos) or 0.0

        cor_ganhos = _sc_cor_ganhos(t["ganhos"], ref_retrasada_ganhos, escopo)
        if t["saldo"] < 0 and cor_ganhos == "verde":
            cor_ganhos = "amarelo"

        luzes = {
            "abertos": _sc_cor_abertos(t["abertos"], escopo),
            "ganhos": cor_ganhos,
            "saldo": _sc_cor_saldo(t["saldo"], escopo),
            "perdidos": _sc_cor_taxa_perda(taxa_perda, escopo),
            "taxaPerda": taxa_perda,
        }

        veredito = _sc_gerar_veredito(
            luzes,
            {
                "pctSlaAgregado": pct_sla_agregado, "pctFuAgregado": pct_fu_agregado,
                "corSla": _sc_cor_pct_saude(pct_sla_agregado, "sla"),
                "corFu": _sc_cor_pct_saude(pct_fu_agregado, "followup"),
            },
            {"abertos": t["abertos"], "ganhos": t["ganhos"], "perdidos": t["perdidos"], "saldo": t["saldo"], "taxaPerda": taxa_perda},
        )

    saude = {
        "porVendedor": saude_lista,
        "totalAtivos": total_ativos, "totalForaSla": total_fora_sla, "totalSemFollowup": total_sem_fu,
        "pctSlaAgregado": pct_sla_agregado, "pctFuAgregado": pct_fu_agregado,
        "estagnado": estagnado,
    }

    return {
        "resultado": resultado,
        "cadencia": cadencia,
        "luzes": luzes,
        "veredito": veredito,
        "saude": saude,
        "acao": acao,
        "acaoTotal": acao_total,
    }


# =============================================================================
# Movimentação de Clientes e Produtos — Abertos/Perdidos (clientes) e
# Lançados/Descontinuados (produtos), comparando o ano selecionado com o
# ano imediatamente anterior. Somente leitura sobre dbo.fato_vendas — não
# reaproveita nem altera nenhuma regra das telas existentes.
# =============================================================================

def _mov_number(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def _mov_int(value: Any) -> int:
    return int(value or 0)


def _mov_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def get_movimentacao_clientes(ano: int) -> dict:
    """Clientes Abertos (venda só no ano selecionado) e Perdidos (venda só no ano anterior).

    Uma única consulta agregada por cliente x ano (GROUP BY cod_parc, ano) cobre as duas
    visões: a classificação Abertos/Perdidos é feita em Python, comparando os dois conjuntos
    já agregados — evita rodar a consulta pesada duas vezes e nunca traz venda por venda.
    """
    ano_anterior = ano - 1
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            fv.cod_parc AS cod_parc,
            COALESCE(dc.razao_social, fv.RAZAOSOCIAL) AS razao_social,
            YEAR(fv.dt_entrega_cliente) AS ano,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COUNT(DISTINCT fv.nro_unico) AS pedidos,
            MIN(fv.dt_entrega_cliente) AS primeira_compra,
            MAX(fv.dt_entrega_cliente) AS ultima_compra
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
        WHERE YEAR(fv.dt_entrega_cliente) IN (?, ?)
          AND (fv.cod_top IS NULL OR fv.cod_top != 1023)
          AND (fv.[top] IS NULL OR fv.[top] NOT LIKE '%ESTOQUE MINIM%')
        GROUP BY fv.cod_parc, dc.razao_social, fv.RAZAOSOCIAL, YEAR(fv.dt_entrega_cliente)
        """,
        ano, ano_anterior,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    atual: dict[int, Any] = {}
    anterior: dict[int, Any] = {}
    for row in rows:
        cod_parc = _mov_int(row.cod_parc)
        (atual if _mov_int(row.ano) == ano else anterior)[cod_parc] = row

    abertos = [
        {
            "codParc": cod_parc,
            "razaoSocial": row.razao_social or f"Cliente {cod_parc}",
            "faturamento": _mov_number(row.faturamento),
            "pedidos": _mov_int(row.pedidos),
            "primeiraCompra": _mov_date(row.primeira_compra),
            "ultimaCompra": _mov_date(row.ultima_compra),
        }
        for cod_parc, row in atual.items()
        if cod_parc not in anterior
    ]
    abertos.sort(key=lambda r: r["faturamento"], reverse=True)

    data_referencia = date(ano_anterior, 12, 31)
    perdidos = []
    for cod_parc, row in anterior.items():
        if cod_parc in atual:
            continue
        ultima_compra = _mov_date(row.ultima_compra)
        dias_sem_comprar = None
        if ultima_compra:
            dias_sem_comprar = (data_referencia - datetime.strptime(ultima_compra, "%Y-%m-%d").date()).days
        perdidos.append({
            "codParc": cod_parc,
            "razaoSocial": row.razao_social or f"Cliente {cod_parc}",
            "faturamento": _mov_number(row.faturamento),
            "pedidos": _mov_int(row.pedidos),
            "ultimaCompra": ultima_compra,
            "diasSemComprar": dias_sem_comprar,
        })
    perdidos.sort(key=lambda r: r["faturamento"], reverse=True)

    return {
        "ano": ano,
        "anoAnterior": ano_anterior,
        "abertos": abertos,
        "perdidos": perdidos,
    }


def get_movimentacao_produtos(ano: int) -> dict:
    """Produtos Lançados (venda só no ano selecionado) e Descontinuados (venda só no ano
    anterior). Mesma estratégia de get_movimentacao_clientes: uma consulta agregada por
    produto x ano cobre as duas visões."""
    ano_anterior = ano - 1
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            fv.cod_produto AS cod_produto,
            COALESCE(dp.nome_produto, fv.nome_produto) AS nome_produto,
            fv.grupo_produto AS grupo_produto,
            YEAR(fv.dt_entrega_cliente) AS ano,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume,
            COUNT(DISTINCT fv.cod_parc) AS clientes,
            MIN(fv.dt_entrega_cliente) AS primeira_venda,
            MAX(fv.dt_entrega_cliente) AS ultima_venda
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
        WHERE YEAR(fv.dt_entrega_cliente) IN (?, ?)
          AND (fv.cod_top IS NULL OR fv.cod_top != 1023)
          AND (fv.[top] IS NULL OR fv.[top] NOT LIKE '%ESTOQUE MINIM%')
        GROUP BY fv.cod_produto, dp.nome_produto, fv.nome_produto, fv.grupo_produto, YEAR(fv.dt_entrega_cliente)
        """,
        ano, ano_anterior,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    atual: dict[int, Any] = {}
    anterior: dict[int, Any] = {}
    for row in rows:
        cod_produto = _mov_int(row.cod_produto)
        (atual if _mov_int(row.ano) == ano else anterior)[cod_produto] = row

    def _serialize(cod_produto: int, row: Any) -> dict:
        return {
            "codProduto": cod_produto,
            "nomeProduto": row.nome_produto or f"Produto {cod_produto}",
            "grupoProduto": row.grupo_produto,
            "faturamento": _mov_number(row.faturamento),
            "volume": _mov_number(row.volume),
            "clientes": _mov_int(row.clientes),
            "primeiraVenda": _mov_date(row.primeira_venda),
            "ultimaVenda": _mov_date(row.ultima_venda),
        }

    lancados = [_serialize(cod, row) for cod, row in atual.items() if cod not in anterior]
    lancados.sort(key=lambda r: r["faturamento"], reverse=True)

    descontinuados = [_serialize(cod, row) for cod, row in anterior.items() if cod not in atual]
    descontinuados.sort(key=lambda r: r["faturamento"], reverse=True)

    return {
        "ano": ano,
        "anoAnterior": ano_anterior,
        "lancados": lancados,
        "descontinuados": descontinuados,
    }


def get_movimentacao_cliente_produtos(cod_parc: int, ano: int) -> list[dict]:
    """Produtos comprados por um cliente específico, dentro de um único ano — usado ao
    expandir uma linha em Clientes Abertos (ano selecionado) ou Perdidos (ano anterior)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            fv.cod_produto AS cod_produto,
            COALESCE(dp.nome_produto, fv.nome_produto) AS nome_produto,
            fv.grupo_produto AS grupo_produto,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_produto dp ON fv.cod_produto = dp.cod_produto
        WHERE fv.cod_parc = ?
          AND YEAR(fv.dt_entrega_cliente) = ?
          AND (fv.cod_top IS NULL OR fv.cod_top != 1023)
          AND (fv.[top] IS NULL OR fv.[top] NOT LIKE '%ESTOQUE MINIM%')
        GROUP BY fv.cod_produto, dp.nome_produto, fv.nome_produto, fv.grupo_produto
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        cod_parc, ano,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "codProduto": _mov_int(row.cod_produto),
            "nomeProduto": row.nome_produto or f"Produto {_mov_int(row.cod_produto)}",
            "grupoProduto": row.grupo_produto,
            "faturamento": _mov_number(row.faturamento),
            "volume": _mov_number(row.volume),
        }
        for row in rows
    ]


def get_movimentacao_produto_clientes(cod_produto: int, ano: int) -> list[dict]:
    """Clientes que compraram um produto específico, dentro de um único ano — usado ao
    expandir uma linha em Produtos Lançados (ano selecionado) ou Descontinuados (ano anterior)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            fv.cod_parc AS cod_parc,
            COALESCE(dc.razao_social, fv.RAZAOSOCIAL) AS razao_social,
            COALESCE(SUM(fv.valor_pendente), 0) AS faturamento,
            COALESCE(SUM(fv.qtd_pendente_kg), 0) AS volume
        FROM dbo.fato_vendas fv
        LEFT JOIN dbo.dim_cliente dc ON fv.cod_parc = dc.cod_parc
        WHERE fv.cod_produto = ?
          AND YEAR(fv.dt_entrega_cliente) = ?
          AND (fv.cod_top IS NULL OR fv.cod_top != 1023)
          AND (fv.[top] IS NULL OR fv.[top] NOT LIKE '%ESTOQUE MINIM%')
        GROUP BY fv.cod_parc, dc.razao_social, fv.RAZAOSOCIAL
        ORDER BY SUM(fv.valor_pendente) DESC
        """,
        cod_produto, ano,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            "codParc": _mov_int(row.cod_parc),
            "razaoSocial": row.razao_social or f"Cliente {_mov_int(row.cod_parc)}",
            "faturamento": _mov_number(row.faturamento),
            "volume": _mov_number(row.volume),
        }
        for row in rows
    ]