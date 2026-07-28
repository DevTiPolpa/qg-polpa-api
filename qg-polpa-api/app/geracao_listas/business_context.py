"""
business_context.py — Contexto de negócio da Polpa Brasil para o agente de briefing.
Edite este arquivo para atualizar o conhecimento do agente sem mexer na lógica.
"""

BUSINESS_CONTEXT = """
## CONTEXTO DA EMPRESA

**Polpa Brasil** — fornecedora B2B de ingredientes alimentícios (frutas e vegetais desidratados).

Clientes: indústrias de alimentos e distribuidores/atacadistas.
Ciclo de venda: longo (mais de 6 meses do primeiro contato ao fechamento).
Negócio "ganho" (WON): quando o cliente realiza o primeiro pedido.
Valor de opportunity: estimativa do faturamento anual com aquele cliente (não valor de um pedido único).
Ticket médio funil Comercial: R$ 50 mil a R$ 200 mil/ano.

Volume mínimo de compra: varia por SKU, entre 100 kg e 1.200 kg por pedido. Clientes que não atingem o volume mínimo são motivo de perda (etapa 3 — "Negócios sem viabilidade").

Portfólio: frutas e vegetais desidratados. Frutas e vegetais têm desempenho comercial distinto — taxa de conversão e ticket médio diferem entre as categorias. Ao analisar por produto, separe frutas de vegetais.

Time comercial: 4 a 8 vendedores com carteiras fixas de clientes. Cada vendedor é responsável por uma lista de contas — ao analisar performance, compare os vendedores entre si e identifique desvios.

Origens de leads: prospecção ativa (cold outreach) e marketing digital/inbound. Ao analisar source_id, esses são os canais esperados.

Qualificação de leads: existe critério formal — volume mínimo + fit técnico. Nem todo lead vira deal; a conversão de lead para deal é criteriosa.

---

## FUNIS DE VENDA

### Funil Comercial (category_id = '0' ou NULL) — PRINCIPAL
B2B doméstico. Prioridade máxima nas análises.

Etapas em ordem:
1. NEW            → "Proposta / Envio da amostra"      — entrada no funil, amostra enviada ao cliente
2. UC_RWSOLQ      → "Teste Exploratório no Cliente"    — ⚠️ PRINCIPAL GARGALO do funil
3. UC_XFS4CF      → "Aplicação no Cliente"             — cliente aplica o produto em sua produção
4. UC_1VRZTH      → "Homologação"                      — aprovação técnica e regulatória
5. 7              → "Teste Industrial/Mercado"          — validação em escala industrial
6. 1              → "Efetivando venda"                  — negociação comercial final
7. WON            → "Ganho Fechado"                    — primeiro pedido realizado ✓
8. LOSE           → "Perda Fechada"                    — negócio perdido ✗
9. 3              → "Negócios sem viabilidade"         — cliente não atinge volume mínimo ✗
10. 8             → "Vale a pena ver denovo"            — pausado para retomar futuramente

Principais motivos de perda:
- Cliente some sem dar retorno (ghosting)
- Cliente não consegue comprar o volume mínimo exigido pela Polpa Brasil

### Funil Mercado Público (Merendô) — ANALISAR SEPARADO
Marca Merendô. Licitações públicas para merenda escolar (prefeituras, secretarias de educação).
Ciclo ditado pelo calendário de editais — longo e regulatório.
Alto volume de produto, margem menor que o Comercial.
Etapas: orientadas ao processo licitatório (apresentação nutricional → edital → contrato → pedido).

### Funil Marca Própria - Private Label — ANALISAR
Clientes que querem os produtos com sua própria marca.
Processo similar ao Comercial mas com etapas de desenvolvimento de embalagem/formulação.

### Funil Internacional — IGNORAR NAS ANÁLISES
Exportações. Não incluir em análises gerais.

### Funil Projetos Inovação — IGNORAR NAS ANÁLISES
P&D interno. Não incluir em análises comerciais.

---

## KPIs PRIORITÁRIOS

1. **Taxa de conversão por etapa** — % de negócios que avançam de cada etapa para a próxima
2. **Tempo médio por etapa** — dias que um negócio fica em cada fase (foco em UC_RWSOLQ)
3. **Performance por responsável** — volume de deals, valor total e taxa de ganho por vendedor
4. **Origem dos leads** — quais fontes (source_id) geram mais negócios ganhos

---

## ATIVIDADES NOS NEGÓCIOS

O campo `last_activity_time` em `deals` é atualizado pelo Bitrix24 automaticamente sempre que qualquer atividade ocorre no negócio: e-mail, ligação, reunião, tarefa, comentário, etc.

**REGRA ABSOLUTA — NUNCA VIOLE:**
- Qualquer pergunta sobre "negócios sem atividade", "sem follow-up", "sem tarefa", "parados", "sem contato" → use EXCLUSIVAMENTE `last_activity_time` da tabela `deals`
- **JAMAIS use a tabela `tasks` para isso** — ela contém apenas tarefas abertas recentes e não representa o histórico completo de atividades
- A tabela `tasks` só deve ser usada para perguntas específicas sobre tarefas (ex: "qual o título da tarefa X", "quem criou a tarefa Y")

---

## RELAÇÃO LEADS → DEALS

Leads são qualificados manualmente pelos vendedores.
Quando aprovado, o vendedor converte o lead em negócio (deal).
O campo lead_id em deals indica de qual lead o negócio originou.
Nem todo lead vira deal — a qualificação é criteriosa.

---

## ORIENTAÇÕES PARA ANÁLISES

- Ao analisar o funil sem especificação, foque no **Comercial**
- Ao falar em "ganho", sempre considerar stage_semantic_id = 'S' (WON)
- Ao falar em "perdido", considerar stage_semantic_id = 'F' (LOSE, 3, 8)
- Ao falar em "em andamento", considerar stage_semantic_id = 'P'
- O gargalo histórico é a etapa UC_RWSOLQ — sempre destaque quando relevante
- Oportunidade = valor anual potencial, não valor de transação pontual
- Ciclo longo significa que negócios com mais de 6 meses em andamento são normais
- Negócios com mais de 12 meses parados numa etapa merecem destaque como estagnados

### Alertas de follow-up
Negócio sem atividade há mais de **15 dias** = sinal de alerta (follow-up atrasado).
Negócio sem atividade há mais de **30 dias** = crítico.
Negócio sem atividade há mais de **60 dias** = estagnado, risco alto de perda.
"""
