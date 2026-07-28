"""
ingest.py - Le a lista que a Manus devolveu, seja por upload de planilha (.xlsx)
ou por colagem de texto (tabulado, com ; ou so uma lista de nomes).
"""

import io
import re
import openpyxl

# Mapeamento de cabecalho (case-insensitive, sem acento) -> campo interno
_HEADER_MAP = {
    "empresa": "nome", "nome": "nome", "razao social": "nome", "razaosocial": "nome", "company": "nome",
    "cnpj": "cnpj",
    "cidade": "cidade", "city": "cidade",
    "uf": "uf", "estado": "uf",
    "site": "site", "website": "site", "web": "site",
    "telefone": "telefone", "fone": "telefone", "phone": "telefone",
    "email": "email", "e-mail": "email",
    "marca": "marca", "marcas": "marca", "marca(s)": "marca", "brand": "marca",
    # Fallback defensivo: o prompt pede colunas separadas, mas se a Manus (ou uma
    # colagem manual) ainda assim juntar campos numa coluna so, tenta separar em
    # vez de simplesmente perder o dado (foi o que aconteceu numa lista real -
    # "cidade/UF" combinado fez cidade e estado sumirem inteiros da planilha).
    "cidade/uf": "cidade_uf", "cidade / uf": "cidade_uf", "cidade-uf": "cidade_uf",
    "telefone/email": "contato", "telefone / email": "contato",
    "telefone e/ou e-mail de contato": "contato", "telefone/e-mail": "contato", "contato": "contato",
}

_CAMPOS = ["nome", "cnpj", "cidade", "uf", "site", "telefone", "email", "marca"]


def _fold_header(h: str) -> str:
    from unidecode import unidecode
    return unidecode(str(h)).strip().lower()


def parse_upload_xlsx(file_bytes: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    header = [_fold_header(h) if h else "" for h in rows[0]]
    campo_por_coluna = [_HEADER_MAP.get(h) for h in header]

    # Se nenhuma coluna reconhecida, trata a 1a coluna inteira (inclusive linha 1) como nome.
    if not any(campo_por_coluna):
        itens = []
        for i, row in enumerate(rows, start=1):
            if row and row[0]:
                itens.append({"linha_origem": i, "nome": str(row[0]).strip()})
        return itens

    itens = []
    for i, row in enumerate(rows[1:], start=2):
        item = {"linha_origem": i}
        for col_idx, campo in enumerate(campo_por_coluna):
            if not campo or col_idx >= len(row) or row[col_idx] is None:
                continue
            valor = str(row[col_idx]).strip()
            if not valor:
                continue
            if campo == "cidade_uf":
                _split_cidade_uf(item, valor)
            elif campo == "contato":
                _split_contato(item, valor)
            else:
                item[campo] = valor
        if item.get("nome"):
            itens.append(item)
    return itens


def _split_cidade_uf(item: dict, valor: str):
    partes = [p.strip() for p in re.split(r"[/\-]", valor) if p.strip()]
    if len(partes) >= 2:
        item.setdefault("cidade", partes[0])
        item.setdefault("uf", partes[-1])
    elif partes:
        item.setdefault("cidade", partes[0])


def _split_contato(item: dict, valor: str):
    for parte in [p.strip() for p in valor.split("/") if p.strip()]:
        if "@" in parte:
            item.setdefault("email", parte)
        else:
            item.setdefault("telefone", parte)


def parse_pasted_text(texto: str) -> list[dict]:
    itens = []
    for i, linha in enumerate(texto.splitlines(), start=1):
        linha = linha.strip()
        if not linha:
            continue

        delimitador = None
        for cand in ["\t", ";", ","]:
            if cand in linha:
                delimitador = cand
                break

        if delimitador is None:
            itens.append({"linha_origem": i, "nome": linha})
            continue

        partes = [p.strip() for p in linha.split(delimitador)]
        # Primeira linha colada pode ser cabecalho - se bater com algum termo conhecido, pula.
        if i == 1 and any(_fold_header(p) in _HEADER_MAP for p in partes):
            continue

        item = {"linha_origem": i, "nome": partes[0]}
        for extra, campo in zip(partes[1:], ["cnpj", "cidade", "uf", "site", "telefone", "email", "marca"]):
            if extra:
                item[campo] = extra
        itens.append(item)
    return itens
