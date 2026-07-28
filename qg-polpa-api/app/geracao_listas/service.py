"""
service.py - Camada de negocio do modulo Geracao de Listas, chamada diretamente
(sem HTTP) pelas rotas /api/geracao-listas/* em app/main.py.

Portado do app standalone geracao-listas/app.py (fora deste repo) - mesma logica
de classificacao/persistencia, sem nenhuma dependencia de processo externo/porta.
"""

import base64
import io
import json
from datetime import datetime

from app.geracao_listas.db import get_conn
from app.geracao_listas.briefing_config import BRIEFING_QUESTIONS  # noqa: F401 (uso futuro/documentacao)
from app.geracao_listas.agent_briefing import run_briefing_agent
from app.geracao_listas.prompt_builder import build_manus_prompt
from app.geracao_listas.exclusion_queries import build_full_internal_lookup, build_token_frequency
from app.geracao_listas.classify import classify_company, find_top_candidates
from app.geracao_listas.ingest import parse_upload_xlsx, parse_pasted_text
from app.geracao_listas.evaluation import compute_evaluation
from app.geracao_listas.export_excel import build_workbook

# Cache de processo: lookup interno e frequencia de token nao mudam a cada request,
# so quando o Bitrix e sincronizado de novo (algumas vezes ao dia). Recalcular em
# toda classificacao seria lento sem necessidade.
_CACHE: dict = {"lookup": None, "token_freq": None, "calculado_em": None}


def _get_lookup_e_freq():
    if _CACHE["lookup"] is None:
        _CACHE["lookup"] = build_full_internal_lookup()
        _CACHE["token_freq"] = build_token_frequency()
        _CACHE["calculado_em"] = datetime.now()
    return _CACHE["lookup"], _CACHE["token_freq"]


def _serialize_history(history: list[dict]) -> list[dict]:
    """Converte os content blocks do SDK Anthropic (objetos) em dicts puros pra JSON."""
    serial = []
    for msg in history:
        content = msg["content"]
        if isinstance(content, str):
            serial.append(msg)
            continue
        blocos = []
        for b in content:
            if isinstance(b, dict):
                blocos.append(b)
            else:
                bloco = {"type": b.type}
                if b.type == "text":
                    bloco["text"] = b.text
                elif b.type == "tool_use":
                    bloco["id"] = b.id
                    bloco["name"] = b.name
                    bloco["input"] = b.input
                blocos.append(bloco)
        serial.append({"role": msg["role"], "content": blocos})
    return serial


# ---------------------------------------------------------------------------
# Briefing (chat + finalizacao)
# ---------------------------------------------------------------------------

def chat_briefing(message: str, history: list[dict]) -> dict:
    resposta, history_atualizado, briefing = run_briefing_agent(message, history)
    return {
        "resposta": resposta,
        "history": _serialize_history(history_atualizado),
        "briefing": briefing,
    }


def finalizar_briefing(briefing: dict, conversa: list, created_by: str | None) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    titulo = f"{briefing.get('segmento', '')} - {briefing.get('aplicacao', '')}".strip(" -")
    cur.execute(
        "INSERT INTO gl_cards (created_by, status, titulo) OUTPUT INSERTED.id VALUES (?, ?, ?)",
        (created_by, "PROMPT_GERADO", titulo),
    )
    card_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO gl_briefings (card_id, segmento, aplicacao, regiao, porte, look_alike, observacoes, conversa_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (card_id, briefing.get("segmento"), briefing.get("aplicacao"), briefing.get("regiao"),
         briefing.get("porte"), briefing.get("look_alike"), briefing.get("observacoes"),
         json.dumps(conversa, ensure_ascii=False)),
    )

    prompt_text, qtd_exclusao, truncado = build_manus_prompt(briefing)
    cur.execute(
        "INSERT INTO gl_manus_prompts (card_id, prompt_text, exclusion_count, truncado) VALUES (?, ?, ?, ?)",
        (card_id, prompt_text, qtd_exclusao, truncado),
    )
    conn.close()

    return {"card_id": card_id, "prompt": prompt_text, "exclusion_count": qtd_exclusao, "truncado": truncado}


# ---------------------------------------------------------------------------
# Cards: listar / detalhe / criar / excluir
# ---------------------------------------------------------------------------

