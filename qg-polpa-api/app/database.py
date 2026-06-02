import os

import pyodbc
from dotenv import load_dotenv

from decimal import Decimal
from datetime import datetime

load_dotenv( )


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




def _serialize_datetime(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialize_decimal(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def list_metas_2026(ano: str = "2026") -> list[dict]:
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
    metas = []

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


def upsert_meta_2026(
    nome_vendedor: str,
    mes: str,
    valor_meta: float,
    projeto: str | None = None,
    mercado_vendas: str | None = None,
) -> None:
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


