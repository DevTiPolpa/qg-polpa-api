"""
db.py - Conexao com o SQL Server para o modulo Geracao de Listas.

Reaproveita a MESMA connection string do resto do qg-polpa-api (app/database.py,
variaveis DB_* do .env deste repo) - nao aponta para nenhum banco/host fora do
que ja e usado pelo restante da API.
"""

import pyodbc

from app.database import get_connection_string


def get_conn() -> pyodbc.Connection:
    return pyodbc.connect(get_connection_string(), autocommit=True)
