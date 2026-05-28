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

