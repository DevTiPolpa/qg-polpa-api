"""
normalize.py - Normalizacao de nome de empresa e CNPJ para deduplicacao.

Chave principal: nome normalizado (remove acentos, pontuacao, sufixos societarios).
Chave de confirmacao: CNPJ (14 digitos), quando presente dos dois lados.
"""

import re
from unidecode import unidecode

# Nota: a pontuacao (. - / , &) ja e removida ANTES deste passo (vira espaco ou some),
# entao os sufixos aqui devem ser escritos como ficam DEPOIS dessa limpeza (ex.: "S/A"
# e "S.A." nunca sobrevivem ate aqui - o que resta e "S A"/"SA"). Mesmo assim os
# sufixos passam por re.escape() ao montar o regex, pra um "." literal nunca ser
# interpretado como wildcard (bug real encontrado em teste: "S.A." sem escape casava
# como curinga "S??" e apagava "SEAL" de "SEAL ALIMENTOS").
CORPORATE_SUFFIXES = [
    "LTDA ME", "LTDA-ME", "LTDA", "EIRELI", "S A", "SA", "ME", "EPP",
    "INDUSTRIA E COMERCIO DE", "COMERCIO E INDUSTRIA DE",
    "IND E COM DE", "IND COM DE",
    "INDUSTRIA E COMERCIO", "IND E COM", "IND COM", "COMERCIO E INDUSTRIA",
    "COMERCIAL", "DISTRIBUIDORA", "CIA", "E CIA",
]

# Ordena do sufixo mais longo para o mais curto, para nao deixar um sufixo
# curto (ex.: "LTDA") remover so parte de um sufixo composto (ex.: "LTDA ME").
_SUFFIXES_SORTED = sorted(CORPORATE_SUFFIXES, key=len, reverse=True)


def normalize_company_name(raw: str | None) -> str:
    if not raw:
        return ""
    s = unidecode(raw).upper()
    s = re.sub(r"[.\-/,&]", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    for suf in _SUFFIXES_SORTED:
        s = re.sub(rf"\b{re.escape(suf)}\b", "", s).strip()
    return re.sub(r"\s+", " ", s).strip()


def normalize_cnpj(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return digits if len(digits) == 14 else None
