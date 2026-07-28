"""
exclusion_queries.py - Duas finalidades DIFERENTES, nao confundir:

1) build_prompt_exclusion_list(segmento, limit=60)
   Lista CURTA, filtrada pelo segmento pedido no briefing, pra caber embutida no
   texto do prompt da Manus (Parte 2 do app). So essa lista tem recorte de segmento.

2) build_full_internal_lookup()
   Base COMPLETA (sem filtro de segmento, sem limite artificial), usada pela
   classificacao/cruzamento (Parte 3). No pedido original do usuario, o bloqueio
   "cliente ativo (24m) ou ja e lead/deal no CRM" NAO tem recorte de segmento -
   uma empresa que ja e cliente bloqueia sempre, mesmo que o segmento dela no
   cadastro seja diferente do que a vendedora esta buscando agora. O recorte por
   segmento serve SO pra caber no prompt (item 1), nunca pra decidir o que bloqueia.

Descoberta ao investigar o banco: `grupo_produto` em fato_vendas NAO e o segmento do
cliente (sao so 10 valores de formato de produto da propria Polpa Brasil, tipo "PA
CUBOS"). Quem carrega o segmento do cliente e `perfil_parceiro`, com valores que batem
quase 1:1 com o enum `segmento_produto` usado nos deals do Bitrix (ver
Polpa Brasil IA/sync_mssql.py _SEGMENTO_PRODUTO).
"""

import re
from collections import Counter
from unidecode import unidecode

from app.geracao_listas.db import get_conn
from app.geracao_listas.classify import LookupEntry, is_junk_candidate_name, is_foreign_reference
from app.geracao_listas.normalize import normalize_company_name

_SEGMENT_KEYS_FOLDED = None  # cache: {chave_sem_acento: chave_original}

# Editar/expandir conforme novos segmentos aparecerem no briefing.
# perfil_parceiro: valores reais da coluna fato_vendas.perfil_parceiro
# deal_segment_ids: IDs do enum UF_CRM segmento_produto em crm_deals (ver sync_mssql.py)
# lead_keywords: crm_leads nao tem campo estruturado de segmento -> busca por palavra-chave
SEGMENT_CONFIG = {
    "barra de cereais":        {"perfil_parceiro": ["BARRAS DE CEREAIS"],        "deal_segment_ids": ["1964"], "lead_keywords": ["barra de cereal", "barras de cereal"]},
    "barras de frutas":        {"perfil_parceiro": ["BARRAS DE FRUTAS"],         "deal_segment_ids": ["1966"], "lead_keywords": ["barra de fruta", "barras de fruta"]},
    "biscoitos":               {"perfil_parceiro": ["BISCOITOS"],                "deal_segment_ids": ["1968"], "lead_keywords": ["biscoito"]},
    "cereais matinais":        {"perfil_parceiro": ["CEREAIS MATINAIS"],         "deal_segment_ids": ["1970"], "lead_keywords": ["cereal matinal", "cereais matinais"]},
    "chas":                    {"perfil_parceiro": ["CHÁS"],                     "deal_segment_ids": ["1972"], "lead_keywords": ["chá", "chás"]},
    "chocolates":              {"perfil_parceiro": ["CHOCOLATES"],               "deal_segment_ids": ["1974"], "lead_keywords": ["chocolate"]},
    "doces e confeitaria":     {"perfil_parceiro": ["Balas / Doces"],            "deal_segment_ids": ["1976"], "lead_keywords": ["doce", "confeitaria", "bala"]},
    "iogurtes":                {"perfil_parceiro": ["SORVETES E IOGURTES"],      "deal_segment_ids": ["1978"], "lead_keywords": ["iogurte"]},
    "panificacao artesanal":   {"perfil_parceiro": ["PANIFICAÇÃO E CONFEITARIA"],"deal_segment_ids": ["1980"], "lead_keywords": ["panificação artesanal", "padaria"]},
    "panificacao industrial":  {"perfil_parceiro": ["PANIFICAÇÃO INDUSTRIAL"],   "deal_segment_ids": ["1982"], "lead_keywords": ["panificação industrial"]},
    "racoes animais / pet":    {"perfil_parceiro": ["PET"],                      "deal_segment_ids": ["1984"], "lead_keywords": ["ração", "pet food", "alimento animal"]},
    "sorvetes":                {"perfil_parceiro": ["SORVETES E IOGURTES"],      "deal_segment_ids": ["1986"], "lead_keywords": ["sorvete"]},
    "granolas":                {"perfil_parceiro": [],                          "deal_segment_ids": ["1988"], "lead_keywords": ["granola"]},
    "suplementos":             {"perfil_parceiro": ["SUPLEMENTOS"],              "deal_segment_ids": ["8375"],"lead_keywords": ["suplemento"]},
    "barra proteica":          {"perfil_parceiro": [],                          "deal_segment_ids": ["8377"],"lead_keywords": ["barra proteica", "barra protéica"]},
    "bebidas naturais":        {"perfil_parceiro": ["BEBIDAS NATURAIS"],         "deal_segment_ids": [],      "lead_keywords": ["bebida natural", "suco"]},
    "farofas":                 {"perfil_parceiro": ["FAROFAS"],                  "deal_segment_ids": [],      "lead_keywords": ["farofa"]},
}


