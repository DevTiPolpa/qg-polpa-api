"""
classify.py - Classificacao de empresas em 3 niveis: LIVRE / REVISAR (ambiguo) / BLOQUEADA (forte).

Regra de ouro (definida pelo usuario): bloquear uma empresa livre por engano e o pior
erro do sistema. Por isso o desenho e assimetrico - e facil cair em REVISAR, dificil
cair em BLOQUEADA (forte), e o "match forte" so e permitido quando o nome contem pelo
menos um token distintivo (raro na base) - nao basta contar tokens ou usar uma lista
manual de palavras genericas, porque isso pegava mal marcas curtas mas inequivocas
(ex.: "Chocolates Garoto", "Dori Alimentos" ficavam presos em REVISAR so por terem
2 tokens). Distintividade e medida por frequencia real de cada token na base (ver
GENERIC_TOKEN_FREQ_THRESHOLD).

Lookup interno (par de cada card): vem SOMENTE de exclusion_queries.py (clientes
ativos 24m em fato_vendas + leads/deals do CRM), nunca do historico de listas
anteriores (gl_raw_items/gl_classified_items) - listas antigas que nunca viraram
lead/deal nao bloqueiam.
"""

from dataclasses import dataclass
from collections import Counter
from rapidfuzz import fuzz
from unidecode import unidecode

from app.geracao_listas.normalize import normalize_company_name, normalize_cnpj

FORTE_THRESHOLD = 95      # rapidfuzz token_sort_ratio minimo para match forte por similaridade
AMBIGUO_THRESHOLD = 85    # abaixo disso = sem match (livre)

# Um token e "generico" quando aparece em muitos nomes distintos da base (ex.:
# ALIMENTOS, BRASIL, INDUSTRIA, CHOCOLATES) - nesse caso ele sozinho nao prova
# identidade, porque varias empresas diferentes o usam. Calculado por frequencia
# (build_token_frequency em exclusion_queries.py), nao por lista manual - listas
# manuais nao escalam e ja erraram na pratica (ex.: nao previam "SEAL", "GAROTO").
#
# Threshold escolhido apos analisar a distribuicao real (2828 nomes, 3377 tokens
# distintos): mediana de frequencia = 1, p90 = 3, p95 = 5, p99 = 20. Um corte em
# 10 (top ~2.6% dos tokens) separa bem os termos genericos do setor (ALIMENTOS 445,
# DE 295, BRASIL 126, INDUSTRIA 98, CHOCOLATES 90, COMERCIO 103, FOODS 86, PET 68...)
# de marcas distintivas (GAROTO 3, DORI 1, HERSHEYS 3, BARION 1, GELNEX 1).
# Efeito colateral aceito: marcas grandes com muitas filiais/entidades cadastradas
# separadamente (BIMBO=13, MONDELEZ=21, KELLOGGS=17) tambem passam do threshold e
# contam como "genericas" - nesses casos raros a marca sozinha nao basta, mas isso
# so empurra pra REVISAR (nunca bloqueia errado), e sao clientes grandes que a
# vendedora reconhece de cara ao revisar.
GENERIC_TOKEN_FREQ_THRESHOLD = 10


_TITULOS_PLACEHOLDER = {
    "SEM TITULO", "SEM NOME", "NA", "TESTE", "TEST", "TESTE TESTE",
}


def is_junk_candidate_name(normalized: str) -> bool:
    """Filtra candidatos-lixo da base interna (telefone, CNPJ solto, titulo vazio,
    placeholder tipo "Sem titulo" do Bitrix quando um deal/lead nao tem empresa
    vinculada) para que nao virem falso-positivo de match. Usado ao montar o
    lookup interno e a lista de exclusao do prompt."""
    if not normalized or len(normalized) < 2:
        return True
    if normalized in _TITULOS_PLACEHOLDER:
        return True
    return not any(c.isalpha() for c in normalized)