def listar_cards() -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.titulo, c.created_by, c.created_at, c.status,
               b.segmento, e.total_manus, e.total_livre, e.total_revisar, e.total_bloqueada
        FROM gl_cards c
        LEFT JOIN gl_briefings b ON b.card_id = c.id
        LEFT JOIN gl_evaluations e ON e.card_id = c.id
        ORDER BY c.created_at DESC
    """)
    linhas = cur.fetchall()
    conn.close()
    return [
        {
            "id": r[0], "titulo": r[1], "created_by": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "status": r[4], "segmento": r[5],
            "total_manus": r[6], "total_livre": r[7], "total_revisar": r[8], "total_bloqueada": r[9],
        }
        for r in linhas
    ]


def _carregar_card(card_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, titulo, created_by, created_at, status FROM gl_cards WHERE id = ?", (card_id,))
    card = cur.fetchone()
    if not card:
        conn.close()
        return None

    cur.execute("""SELECT segmento, aplicacao, regiao, porte, look_alike, observacoes
                   FROM gl_briefings WHERE card_id = ?""", (card_id,))
    briefing = cur.fetchone()

    cur.execute("SELECT prompt_text, exclusion_count, truncado FROM gl_manus_prompts WHERE card_id = ? ORDER BY id DESC", (card_id,))
    prompt_row = cur.fetchone()

    cur.execute("""
        SELECT ri.nome_original, ri.cidade, ri.uf, ri.cnpj_original, ri.site, ri.telefone, ri.email, ri.marca,
               ci.classe, ci.motivo, ci.fonte_bloqueio, ci.match_ref_nome, ci.match_score, ci.responsavel
        FROM gl_raw_items ri
        LEFT JOIN gl_classified_items ci ON ci.raw_item_id = ri.id
        WHERE ri.card_id = ?
        ORDER BY ri.linha_origem
    """, (card_id,))
    itens = cur.fetchall()

    cur.execute("""SELECT total_manus, total_livre, total_revisar, total_bloqueada,
                          bloqueada_cliente_ativo, bloqueada_crm_lead, bloqueada_crm_deal,
                          pct_aderencia, pct_cnpj_presente, pct_contato_presente, saturacao_alerta
                   FROM gl_evaluations WHERE card_id = ?""", (card_id,))
    avaliacao = cur.fetchone()
    conn.close()
    return {"card": card, "briefing": briefing, "prompt": prompt_row, "itens": itens, "avaliacao": avaliacao}


def obter_card(card_id: int) -> dict | None:
    dados = _carregar_card(card_id)
    if not dados:
        return None

    _, titulo, created_by, created_at, status = dados["card"]

    briefing = None
    if dados["briefing"]:
        segmento, aplicacao, regiao, porte, look_alike, observacoes = dados["briefing"]
        # NOTA: gl_briefings so tem estas 6 colunas - quantidade/profundidade_pesquisa/
        # tipo_empresa/segmento_canonico sao coletados pelo agente no chat mas nunca
        # foram persistidos em coluna propria. Ficam None aqui ao reabrir um card ja
        # finalizado (gap conhecido).
        briefing = {
            "segmento": segmento, "segmento_canonico": None, "aplicacao": aplicacao,
            "quantidade": None, "profundidade_pesquisa": None, "tipo_empresa": None,
            "regiao": regiao, "porte": porte, "look_alike": look_alike, "observacoes": observacoes,
        }

    prompt_texto = exclusion_count = truncado = None
    if dados["prompt"]:
        prompt_texto, exclusion_count, truncado = dados["prompt"]

    itens = [
        {
            "nome": it[0], "cidade": it[1], "uf": it[2], "cnpj": it[3], "site": it[4],
            "telefone": it[5], "email": it[6], "marca": it[7], "classe": it[8], "motivo": it[9],
            "fonte_bloqueio": it[10], "match_ref_nome": it[11], "match_score": it[12], "responsavel": it[13],
        }
        for it in dados["itens"]
    ]

    avaliacao = None
    if dados["avaliacao"]:
        (total_manus, total_livre, total_revisar, total_bloqueada,
         bloq_cliente, bloq_lead, bloq_deal, pct_aderencia, pct_cnpj, pct_contato, saturacao) = dados["avaliacao"]
        avaliacao = {
            "total_manus": total_manus, "total_livre": total_livre, "total_revisar": total_revisar,
            "total_bloqueada": total_bloqueada, "bloqueada_cliente_ativo": bloq_cliente,
            "bloqueada_crm_lead": bloq_lead, "bloqueada_crm_deal": bloq_deal,
            "pct_aderencia": pct_aderencia, "pct_cnpj_presente": pct_cnpj,
            "pct_contato_presente": pct_contato, "saturacao_alerta": bool(saturacao),
        }

    return {
        "id": card_id, "titulo": titulo, "created_by": created_by,
        "created_at": created_at.isoformat() if created_at else None,
        "status": status, "segmento": briefing["segmento"] if briefing else None,
        "total_manus": avaliacao["total_manus"] if avaliacao else None,
        "total_livre": avaliacao["total_livre"] if avaliacao else None,
        "total_revisar": avaliacao["total_revisar"] if avaliacao else None,
        "total_bloqueada": avaliacao["total_bloqueada"] if avaliacao else None,
        "briefing": briefing, "prompt_texto": prompt_texto,
        "exclusion_count": exclusion_count, "truncado": truncado,
        "itens": itens, "avaliacao": avaliacao,
    }


def criar_card_validacao(titulo: str | None, created_by: str | None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO gl_cards (created_by, status, titulo) OUTPUT INSERTED.id VALUES (?, ?, ?)",
        (created_by, "AGUARDANDO_UPLOAD", titulo or "Lista para validacao"),
    )
    card_id = cur.fetchone()[0]
    conn.close()
    return card_id


def excluir_card(card_id: int) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM gl_classified_items WHERE card_id = ?", (card_id,))
    cur.execute("DELETE FROM gl_raw_items WHERE card_id = ?", (card_id,))
    cur.execute("DELETE FROM gl_evaluations WHERE card_id = ?", (card_id,))
    cur.execute("DELETE FROM gl_manus_prompts WHERE card_id = ?", (card_id,))
    cur.execute("DELETE FROM gl_briefings WHERE card_id = ?", (card_id,))
    cur.execute("DELETE FROM gl_cards WHERE id = ?", (card_id,))
    conn.close()


def obter_card_dono(card_id: int) -> str | None:
    """So o created_by, pra checagem de permissao sem carregar o card inteiro."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT created_by FROM gl_cards WHERE id = ?", (card_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Classificacao
# ---------------------------------------------------------------------------

def _classificar_e_salvar(card_id: int, itens_brutos: list[dict]) -> list[dict]:
    """Classifica cada item bruto contra a base interna e persiste raw_item +
    classified_item. Retorna os itens com o veredito embutido."""
    lookup, token_freq = _get_lookup_e_freq()

    conn = get_conn()
    cur = conn.cursor()
    classificados = []
    for item in itens_brutos:
        cur.execute(
            """INSERT INTO gl_raw_items (card_id, linha_origem, nome_original, cnpj_original, cidade, uf, site, telefone, email, marca)
               OUTPUT INSERTED.id VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (card_id, item.get("linha_origem"), item.get("nome"), item.get("cnpj"),
             item.get("cidade"), item.get("uf"), item.get("site"), item.get("telefone"), item.get("email"),
             item.get("marca")),
        )
        raw_id = cur.fetchone()[0]

        resultado = classify_company(item.get("nome", ""), item.get("cnpj"), lookup, token_freq)
        cur.execute(
            """INSERT INTO gl_classified_items
               (card_id, raw_item_id, nome_normalizado, classe, motivo, fonte_bloqueio, match_score, match_ref_tipo, match_ref_id, match_ref_nome, responsavel)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (card_id, raw_id, None, resultado.classe, resultado.motivo, resultado.fonte_bloqueio,
             resultado.match_score, resultado.match_ref_tipo, resultado.match_ref_id, resultado.match_ref_nome,
             resultado.responsavel),
        )
        classificados.append({**item, "classe": resultado.classe, "motivo": resultado.motivo,
                               "fonte_bloqueio": resultado.fonte_bloqueio, "match_ref_nome": resultado.match_ref_nome,
                               "match_score": resultado.match_score, "responsavel": resultado.responsavel})
    conn.close()
    return classificados


def _salvar_avaliacao(card_id: int, avaliacao: dict) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO gl_evaluations
           (card_id, total_manus, total_livre, total_revisar, total_bloqueada,
            bloqueada_cliente_ativo, bloqueada_crm_lead, bloqueada_crm_deal,
            pct_aderencia, pct_cnpj_presente, pct_contato_presente, saturacao_alerta)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (card_id, avaliacao["total_manus"], avaliacao["total_livre"], avaliacao["total_revisar"],
         avaliacao["total_bloqueada"], avaliacao["bloqueada_cliente_ativo"], avaliacao["bloqueada_crm_lead"],
         avaliacao["bloqueada_crm_deal"], avaliacao["pct_aderencia"], avaliacao["pct_cnpj_presente"],
         avaliacao["pct_contato_presente"], avaliacao["saturacao_alerta"]),
    )
    cur.execute("UPDATE gl_cards SET status = 'LISTA_CLASSIFICADA' WHERE id = ?", (card_id,))
    conn.close()