def _fold(s: str) -> str:
    return unidecode(s).strip().lower()


def resolve_segment_key(segmento_livre: str) -> str | None:
    """Casa o texto livre digitado/falado no briefing com uma chave conhecida
    de SEGMENT_CONFIG (match exato ou por substring, sem distinguir acento/caixa)."""
    global _SEGMENT_KEYS_FOLDED
    if not segmento_livre:
        return None
    if _SEGMENT_KEYS_FOLDED is None:
        _SEGMENT_KEYS_FOLDED = {_fold(k): k for k in SEGMENT_CONFIG}
    alvo = _fold(segmento_livre)
    if alvo in _SEGMENT_KEYS_FOLDED:
        return _SEGMENT_KEYS_FOLDED[alvo]
    for chave_folded, chave_original in _SEGMENT_KEYS_FOLDED.items():
        if chave_folded in alvo or alvo in chave_folded:
            return chave_original
    return None


# ---------------------------------------------------------------------------
# 1) Lista curta para o prompt da Manus (COM recorte de segmento)
# ---------------------------------------------------------------------------

def build_prompt_exclusion_list(
    segmento_livre: str, segmento_canonico: str | None = None, limit: int = 60
) -> tuple[list[str], bool]:
    """Retorna (nomes, truncado). 'truncado' = True se bateu no limite (sinal de
    que o segmento tem mais empresas do que coube na lista - nao esconder isso).

    segmento_canonico: chave de SEGMENT_CONFIG ja resolvida (ex.: pelo agente do
    briefing, que consegue mapear "Pet Food" -> "racoes animais / pet" muito melhor
    que um match de substring cego). Se vier valida, tem prioridade sobre tentar
    resolver segmento_livre por conta propria."""
    chave = segmento_canonico if segmento_canonico in SEGMENT_CONFIG else resolve_segment_key(segmento_livre)
    nomes: list[str] = []
    vistos_normalizados: set[str] = set()
    if chave is None:
        return nomes, False
    cfg = SEGMENT_CONFIG[chave]
    conn = get_conn()
    cur = conn.cursor()

    def _acrescentar(candidatos: list[str]):
        for nome in candidatos:
            norm = normalize_company_name(nome)
            if is_junk_candidate_name(norm) or norm in vistos_normalizados or is_foreign_reference(nome):
                continue
            vistos_normalizados.add(norm)
            nomes.append(nome)

    if cfg["perfil_parceiro"]:
        placeholders = ", ".join("?" for _ in cfg["perfil_parceiro"])
        cur.execute(f"""
            SELECT DISTINCT TOP (?) RAZAOSOCIAL
            FROM fato_vendas
            WHERE dt_prev_entrega_embarque >= DATEADD(month, -24, GETDATE())
              AND (cod_top IS NULL OR cod_top <> 1023)
              AND perfil_parceiro IN ({placeholders})
            ORDER BY RAZAOSOCIAL
        """, (limit, *cfg["perfil_parceiro"]))
        _acrescentar([r[0] for r in cur.fetchall()])

    if cfg["deal_segment_ids"] and len(nomes) < limit:
        restante = limit - len(nomes)
        like_conds = " OR ".join("cd.segmento_produto LIKE ?" for _ in cfg["deal_segment_ids"])
        like_params = [f"%{sid}%" for sid in cfg["deal_segment_ids"]]
        cur.execute(f"""
            SELECT DISTINCT TOP (?) cc.title
            FROM crm_deals cd
            LEFT JOIN crm_companies cc ON cd.company_id = cc.id
            WHERE (cd.category_id = '0' OR cd.category_id IS NULL)
              AND cc.title IS NOT NULL
              AND ({like_conds})
            ORDER BY cc.title
        """, (restante, *like_params))
        _acrescentar([r[0] for r in cur.fetchall()])

    if cfg["lead_keywords"] and len(nomes) < limit:
        restante = limit - len(nomes)
        like_conds = " OR ".join(
            "(cl.title LIKE ? OR cl.company_title LIKE ? OR cl.comments LIKE ?)"
            for _ in cfg["lead_keywords"]
        )
        like_params = []
        for kw in cfg["lead_keywords"]:
            like_params += [f"%{kw}%", f"%{kw}%", f"%{kw}%"]
        cur.execute(f"""
            SELECT DISTINCT TOP (?) cl.title, cl.company_title
            FROM crm_leads cl
            WHERE cl.company_title IS NOT NULL AND cl.company_title <> ''
              AND ({like_conds})
            ORDER BY cl.company_title
        """, (restante, *like_params))
        # A marca de "estrangeiro" (ex.: "- Mexico", "Inc.") as vezes esta so no
        # title e nao no company_title (ou vice-versa) - checa os dois antes de
        # decidir excluir, senao passa batido (ex.: "Blommer Chocolate Company"
        # sem sufixo no company_title, mas com "- EUA" no title do mesmo lead).
        _acrescentar([
            r[1] or r[0] for r in cur.fetchall()
            if not (is_foreign_reference(r[0]) or is_foreign_reference(r[1]))
        ])

    conn.close()
    nomes = nomes[:limit]
    truncado = len(nomes) >= limit
    return nomes, truncado