# Prospeccao esta limitada ao Brasil por enquanto. Alguns leads/companies no Bitrix
# sao referencias de mercado internacional (concorrentes/benchmarks de fora, usados
# so pra inteligencia de mercado, nao prospeccao real) - tipicamente cadastrados
# como "Nome - Pais" (ex.: "Barry Callebaut - Mexico") ja que o campo de pais do
# Bitrix quase nunca e preenchido (2251 de 2273 leads sem pais nenhum). Filtrar
# esses evita que ocupem vaga na lista de exclusao do prompt (que e limitada a 60
# nomes) e que gerem revisao desnecessaria na classificacao.
_PAISES_ESTRANGEIROS = {
    "suica", "suiça", "mexico", "eua", "usa", "estados unidos",
    "alemanha", "franca", "italia", "argentina", "chile", "colombia", "peru",
    "china", "reino unido", "canada", "espanha", "portugal", "holanda",
    "belgica", "japao", "coreia", "india", "australia", "uruguai", "paraguai",
    "bolivia", "equador", "venezuela", "russia",
}
# Sufixos de razao social tipicos de fora do Brasil (empresa brasileira usa LTDA/
# EIRELI/S.A./ME/EPP - ja tratados como sufixo em normalize.py). Aqui e so pra
# marcar como estrangeiro, nao pra remover do nome.
_SUFIXOS_ESTRANGEIROS = {"LIMITED", "INC", "LLC", "GMBH", "CORP", "CORPORATION"}


def is_foreign_reference(nome_raw: str) -> bool:
    """True se o nome tem marca clara de ser uma referencia de fora do Brasil (nao
    detecta 100% dos casos - so quando ha um sinal textual explicito; nome
    'internacional-soante' sem marcador nenhum, tipo 'Chocolat du Jour', nao da
    pra distinguir com seguranca de uma marca brasileira de verdade so pelo texto)."""
    if not nome_raw:
        return False
    texto = unidecode(nome_raw).strip().lower()
    if " - " in texto:
        sufixo = texto.rsplit(" - ", 1)[1].strip()
        if sufixo in _PAISES_ESTRANGEIROS:
            return True
    tokens = normalize_company_name(nome_raw).split()
    return any(t in _SUFIXOS_ESTRANGEIROS for t in tokens)


def is_distinctive_name(
    normalized: str, token_freq: Counter, threshold: int = GENERIC_TOKEN_FREQ_THRESHOLD
) -> bool:
    """Um nome e 'distintivo' o suficiente pra sustentar um match forte se tiver
    PELO MENOS 1 token raro (frequencia < threshold na base), mesmo que o nome
    inteiro tenha so 1 ou 2 tokens (ex.: "Chocolates Garoto" -> GAROTO e raro,
    entao o nome inteiro e distintivo, apesar de "CHOCOLATES" ser comum).
    Se TODOS os tokens do nome forem comuns (>= threshold), o nome nunca vira
    forte, mesmo batendo exato - risco real de colisao com outra empresa."""
    tokens = normalized.split()
    if not tokens:
        return False
    return any(token_freq.get(t, 0) < threshold for t in tokens)


@dataclass
class LookupEntry:
    nome_original: str
    nome_normalizado: str
    fonte: str          # FATO_VENDAS | CRM_LEAD | CRM_DEAL | CRM_COMPANY
    ref_id: str
    cnpj_normalizado: str | None = None
    responsavel: str | None = None   # vendedor (fato_vendas) ou dono no CRM (assigned_by_id)


@dataclass
class ClassificationResult:
    classe: str                 # LIVRE | REVISAR | BLOQUEADA
    motivo: str
    fonte_bloqueio: str | None = None
    match_score: float | None = None
    match_ref_tipo: str | None = None
    match_ref_id: str | None = None
    match_ref_nome: str | None = None
    responsavel: str | None = None


_FONTE_MOTIVO = {
    "FATO_VENDAS": "cliente ativo (comprou nos ultimos 24 meses)",
    "CRM_LEAD": "ja existe como lead no CRM",
    "CRM_DEAL": "ja existe como negocio (deal) no CRM",
    "CRM_COMPANY": "ja existe como empresa cadastrada no CRM",
}


def _tokens_raros(normalized: str, token_freq: Counter, threshold: int) -> set[str]:
    return {t for t in normalized.split() if token_freq.get(t, 0) < threshold}


