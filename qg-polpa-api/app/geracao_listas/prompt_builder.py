"""
prompt_builder.py - Monta o prompt de busca para a Manus a partir do briefing.

Template deterministico, NAO passa pelo LLM: a lista de exclusao e a parte critica e
auditavel do prompt, nao pode ser parafraseada/alterada por um modelo de linguagem.
"""

from app.geracao_listas.exclusion_queries import build_prompt_exclusion_list
from app.geracao_listas.company_pitch import COMPANY_PITCH

EXCLUSION_LIMIT = 60
QUANTIDADE_PADRAO = "30 a 50"  # usado so se o briefing nao trouxer quantidade (fallback defensivo)

_TEXTO_PROFUNDIDADE = {
    "profunda": (
        "Pesquisa APROFUNDADA: só inclua na lista empresas que você consiga confirmar "
        "que realmente utilizam frutas ou vegetais desidratados em seus produtos "
        "(verifique página de produtos/ingredientes, ficha técnica, embalagem ou outra "
        "fonte pública antes de incluir). Se não conseguir confirmar o uso do "
        "ingrediente, NÃO inclua a empresa, mesmo que ela seja do segmento certo."
    ),
    "ampla": (
        "Pesquisa ABRANGENTE: pode incluir qualquer empresa do segmento informado, "
        "mesmo sem confirmar o uso específico de frutas/vegetais desidratados - a "
        "triagem fina desse detalhe será feita depois, internamente."
    ),
}

_TEXTO_TIPO_EMPRESA = {
    "somente_matriz": (
        "Traga apenas a MATRIZ de cada grupo empresarial - não liste filiais/unidades "
        "da mesma empresa separadamente."
    ),
    "matriz_e_filiais": (
        "Pode incluir filiais/unidades além da matriz, quando forem relevantes, "
        "indicando a cidade/UF de cada uma separadamente."
    ),
}


def build_manus_prompt(briefing: dict) -> tuple[str, int, bool]:
    """Retorna (prompt_texto, quantidade_excluida, truncado)."""
    nomes, truncado = build_prompt_exclusion_list(
        briefing.get("segmento", ""), briefing.get("segmento_canonico"), limit=EXCLUSION_LIMIT
    )

    criterios = [
        f"1. Segmento/indústria: {briefing.get('segmento', '')}",
        f"2. Aplicação do ingrediente: {briefing.get('aplicacao', '')}",
    ]
    n = 3
    if briefing.get("regiao"):
        criterios.append(f"{n}. Região/estado: {briefing['regiao']}")
        n += 1
    if briefing.get("porte"):
        criterios.append(f"{n}. Porte da empresa: {briefing['porte']}")
        n += 1

    look_alike_bloco = ""
    if briefing.get("look_alike"):
        look_alike_bloco = f"""
Empresas de referência (look-alike): {briefing['look_alike']}.
Pesquise o perfil de mercado dessas empresas de referência (porte, canais de venda,
tipo de produto/linha, posicionamento) e priorize encontrar OUTRAS empresas com
perfil semelhante - não é necessário que o nome ou produto seja idêntico, o que
importa é o perfil de negócio parecido.
"""

    observacoes_bloco = f"\nObservações adicionais: {briefing['observacoes']}\n" if briefing.get("observacoes") else ""

    if nomes:
        exclusion_block = "\n".join(f"- {n}" for n in nomes)
        aviso_truncado = (
            f"\n(Lista limitada às {EXCLUSION_LIMIT} mais relevantes para este segmento - "
            "já existem mais empresas conhecidas além destas, mas a lista precisa caber neste prompt.)"
            if truncado else ""
        )
    else:
        exclusion_block = "(nenhuma empresa conhecida a excluir neste segmento até o momento)"
        aviso_truncado = ""

    quantidade = briefing.get("quantidade") or QUANTIDADE_PADRAO
    texto_profundidade = _TEXTO_PROFUNDIDADE.get(briefing.get("profundidade_pesquisa"), _TEXTO_PROFUNDIDADE["ampla"])
    texto_tipo_empresa = _TEXTO_TIPO_EMPRESA.get(briefing.get("tipo_empresa"), _TEXTO_TIPO_EMPRESA["matriz_e_filiais"])

    prompt = f"""{COMPANY_PITCH}

Preciso de uma lista de EMPRESAS (potenciais clientes B2B, não consumidores finais)
para prospecção comercial, segundo os critérios abaixo:

{chr(10).join(criterios)}
{look_alike_bloco}{observacoes_bloco}
Traga {quantidade} empresas. Priorize fabricantes/indústrias reais (não marketplaces,
diretórios genéricos ou páginas de associações) - use sites oficiais das empresas,
LinkedIn, associações do setor e notícias de mercado como fontes.

{texto_profundidade}

{texto_tipo_empresa}

IMPORTANTE - formato de entrega: gere e disponibilize o resultado em um arquivo de
planilha Excel (.xlsx) para download, com uma linha por empresa e EXATAMENTE estas
8 colunas, cada uma em sua própria coluna (não junte campos na mesma célula/coluna):

Razão Social | CNPJ | Cidade | UF | Site | Telefone | Email | Marca(s)

A coluna "Razão Social" deve trazer APENAS a razão social/nome legal da empresa (o
nome que aparece no CNPJ/contrato social) - não inclua marca, nome fantasia ou
qualquer informação entre parênteses nessa coluna. Se a empresa tiver marca(s)
comercial(is) diferente(s) da razão social, liste na coluna "Marca(s)" (separadas
por vírgula se houver mais de uma); se a marca for igual à razão social ou não for
identificável, deixe "Marca(s)" em branco.

Cidade e UF são colunas SEPARADAS (ex.: "Sales Oliveira" numa coluna e "SP" na
coluna ao lado - não "Sales Oliveira/SP" numa coluna só). Telefone e Email também
são colunas separadas, cada uma com um campo só. Use exatamente esses nomes de
coluna no cabeçalho da planilha. Se não for possível gerar o arquivo .xlsx, retorne
os dados em uma tabela com essas mesmas 8 colunas separadas, que dá para copiar e
colar.

IMPORTANTE - NÃO incluir na lista as empresas abaixo, porque já são clientes ativos
da Polpa Brasil ou já estão em prospecção/negociação:
{exclusion_block}{aviso_truncado}
"""
    return prompt, len(nomes), truncado