def _item_classificado_json(it: dict) -> dict:
    return {
        "nome": it.get("nome"), "cidade": it.get("cidade"), "uf": it.get("uf"),
        "cnpj": it.get("cnpj"), "site": it.get("site"), "telefone": it.get("telefone"),
        "email": it.get("email"), "marca": it.get("marca"), "classe": it.get("classe"), "motivo": it.get("motivo"),
        "fonte_bloqueio": it.get("fonte_bloqueio"), "match_ref_nome": it.get("match_ref_nome"),
        "match_score": it.get("match_score"), "responsavel": it.get("responsavel"),
    }


def _avaliacao_json(av: dict) -> dict:
    return {
        "total_manus": av["total_manus"], "total_livre": av["total_livre"],
        "total_revisar": av["total_revisar"], "total_bloqueada": av["total_bloqueada"],
        "bloqueada_cliente_ativo": av["bloqueada_cliente_ativo"],
        "bloqueada_crm_lead": av["bloqueada_crm_lead"], "bloqueada_crm_deal": av["bloqueada_crm_deal"],
        "pct_aderencia": av["pct_aderencia"], "pct_cnpj_presente": av["pct_cnpj_presente"],
        "pct_contato_presente": av["pct_contato_presente"], "saturacao_alerta": bool(av["saturacao_alerta"]),
    }