def classify_company(
    nome_raw: str, cnpj_raw: str | None, lookup: list[LookupEntry], token_freq: Counter
) -> ClassificationResult:
    nome_norm = normalize_company_name(nome_raw)
    cnpj_norm = normalize_cnpj(cnpj_raw)

    if not nome_norm:
        return ClassificationResult("REVISAR", "nome vazio ou nao identificavel apos normalizacao")

    candidatos_validos = [e for e in lookup if not is_junk_candidate_name(e.nome_normalizado)]
    distintivo = is_distinctive_name(nome_norm, token_freq)

    # 1) Chave de confirmacao CNPJ - so decide quando os DOIS lados tem CNPJ.
    if cnpj_norm:
        com_cnpj = [e for e in candidatos_validos if e.cnpj_normalizado]
        bate_cnpj = [e for e in com_cnpj if e.cnpj_normalizado == cnpj_norm]
        if bate_cnpj:
            e = bate_cnpj[0]
            return ClassificationResult(
                "BLOQUEADA", f"CNPJ confere com {_FONTE_MOTIVO[e.fonte]}", e.fonte,
                100.0, e.fonte, e.ref_id, e.nome_original, e.responsavel,
            )
        # Nome bate mas CNPJ diverge -> contradicao, nunca forte.
        nome_igual = [e for e in com_cnpj if e.nome_normalizado == nome_norm]
        if nome_igual:
            e = nome_igual[0]
            return ClassificationResult(
                "REVISAR", "nome parecido mas CNPJ diverge - revisar manualmente", e.fonte,
                None, e.fonte, e.ref_id, e.nome_original, e.responsavel,
            )

    # 2) Match exato de nome normalizado.
    #
    # Observado em teste com dados reais: quando o mesmo nome normalizado aparece em
    # mais de um registro interno (ref_id distinto), na pratica isso quase sempre e a
    # MESMA empresa presente em mais de uma fonte (ex.: "BARION ALIMENTOS" existe como
    # cliente ativo em fato_vendas E como company sincronizada do CRM - a mesma Barion,
    # nao duas empresas diferentes) - nao e risco de colisao de nome, e so a empresa
    # aparecendo em dois sistemas. Por isso NAO tratamos "multiplos ref_id" como motivo
    # de ambiguidade por si so; o guarda-corpo real contra falso-positivo e o
    # is_distinctive_name() abaixo (frequencia de token), que pega o caso de verdade
    # arriscado: nome composto so por termos comuns na base (ex.: "Alimentos Ltda").
    iguais = [e for e in candidatos_validos if e.nome_normalizado == nome_norm]
    if iguais:
        e = iguais[0]
        fontes_distintas = sorted({x.fonte for x in iguais})
        if not distintivo:
            return ClassificationResult(
                "REVISAR", "nome composto so por termos comuns na base - mesmo batendo exato, nao e seguro bloquear automaticamente",
                e.fonte, None, e.fonte, e.ref_id, e.nome_original, e.responsavel,
            )
        motivo = _FONTE_MOTIVO[e.fonte].capitalize()
        if len(fontes_distintas) > 1:
            motivo += f" (tambem encontrado em: {', '.join(f for f in fontes_distintas if f != e.fonte)})"
        return ClassificationResult(
            "BLOQUEADA", motivo, e.fonte,
            100.0, e.fonte, e.ref_id, e.nome_original, e.responsavel,
        )

    # 3) Fuzzy - so entra aqui se nao houve match exato.
    melhor_score = -1.0
    melhor_entry = None
    for e in candidatos_validos:
        score = fuzz.token_sort_ratio(nome_norm, e.nome_normalizado)
        if score > melhor_score:
            melhor_score = score
            melhor_entry = e

    if melhor_entry is None or melhor_score < AMBIGUO_THRESHOLD:
        # Nomes as vezes sao MUITO diferentes no geral (razao social x apelido/marca,
        # nome do lead cheio de texto solto etc.) mesmo sendo a mesma empresa - nesses
        # casos o token_sort_ratio do nome inteiro fica baixo, mas um token RARO
        # (ex.: "MATSUDA", "GUABI", "FOSFERPET") aparece em ambos e ja e um sinal forte
        # o suficiente pra mandar pra REVISAR (nunca pra BLOQUEADA - e um sinal mais
        # fraco que similaridade de nome inteiro, so vale pra nao deixar passar batido).
        tokens_raros_entrada = _tokens_raros(nome_norm, token_freq, GENERIC_TOKEN_FREQ_THRESHOLD)
        candidatos_com_token_raro = [
            e for e in candidatos_validos
            if tokens_raros_entrada & set(e.nome_normalizado.split())
        ] if tokens_raros_entrada else []
        if candidatos_com_token_raro:
            melhor_raro = max(
                candidatos_com_token_raro,
                key=lambda e: fuzz.token_sort_ratio(nome_norm, e.nome_normalizado),
            )
            score_raro = fuzz.token_sort_ratio(nome_norm, melhor_raro.nome_normalizado)
            token_comum = next(iter(tokens_raros_entrada & set(melhor_raro.nome_normalizado.split())))
            return ClassificationResult(
                "REVISAR",
                f'nomes diferentes no geral, mas compartilham o termo raro "{token_comum}" '
                f'com "{melhor_raro.nome_original}" - revisar manualmente',
                melhor_raro.fonte, score_raro, melhor_raro.fonte, melhor_raro.ref_id, melhor_raro.nome_original,
                melhor_raro.responsavel,
            )
        return ClassificationResult("LIVRE", "sem correspondencia na base interna")

    if melhor_score < FORTE_THRESHOLD:
        return ClassificationResult(
            "REVISAR", f"possivel duplicata - {melhor_score:.0f}% similar a \"{melhor_entry.nome_original}\"",
            melhor_entry.fonte, melhor_score, melhor_entry.fonte, melhor_entry.ref_id, melhor_entry.nome_original,
            melhor_entry.responsavel,
        )

    # score >= FORTE_THRESHOLD: so vira forte se os dois nomes forem distintivos.
    if not distintivo or not is_distinctive_name(melhor_entry.nome_normalizado, token_freq):
        return ClassificationResult(
            "REVISAR",
            f"nome muito parecido ({melhor_score:.0f}%) com \"{melhor_entry.nome_original}\", "
            "mas composto so por termos comuns na base - nao e seguro bloquear automaticamente",
            melhor_entry.fonte, melhor_score, melhor_entry.fonte, melhor_entry.ref_id, melhor_entry.nome_original,
            melhor_entry.responsavel,
        )

    return ClassificationResult(
        "BLOQUEADA",
        f"{_FONTE_MOTIVO[melhor_entry.fonte].capitalize()} (nome {melhor_score:.0f}% similar - provavel variacao de grafia)",
        melhor_entry.fonte, melhor_score, melhor_entry.fonte, melhor_entry.ref_id, melhor_entry.nome_original,
        melhor_entry.responsavel,
    )


