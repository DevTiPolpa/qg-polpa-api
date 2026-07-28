"""
evaluation.py - Calcula os numeros de avaliacao de uma lista classificada.
"""

from app.geracao_listas.export_excel import SATURATION_THRESHOLD


def compute_evaluation(itens_classificados: list[dict]) -> dict:
    total = len(itens_classificados)
    livres = [i for i in itens_classificados if i["classe"] == "LIVRE"]
    revisar = [i for i in itens_classificados if i["classe"] == "REVISAR"]
    bloqueadas = [i for i in itens_classificados if i["classe"] == "BLOQUEADA"]

    def _sem_nome_valido(i):
        return not (i.get("nome") or "").strip()

    invalidas = sum(1 for i in itens_classificados if _sem_nome_valido(i))
    com_cnpj = sum(1 for i in itens_classificados if (i.get("cnpj") or "").strip())
    com_contato = sum(
        1 for i in itens_classificados
        if (i.get("site") or "").strip() or (i.get("telefone") or "").strip() or (i.get("email") or "").strip()
    )

    pct_aderencia = (total - invalidas) / total if total else 0.0
    taxa_aproveitamento = len(livres) / total if total else 0.0
    pct_cnpj_presente = com_cnpj / total if total else 0.0
    pct_contato_presente = com_contato / total if total else 0.0
    saturacao = (len(revisar) + len(bloqueadas)) / total if total else 0.0

    return {
        "total_manus": total,
        "total_livre": len(livres),
        "total_revisar": len(revisar),
        "total_bloqueada": len(bloqueadas),
        "bloqueada_cliente_ativo": sum(1 for i in bloqueadas if i.get("fonte_bloqueio") == "FATO_VENDAS"),
        "bloqueada_crm_lead": sum(1 for i in bloqueadas if i.get("fonte_bloqueio") == "CRM_LEAD"),
        "bloqueada_crm_deal": sum(1 for i in bloqueadas if i.get("fonte_bloqueio") == "CRM_DEAL"),
        "pct_aderencia": pct_aderencia,
        "taxa_aproveitamento": taxa_aproveitamento,
        "pct_cnpj_presente": pct_cnpj_presente,
        "pct_contato_presente": pct_contato_presente,
        "saturacao_alerta": saturacao > SATURATION_THRESHOLD,
    }