def classificar(card_id: int, arquivo_base64: str | None, texto_colado: str | None) -> dict:
    if arquivo_base64:
        conteudo = base64.b64decode(arquivo_base64)
        itens_brutos = parse_upload_xlsx(conteudo)
    else:
        itens_brutos = parse_pasted_text(texto_colado or "")

    classificados = _classificar_e_salvar(card_id, itens_brutos)
    avaliacao = compute_evaluation(classificados)
    _salvar_avaliacao(card_id, avaliacao)

    return {
        "itens": [_item_classificado_json(it) for it in classificados],
        "avaliacao": _avaliacao_json(avaliacao),
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def exportar_excel(card_id: int) -> dict | None:
    dados = _carregar_card(card_id)
    if not dados or not dados["avaliacao"]:
        return None

    itens_classificados = [
        {"nome": it[0], "cidade": it[1], "uf": it[2], "cnpj": it[3], "site": it[4], "telefone": it[5], "email": it[6],
         "marca": it[7], "classe": it[8], "motivo": it[9], "fonte_bloqueio": it[10], "match_ref_nome": it[11],
         "match_score": it[12], "responsavel": it[13]}
        for it in dados["itens"]
    ]
    avaliacao_row = dados["avaliacao"]
    (total_manus, total_livre, total_revisar, total_bloqueada,
     bloq_cliente, bloq_lead, bloq_deal, pct_aderencia, pct_cnpj, pct_contato, saturacao) = avaliacao_row
    avaliacao = {
        "total_manus": total_manus, "total_livre": total_livre, "total_revisar": total_revisar,
        "total_bloqueada": total_bloqueada, "bloqueada_cliente_ativo": bloq_cliente,
        "bloqueada_crm_lead": bloq_lead, "bloqueada_crm_deal": bloq_deal,
        "pct_aderencia": pct_aderencia, "taxa_aproveitamento": (total_livre / total_manus if total_manus else 0),
        "pct_cnpj_presente": pct_cnpj, "pct_contato_presente": pct_contato, "saturacao_alerta": bool(saturacao),
    }
    wb = build_workbook(itens_classificados, avaliacao)
    buf = io.BytesIO()
    wb.save(buf)
    conteudo_base64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return {"nome_arquivo": f"lista_prospeccao_card{card_id}.xlsx", "conteudo_base64": conteudo_base64}


# ---------------------------------------------------------------------------
# Busca avulsa
# ---------------------------------------------------------------------------

def buscar_empresa(nome: str, cnpj: str | None) -> dict:
    lookup, token_freq = _get_lookup_e_freq()
    veredito = classify_company(nome, cnpj or None, lookup, token_freq)
    candidatos = find_top_candidates(nome, cnpj or None, lookup)
    return {
        "veredito": {
            "classe": veredito.classe, "motivo": veredito.motivo,
            "fonte_bloqueio": veredito.fonte_bloqueio, "match_ref_nome": veredito.match_ref_nome,
            "match_score": veredito.match_score, "responsavel": veredito.responsavel,
        },
        "candidatos": [
            {
                "nome_original": c.nome_original, "fonte": c.fonte, "score": c.score,
                "cnpj_bate": c.cnpj_bate, "responsavel": c.responsavel,
            }
            for c in candidatos
        ],
    }