# ---------------------------------------------------------------------------
# 2) Base completa para classificacao (SEM recorte de segmento, sem limite)
# ---------------------------------------------------------------------------

def build_full_internal_lookup() -> list[LookupEntry]:
    lookup: list[LookupEntry] = []
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT DISTINCT cod_parc, RAZAOSOCIAL, nome_vendedor
        FROM fato_vendas
        WHERE RAZAOSOCIAL IS NOT NULL
          AND dt_prev_entrega_embarque >= DATEADD(month, -24, GETDATE())
          AND (cod_top IS NULL OR cod_top <> 1023)
    """)
    for cod_parc, nome, vendedor in cur.fetchall():
        norm = normalize_company_name(nome)
        if not is_junk_candidate_name(norm):
            # nome_vendedor as vezes vem como "23 - TALIA STEFANI SCAIN" (codigo do
            # ERP na frente) - mesmo padrao de limpeza do qg-polpa-brasil/db.ts
            # normalizeSellerName, so pra exibicao ficar consistente com o CRM.
            resp = re.sub(r"^\d+\s*-\s*", "", vendedor).strip() if vendedor else None
            lookup.append(LookupEntry(nome, norm, "FATO_VENDAS", str(cod_parc), responsavel=resp))

    # Leads: usar SO company_title deixava de fora a maioria (so 35% dos leads tem
    # esse campo preenchido) e, mesmo quando preenchido, as vezes e um alias sem
    # relacao textual com o nome comercial (ex.: um lead da "Puro Trato" tinha
    # company_title = "J A TEIXEIRA VETERINARIA LTDA" - nome de outra entidade
    # ligada, nao a marca). Por isso agora entram COMO CANDIDATOS SEPARADOS: o
    # titulo do lead, o company_title (se houver) e o titulo da company vinculada
    # via company_id (se houver) - qualquer um dos tres pode ser o que bate com o
    # nome que a Manus devolveu. Descoberto revisando manualmente uma lista real
    # (15 de 24 "livres" na verdade ja estavam no CRM, maioria por causa disso).
    cur.execute("""
        SELECT cl.id, cl.title, cl.company_title, cc.title AS company_vinculada,
               LTRIM(RTRIM(u.name + ' ' + COALESCE(u.last_name, ''))) AS responsavel
        FROM crm_leads cl
        LEFT JOIN crm_companies cc ON cl.company_id = cc.id
        LEFT JOIN crm_users u ON cl.assigned_by_id = u.id
    """)
    for id_, title, company_title, company_vinculada, responsavel in cur.fetchall():
        # Prospeccao esta limitada ao Brasil por enquanto - lead de referencia
        # internacional (marca de pais/sufixo estrangeiro em QUALQUER um dos 3
        # campos) fica de fora inteiro, nao so a variante que carrega a marca.
        if any(is_foreign_reference(c) for c in (title, company_title, company_vinculada)):
            continue
        vistos_norm = set()
        for nome in (title, company_title, company_vinculada):
            if not nome:
                continue
            norm = normalize_company_name(nome)
            if is_junk_candidate_name(norm) or norm in vistos_norm:
                continue
            vistos_norm.add(norm)
            lookup.append(LookupEntry(nome, norm, "CRM_LEAD", str(id_), responsavel=responsavel))

    cur.execute("""
        SELECT DISTINCT cd.company_id, cc.title,
               LTRIM(RTRIM(u.name + ' ' + COALESCE(u.last_name, ''))) AS responsavel
        FROM crm_deals cd
        JOIN crm_companies cc ON cd.company_id = cc.id
        LEFT JOIN crm_users u ON cd.assigned_by_id = u.id
        WHERE (cd.category_id = '0' OR cd.category_id IS NULL)
          AND cc.title IS NOT NULL AND cc.title <> ''
    """)
    for id_, nome, responsavel in cur.fetchall():
        norm = normalize_company_name(nome)
        if not is_junk_candidate_name(norm) and not is_foreign_reference(nome):
            lookup.append(LookupEntry(nome, norm, "CRM_DEAL", str(id_), responsavel=responsavel))

    # Todas as companies do CRM, mesmo sem negocio (deal) aberto vinculado - uma
    # empresa ja cadastrada no Bitrix (por ter sido lead/deal no passado, ou
    # cadastrada manualmente) ja e "conhecida", nao so quando tem deal ativo.
    # Antes so entravam companies com deal em category 0/NULL (join acima), o que
    # deixava de fora companies que so tem historico de lead ou foram cadastradas
    # sem virar negocio - essas nao apareciam em lugar nenhum do lookup.
    cur.execute("""
        SELECT cc.id, cc.title,
               LTRIM(RTRIM(u.name + ' ' + COALESCE(u.last_name, ''))) AS responsavel
        FROM crm_companies cc
        LEFT JOIN crm_users u ON cc.assigned_by_id = u.id
        WHERE cc.title IS NOT NULL AND cc.title <> ''
    """)
    for id_, nome, responsavel in cur.fetchall():
        norm = normalize_company_name(nome)
        if not is_junk_candidate_name(norm) and not is_foreign_reference(nome):
            lookup.append(LookupEntry(nome, norm, "CRM_COMPANY", str(id_), responsavel=responsavel))

    conn.close()
    return lookup


# ---------------------------------------------------------------------------
# 3) Frequencia de token para classify.is_distinctive_name (ver classify.py)
# ---------------------------------------------------------------------------

def build_token_frequency() -> Counter:
    """Conta em quantos NOMES NORMALIZADOS DISTINTOS cada token aparece, usando o
    universo mais amplo possivel (fato_vendas inteiro, sem filtro de 24 meses, +
    todos os leads + todas as companies) - quanto maior a amostra, mais estavel a
    frequencia. Deduplicar por nome normalizado ANTES de contar e essencial: senao
    uma empresa citada 3x (ERP + lead + deal) infla artificialmente seus proprios
    tokens."""
    nomes_normalizados: set[str] = set()
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT RAZAOSOCIAL FROM fato_vendas WHERE RAZAOSOCIAL IS NOT NULL")
    for (n,) in cur.fetchall():
        norm = normalize_company_name(n)
        if norm:
            nomes_normalizados.add(norm)

    cur.execute("SELECT DISTINCT company_title FROM crm_leads WHERE company_title IS NOT NULL AND company_title <> ''")
    for (n,) in cur.fetchall():
        norm = normalize_company_name(n)
        if norm:
            nomes_normalizados.add(norm)

    cur.execute("SELECT DISTINCT title FROM crm_companies WHERE title IS NOT NULL AND title <> ''")
    for (n,) in cur.fetchall():
        norm = normalize_company_name(n)
        if norm:
            nomes_normalizados.add(norm)

    conn.close()

    freq: Counter = Counter()
    for norm in nomes_normalizados:
        for token in set(norm.split()):
            freq[token] += 1
    return freq
