"""
agent_briefing.py - Agente Claude que conduz o briefing de prospeccao por chat.
Mesmo formato de tool-use loop do chatbot de analise (ver main.py), mas em vez de
rodar SQL, a tool "submit_briefing" so captura as respostas estruturadas quando o
agente decidir que tem informacao suficiente (no minimo segmento + aplicacao).
"""

import os
import anthropic
from dotenv import load_dotenv

from app.geracao_listas.briefing_config import BRIEFING_QUESTIONS
from app.geracao_listas.exclusion_queries import SEGMENT_CONFIG
from app.geracao_listas.business_context import BUSINESS_CONTEXT

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = "claude-haiku-4-5-20251001"

_PERGUNTAS_TEXTO = "\n".join(
    f"- {q['key']} ({'obrigatorio' if q['required'] else 'opcional'}): {q['label']} "
    f"[ex.: {q['exemplo']}]"
    for q in BRIEFING_QUESTIONS
)

_SEGMENTOS_CONHECIDOS = sorted(SEGMENT_CONFIG.keys())
_SEGMENTOS_TEXTO = "\n".join(f"- {s}" for s in _SEGMENTOS_CONHECIDOS)

_SYSTEM_TEXT = f"""Voce e um assistente que ajuda vendedoras da Polpa Brasil a montar o
briefing de uma nova lista de prospeccao, antes de gerar um prompt de busca para a
ferramenta Manus.

Converse de forma natural, uma pergunta de cada vez, ate reunir as respostas abaixo.
Segmento, aplicacao, quantidade de empresas, profundidade da pesquisa e matriz/filial
sao obrigatorios - NUNCA finalize o briefing sem perguntar cada um desses. Regiao,
porte e look-alike sao opcionais - se a vendedora nao souber ou nao quiser informar,
siga em frente sem insistir.

Perguntas a cobrir:
{_PERGUNTAS_TEXTO}

Assim que tiver os campos obrigatorios (e as demais informacoes que a vendedora
quiser dar), chame a tool submit_briefing com o que foi coletado. Nao pergunte de
novo depois de chamar a tool. Responda sempre em portugues, de forma curta e direta.

IMPORTANTE - classificacao de segmento: alem do campo "segmento" (a descricao livre
que a vendedora deu, ex.: "Pet Food"), preencha tambem "segmento_canonico" com a
opcao MAIS PARECIDA da lista abaixo (copie o texto exatamente como esta na lista).
Essa classificacao alimenta a busca de empresas a excluir do prompt - se voce nao
mapear certo, o prompt final fica sem essa lista de exclusao. Se nenhuma opcao for
minimamente parecida, deixe segmento_canonico como null.

Segmentos conhecidos (copie exatamente um destes em segmento_canonico, ou null):
{_SEGMENTOS_TEXTO}

IMPORTANTE - classificacao de profundidade e matriz/filial: a resposta da vendedora
sobre pesquisa profunda vai ser livre (ex.: "pode ser mais tranquilo", "quero
certeza"), mas voce deve classificar em "profundidade_pesquisa" usando EXATAMENTE
um destes dois valores: "profunda" ou "ampla". Da mesma forma, classifique
"tipo_empresa" usando EXATAMENTE um destes dois valores: "somente_matriz" ou
"matriz_e_filiais".

Contexto de negocio da Polpa Brasil, para entender os segmentos/aplicacoes citados:

{BUSINESS_CONTEXT}
"""

SYSTEM_PROMPT = [
    {"type": "text", "text": _SYSTEM_TEXT, "cache_control": {"type": "ephemeral"}}
]

SUBMIT_BRIEFING_TOOL = {
    "name": "submit_briefing",
    "description": (
        "Registra as respostas estruturadas do briefing assim que houver informacao "
        "suficiente (no minimo segmento, aplicacao, quantidade, profundidade_pesquisa "
        "e tipo_empresa)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "segmento": {"type": "string", "description": "Descricao livre do segmento, como a vendedora falou."},
            "segmento_canonico": {
                "type": ["string", "null"],
                "enum": _SEGMENTOS_CONHECIDOS + [None],
                "description": "Segmento da lista conhecida mais parecido com 'segmento', ou null.",
            },
            "aplicacao": {"type": "string"},
            "quantidade": {
                "type": "string",
                "description": "Quantidade de empresas que a vendedora quer que a Manus traga (ex.: '20', '50', 'umas 100').",
            },
            "profundidade_pesquisa": {
                "type": "string",
                "enum": ["profunda", "ampla"],
                "description": (
                    "'profunda' = so incluir empresas que comprovadamente usam frutas/vegetais "
                    "desidratados; 'ampla' = qualquer empresa do segmento, sem confirmar o ingrediente."
                ),
            },
            "tipo_empresa": {
                "type": "string",
                "enum": ["somente_matriz", "matriz_e_filiais"],
                "description": "'somente_matriz' = so a matriz de cada grupo; 'matriz_e_filiais' = pode incluir filiais.",
            },
            "regiao": {"type": ["string", "null"]},
            "porte": {"type": ["string", "null"]},
            "look_alike": {"type": ["string", "null"]},
            "observacoes": {"type": ["string", "null"]},
        },
        "required": ["segmento", "aplicacao", "quantidade", "profundidade_pesquisa", "tipo_empresa"],
    },
}

TOOLS = [SUBMIT_BRIEFING_TOOL]


def run_briefing_agent(user_message: str, history: list[dict]) -> tuple[str, list[dict], dict | None]:
    """Retorna (resposta_texto, historico_atualizado, briefing_coletado_ou_None)."""
    messages = history + [{"role": "user", "content": user_message}]
    briefing_coletado = None

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "submit_briefing":
                    briefing_coletado = block.input
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Briefing registrado com sucesso.",
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        text_parts = [b.text for b in response.content if hasattr(b, "text")]
        return "\n".join(text_parts), messages, briefing_coletado