@dataclass
class Candidato:
    nome_original: str
    fonte: str
    ref_id: str
    score: float
    cnpj_bate: bool
    responsavel: str | None = None


def find_top_candidates(
    nome_raw: str, cnpj_raw: str | None, lookup: list[LookupEntry], top_n: int = 8
) -> list[Candidato]:
    """Busca manual (Parte 6 - consulta avulsa): ao contrario de classify_company
    (que so devolve o veredito automatico com 1 melhor match), aqui devolvemos os
    top_n candidatos mais parecidos, pra o usuario olhar com os proprios olhos e
    decidir - util quando o veredito automatico fica em duvida ou quando se quer
    conferir varias grafias parecidas de uma vez."""
    nome_norm = normalize_company_name(nome_raw)
    cnpj_norm = normalize_cnpj(cnpj_raw)
    if not nome_norm:
        return []

    candidatos_validos = [e for e in lookup if not is_junk_candidate_name(e.nome_normalizado)]
    vistos: dict[tuple[str, str], Candidato] = {}  # (nome_original, fonte) -> melhor candidato
    for e in candidatos_validos:
        cnpj_bate = bool(cnpj_norm and e.cnpj_normalizado and cnpj_norm == e.cnpj_normalizado)
        if e.nome_normalizado == nome_norm:
            score = 100.0
        else:
            score = fuzz.token_sort_ratio(nome_norm, e.nome_normalizado)
        if cnpj_bate:
            score = 100.0
        if score < 60 and not cnpj_bate:
            continue
        chave = (e.nome_original, e.fonte)
        # Mesma empresa pode aparecer com varios ref_id na mesma fonte (ex.: dois
        # cod_parc distintos em fato_vendas para o mesmo cadastro duplicado) -
        # colapsa pra 1 linha na exibicao, nao interessa qual ref_id especifico.
        if chave not in vistos or score > vistos[chave].score:
            vistos[chave] = Candidato(e.nome_original, e.fonte, e.ref_id, score, cnpj_bate, e.responsavel)

    resultados = sorted(vistos.values(), key=lambda c: (-c.cnpj_bate, -c.score))
    return resultados[:top_n]
