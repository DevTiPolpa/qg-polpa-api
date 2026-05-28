import os

import pyodbc
from dotenv import load_dotenv

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

