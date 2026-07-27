# Spec de integração — Placar Funil Comercial (BACKEND)

Fonte da verdade: `funil-scorecard/app.py` (protótipo Python/FastAPI já validado com o usuário
ao longo de várias semanas de iteração). Este documento traduz a lógica de negócio pra quem vai
portar pra `qg-polpa-brasil/server/src/db.ts` + `routers.ts` (tRPC, Node/mssql). Não é um resumo —
cada número aqui já foi conferido contra o Bitrix24 e contra os KPIs de produção do próprio QG.

## Acesso

`adminProcedure` — só admin, por decisão explícita do usuário (não é `protectedProcedure`).

## Fontes de dados

Tabelas já existentes no SQL Server (banco `PolpaBrasil`), nenhuma tabela nova precisa ser criada
pro placar em si (só, opcionalmente, uma pra guardar overrides de diagnóstico — ver seção final):

- `crm_deals` — negócios do Bitrix24 (sync já roda via `Polpa Brasil IA/sync_mssql.py`)
- `crm_leads` — leads (usado só pra Jane, hoje fora do placar)
- `crm_deal_stage_history` — histórico de mudança de etapa
- `crm_activities` — atividades (follow-up)
- `crm_users` — nome dos vendedores
- `fato_vendas` — faturamento (VIEW sobre a tabela `B2B`)
- `metas_2026` — meta oficial por vendedor/mês/projeto (cadastrada no admin do QG)

## Regras de negócio fundamentais

**Funil Comercial** = `crm_deals.category_id = '0' OR category_id IS NULL`. Os pipelines Marca
Própria(31)/Inovação(15)/Mercado Público(23)/Internacional(25) ficam sempre de fora.

**Vendedoras do placar** (hoje 4 — Jane Araujo, BDR, está deliberadamente fora, ver nota no fim):
```
Julia Alberti         -> crm_users.id = 151
Talia Stefani Scain    -> crm_users.id = 289
Jennifer Anacleto      -> crm_users.id = 365
Tatiana Evangelista    -> crm_users.id = 397
```
Filtro sempre por `crm_deals.assigned_by_id`.

**Fuso horário**: datas no Bitrix (e portanto em `crm_deals`/`crm_activities`/`crm_deal_stage_history`)
vêm gravadas no fuso do portal (+03:00), não no fuso do Brasil (-03:00, fixo, sem horário de verão
desde 2019). Qualquer agrupamento por dia/semana/mês precisa converter antes:
```sql
CAST(SWITCHOFFSET(CONVERT(datetimeoffset(0), <coluna>), '-03:00') AS date)
```
Isso já mudou um resultado real uma vez (um "ganho" que sumia ao corrigir o fuso) — não pular essa
conversão.

**Filtro de cod_top** (usado em `fato_vendas`, idêntico ao já usado em `db.ts`/`getKpisGlobais`):
```sql
(cod_top IS NULL OR cod_top <> 1023) AND ([top] IS NULL OR [top] NOT LIKE '%ESTOQUE MINIM%')
```

---

## Seção 1 — Resultado (meta x realizado, ano e trimestre atual)

**Meta**: `SELECT SUM(valor_meta) FROM metas_2026` (ano inteiro, sem filtro de mês, pra meta anual).
Pro trimestre: `SUM(valor_meta) FROM metas_2026 WHERE mes IN ('YYYY-MM', 'YYYY-MM', 'YYYY-MM')` —
os 3 meses do trimestre corrente (trimestre de calendário: Jan-Mar/Abr-Jun/Jul-Set/Out-Dez, nunca
cruza o ano). **Não usar `orcamento_2026`** — os totais anuais das duas tabelas coincidem por
coincidência, mas divergem por trimestre (granularidade diferente).

**Realizado**: mesmo eixo de data do KPI "Faturamento" de produção (`getKpisGlobais`/`buildWhere`
em `db.ts`, que usa `dt_entrega_cliente`, não `dt_prev_entrega_embarque`), mas restrito a
`tipo_receita IN ('VENDA_FIRME', 'FORECAST', 'DEVOLUCAO')` — Devolução entra pra deduzir retornos
do total (mesma lógica que `buildWhere` já aplica quando VENDA_FIRME é filtrado), Novo Projeto
fica de fora.
```sql
SELECT SUM(valor_pendente) FROM fato_vendas
WHERE YEAR(dt_entrega_cliente) = @ano AND tipo_receita IN ('VENDA_FIRME','FORECAST','DEVOLUCAO')
  AND <filtro cod_top>
```
Mesma query com `dt_entrega_cliente >= @inicioTrimestre AND dt_entrega_cliente < @fimTrimestre`
pro trimestre.

**% atingido** = realizado ÷ meta × 100.

**Cor do % atingido**: verde ≥100%, amarelo 85-99%, vermelho <85%.

---

## Seção 2 — Cadência (a máquina está girando?)

### Os 4 recortes de tempo (mais um auxiliar)

Só a Cadência muda por recorte — Saúde e Ação são sempre "foto de agora", calculadas uma vez só.

```
hoje = data atual
segunda_desta_semana = hoje - (hoje.diaDaSemana em ISO, 0=segunda)

semana_atual     = [segunda_desta_semana, segunda_desta_semana + 7 dias)   -- SEM semáforo, só acompanhamento
semana_anterior  = [segunda_desta_semana - 7 dias, segunda_desta_semana)   -- fechada, foco da reunião de segunda
semana_retrasada = [segunda_desta_semana - 14 dias, segunda_desta_semana - 7 dias)  -- só referência (regra de ganhos)

mes_atual_inicio = primeiro dia do mês corrente
mes_atual        = [mes_atual_inicio, primeiro dia do mês seguinte)
mes_anterior     = [primeiro dia do mês anterior, mes_atual_inicio)
```

Comparação lado a lado: `semana_anterior` mostra `semana_retrasada` ao lado; `mes_atual` mostra
`mes_anterior` ao lado (e vice-versa quando `mes_anterior` é o recorte primário).

### Por vendedora (loop nas 4), para um intervalo [start, end):

```sql
-- Abertos
SELECT COUNT(*) FROM crm_deals d
WHERE d.assigned_by_id=@uid AND <Funil Comercial>
  AND <fuso>(d.date_create) >= @start AND <fuso>(d.date_create) < @end

-- Ganhos
SELECT COUNT(*) FROM crm_deals d
WHERE d.assigned_by_id=@uid AND <Funil Comercial>
  AND d.stage_semantic_id='S'
  AND <fuso>(d.closedate) >= @start AND <fuso>(d.closedate) < @end

-- Perdidos (inclui "Vale a pena ver de novo" -- ver nota abaixo)
SELECT COUNT(*) FROM crm_deals d
WHERE d.assigned_by_id=@uid AND <Funil Comercial>
  AND d.stage_id IN ('LOSE','3','8')
  AND <fuso>(d.closedate) >= @start AND <fuso>(d.closedate) < @end

-- Avançaram (usa historico de mudanca de etapa + LAG por posicao no funil)
WITH hist AS (
    SELECT h.deal_id, h.created_time, <SORT_CASE>(h.stage_id) sort_atual,
           LAG(<SORT_CASE>(h.stage_id)) OVER (PARTITION BY h.deal_id ORDER BY h.created_time) sort_anterior
    FROM crm_deal_stage_history h JOIN crm_deals d ON d.id=h.deal_id
    WHERE d.assigned_by_id=@uid AND <Funil Comercial>
)
SELECT COUNT(DISTINCT deal_id) FROM hist
WHERE <fuso>(created_time) >= @start AND <fuso>(created_time) < @end
  AND sort_anterior IS NOT NULL AND sort_atual > sort_anterior
```

`SORT_CASE` (posição de cada etapa no funil, usada só pra saber se um negócio "avançou"):
```sql
CASE stage_id
    WHEN 'UC_IJG2LW' THEN 10   -- Qualificação
    WHEN 'NEW'       THEN 20   -- Proposta e Amostra
    WHEN 'UC_RWSOLQ' THEN 45   -- (legado) Teste Exploratório no Cliente
    WHEN 'UC_XFS4CF' THEN 50   -- Avaliação no Cliente
    WHEN 'UC_1VRZTH' THEN 60   -- Homologação
    WHEN '7'         THEN 70   -- Teste Industrial/Mercado
    WHEN 'UC_M8BBII' THEN 85   -- (legado) Negociação
    WHEN '1'         THEN 90   -- Efetivando venda
    WHEN 'WON'       THEN 100  -- Ganho Fechado
    WHEN 'LOSE'      THEN 110  -- Perda Fechada
    WHEN '3'         THEN 120  -- Negócios sem viabilidade
    WHEN '8'         THEN 130  -- Vale a pena ver de novo
    ELSE NULL
END
```
`UC_RWSOLQ`/`UC_M8BBII` são etapas legadas/desativadas no Bitrix mas ainda têm negócios reais
parados nelas — os valores 45/85 são estimativas posicionais (não vêm do Bitrix), escolhidas pelo
nome da etapa (ficam entre as vizinhas equivalentes).

**Nota importante sobre Perdidos**: `stage_id='8'` ("Vale a pena ver de novo") foi reclassificado
de "congelado" para **perda real** por decisão explícita do usuário — antes era uma categoria à
parte, hoje conta como perda tanto na Cadência quanto na taxa de perda. `UC_PNH69S` ("Estagnado")
é a única categoria que continua fora de tudo (não é perda, não é ativo — ver Seção 3).

`saldo = abertos - (ganhos + perdidos)`.

### Réguas de semáforo (cores)

**Abertos**:
- Semana: verde ≥5, amarelo 3-4, vermelho <3
- Mês: verde ≥22, amarelo 15-21, vermelho <15

**Ganhos**:
- Semana: verde ≥1; se 0, olha a *semana retrasada* — se ela teve ≥1 ganho, amarelo; se também foi 0, vermelho (regra de "2 semanas seguidas zeradas")
- Mês: verde ≥5, amarelo 3-4, vermelho <3

**Saldo**:
- Semana: verde se >0, amarelo se =0, vermelho se <0
- Mês: verde ≥+5, amarelo entre +1 e +4, vermelho ≤0

**Taxa de perda** = `perdidos ÷ total_ativos_agora × 100` (total_ativos é o mesmo número da Seção 3,
uma foto do funil ativo AGORA, não do período — perder 20 negócios de um funil de 300 é diferente
de perder 20 de um funil de 60):
- Semana: verde <3%, amarelo 3-6%, vermelho >6%
- Mês: verde <5%, amarelo 5-12%, vermelho >12%

**Correção de coerência** (aplicar por último, depois das réguas acima): se `saldo < 0`, o
semáforo de Ganhos nunca fica verde — no máximo amarelo (um ganho isolado no meio de muita perda
não é vitória).

**`semana_atual` nunca tem semáforo** — é a semana em andamento, julgar ela seria injusto (regra
literal do usuário: "resolve de vez o bug da segunda-feira"). Mostrar os 4 números crus, sem cor.

---

## Seção 3 — Saúde (o que está travado — sempre "agora", não muda por recorte)

### Negócios ativos + contexto (uma única query, reaproveitada pra Saúde e Ação)

```sql
WITH entrada_fase AS (
    -- Data em que o negocio entrou na etapa em que esta agora (a mais recente
    -- transicao registrada para aquele stage_id especifico)
    SELECT h.deal_id, MAX(h.created_time) entrada
    FROM crm_deal_stage_history h JOIN crm_deals d ON d.id=h.deal_id AND d.stage_id=h.stage_id
    GROUP BY h.deal_id
), followup AS (
    -- CRM_TODO sempre tem prazo real. CRM_TASKS_TASK conta so quando NAO concluida
    -- e o prazo NAO e o sentinela 9999-12-31 (que CRM_BIZPROC_WORKFLOW e parte do
    -- CRM_TASKS_TASK usam pra "sem prazo definido" -- nao e agendamento de verdade,
    -- e contar isso infla a metrica quase pra 100% dos negocios trivialmente).
    SELECT DISTINCT owner_id FROM crm_activities
    WHERE owner_type_id=2  -- 2 = Deal no Bitrix
      AND deadline NOT LIKE '9999%'
      AND (provider_id='CRM_TODO' OR (provider_id='CRM_TASKS_TASK' AND completed=0))
      AND <fuso>(deadline) >= <fuso>(agora)
)
SELECT d.id, d.title, d.assigned_by_id, d.stage_id, <FASE_CASE>(d.stage_id) fase,
       d.opportunity, COALESCE(ef.entrada, d.date_create) entrada_fase,
       CASE WHEN f.owner_id IS NULL THEN 0 ELSE 1 END tem_followup
FROM crm_deals d
LEFT JOIN entrada_fase ef ON ef.deal_id=d.id
LEFT JOIN followup f ON f.owner_id=d.id
WHERE <Funil Comercial> AND d.stage_semantic_id='P' AND d.stage_id NOT IN ('8','UC_PNH69S')
```

`FASE_CASE` (agrupa os stage_id do Bitrix nos 5 "buckets" de fase usados pro SLA):
```sql
CASE stage_id
    WHEN 'UC_IJG2LW' THEN 'Qualificacao'
    WHEN 'NEW'       THEN 'Proposta e Amostra'
    WHEN 'UC_XFS4CF' THEN 'Avaliacao no Cliente'
    WHEN 'UC_RWSOLQ' THEN 'Avaliacao no Cliente'       -- legado, fundido por nome
    WHEN 'UC_1VRZTH' THEN 'Homologacao e Teste Industrial'
    WHEN '7'         THEN 'Homologacao e Teste Industrial'
    WHEN '1'         THEN 'Fechamento'
    WHEN 'UC_M8BBII' THEN 'Fechamento'                  -- legado, fundido por nome
    ELSE 'SEM_MAPEAMENTO'
END
```

Depois, em código (não em SQL): pra cada negócio, `dias_na_fase = hoje - entrada_fase` (já
convertido pro fuso do Brasil). `perfil = 'B' se opportunity >= 150000 senão 'A'` — **opportunity
nunca é somado como faturamento em lugar nenhum, serve só pra escolher o SLA**. `sla =
SLA_TABELA[fase][perfil]`. `fora_do_sla = sla != null AND dias_na_fase > sla`.

**Tabela de SLA por fase (dias)**:
| Fase | Perfil A (opportunity < 150 mil) | Perfil B (≥ 150 mil) |
|---|---|---|
| Qualificação | 10 | 15 |
| Proposta e Amostra | 20 | 20 |
| Avaliação no Cliente | 60 | 90 |
| Homologação e Teste Industrial | 60 | 120 |
| Fechamento | 10 | 15 |

### Agregação por vendedora

```
para cada vendedora:
  ativos = COUNT(negocios ativos dela)
  fora_sla = COUNT(negocios ativos dela onde fora_do_sla=true)
  sem_followup = COUNT(negocios ativos dela onde tem_followup=false)
  pct_sla = 100 * fora_sla / ativos   (null se ativos=0, exibir "—")
  pct_fu  = 100 * sem_followup / ativos
```
Um 5º grupo "Outros (fora do placar)" soma quem não é uma das 4 vendedoras — existe pra o total
bater e o coordenador ver o que sobra fora do placar, mas fica separado.

**Estagnado**: `SELECT COUNT(*) FROM crm_deals WHERE <Funil Comercial> AND stage_id='UC_PNH69S'`
— exibido sozinho, nunca somado a nada.

**Cores de % fora do SLA / % sem follow-up** (mesma régua nos 2 casos, mesma régua em qualquer
recorte de tempo — isso é sempre uma foto de agora):
- % fora do SLA: verde <30%, amarelo 30-50%, vermelho >50%
- % sem follow-up: verde <30%, amarelo 30-60%, vermelho >60%

---

## Seção 4 — Ação (lista de prioridade)

Reaproveita a MESMA lista de "ativos com contexto" da Seção 3. Filtra: `assigned_by_id` numa das
4 vendedoras do placar (negócio de quem está fora do placar não entra — vira "mutirão do
coordenador", não reunião de cadência) **e** `fora_do_sla=true` **e** `tem_followup=false`.
Ordena por `dias_na_fase` decrescente (o mais parado primeiro). Limita a ~20 linhas.

---

## Veredito (frase de topo, sintetizada a partir dos semáforos)

`semana_atual` sempre retorna uma frase neutra de acompanhamento (sem julgamento):
> "Acompanhamento da semana em andamento (sem veredito de cobrança): X abertos, Y ganhos,
> Z perdidos, saldo ±W até agora."

Pros outros 3 recortes, calcular a saúde agregada do time inteiro (`pct_sla`/`pct_fu` sobre o
total de negócios ativos, não por vendedora) e aplicar em ordem de prioridade (a primeira regra
que bater, usa):

1. **Cadência toda verde (abertos+ganhos+saldo) E saúde tem algo vermelho** → "Motor de entrada
   girando bem ({abertos} abertos, {ganhos} ganhos, saldo {saldo:+d}) — mas o problema não é o
   topo do funil, é o meio: {pct_sla}% fora do SLA e {pct_fu}% sem follow-up agendado."
2. **Saldo vermelho E taxa de perda amarela ou vermelha** → "A máquina gira devagar e vaza:
   {perdidos} perdidos (taxa de {taxa_perda}% do funil ativo) contra {ganhos} ganhos (saldo
   {saldo:+d}) — o problema principal é a saída, não a entrada ({abertos} abertos)." + se
   %follow-up não for verde, acrescenta: " O funil ativo também carrega {pct_fu}% sem follow-up,
   o que agrava o risco."
3. **Abertos vermelho** → "Geração de negócios fraca ({abertos} abertos) — saldo {saldo:+d}.
   Se não reagir, o funil começa a secar."
4. **Ganhos vermelho** → "Conversão fraca: só {ganhos} ganho(s) — poucos negócios fechando
   apesar do funil girar."
5. **Cadência toda verde E saúde toda verde** → "Tudo girando bem: cadência no alvo e funil
   saudável. Manter o ritmo."
6. **Cadência toda vermelha E saúde tem vermelho** → "Situação crítica: entrada fraca e funil
   travado ao mesmo tempo — atenção total."
7. Fallback → "Sinais mistos: sem crise clara, mas vale atenção pontual nos itens
   amarelos/vermelhos."

---

## Diagnóstico automático por vendedora (regras, em ordem de prioridade)

Usa a cadência do recorte selecionado (não é fixo) + a saúde agregada (sempre "agora").
`semana_atual` não gera diagnóstico (mesma lógica do veredito: julgamento é injusto ainda).

1. **Em rampa**: `ativos < 5` → "Em rampa: só {ativos} negócio(s) ativo(s) — ainda não dá pra
   avaliar performance, depende do processo trazer mais volume." *(limiar `<5` é uma escolha
   arbitrária minha, não veio de número exato do usuário — ok pra ajustar)*
2. **Afogada e sem follow-up**: `pct_fu >= 80% E fora_sla >= 3` → "Afogada e sem follow-up: {N}
   negócios fora do SLA e {pct_fu}% sem próximo passo agendado. Prioridade da reunião."
   *(o limiar `fora_sla >= 3` pra "vários" também foi escolha minha)*
3. **Volume alto, conversão baixa**: `perdidos > ganhos E avancaram >= 5` →
   - se `perdidos >= 10`: "Volume alto e conversão baixa: movimenta muito ({avancaram} avanços,
     {abertos} aberturas) mas perdeu {perdidos} contra só {ganhos} ganho(s). Foco em fechar, não
     em abrir mais."
   - senão (mais leve): "Padrão de conversão baixa, mas leve: perde um pouco mais do que ganha
     ({perdidos}×{ganhos}) com bom volume de avanços ({avancaram}). Vale atenção, sem urgência."
4. **Saudável mas estreita**: `ganhos >= 1 E ganhos >= perdidos E pct_fu < 30% E abertos <= 1` →
   "Saudável — converte bem e follow-up em dia — mas abre pouco ({abertos}). Precisa de mais
   largura pra não secar."
5. Fallback → "Sem sinal de alerta claro nas regras padrão — números equilibrados."

**Mecanismo de override manual**: o coordenador pode substituir qualquer diagnóstico por um texto
escrito à mão (o protótipo Python usa um arquivo `diagnosticos_overrides.json`, chave por recorte
+ nome da vendedora). Na versão de produção, isso provavelmente deveria virar uma tabelinha no SQL
Server (ex.: `crm_diagnostico_overrides(recorte, vendedor, texto, updated_at, updated_by)`) editável
via uma pequena UI — decisão de vocês, mas o comportamento esperado é: se existe override pro
(recorte, vendedora) atual, usa ele e marca visualmente como editado (✎); senão, usa o texto
automático das regras acima.

---

## Contrato de dados sugerido (o que o tRPC deveria devolver)

```typescript
interface FunilScorecardResponse {
  resultado: {
    ano: number
    metaAno: number; realizadoAno: number; pctAno: number
    trimestreLabel: string  // ex: "T3/2026 (jul-set)"
    metaTri: number; realizadoTri: number; pctTri: number
  }
  cadencia: {
    // uma entrada por recorte -- o front decide qual mostrar
    [recorte in 'semana_atual'|'semana_anterior'|'semana_retrasada'|'mes_atual'|'mes_anterior']: {
      label: string  // ex: "13/07 a 19/07"
      vendedores: { nome: string; abertos: number; ganhos: number; perdidos: number; avancaram: number; saldo: number }[]
      totais: { abertos: number; ganhos: number; perdidos: number; avancaram: number; saldo: number }
    }
  }
  luzes: null | {  // null quando recorte selecionado = semana_atual
    abertos: 'verde'|'amarelo'|'vermelho'
    ganhos: 'verde'|'amarelo'|'vermelho'
    saldo: 'verde'|'amarelo'|'vermelho'
    perdidos: 'verde'|'amarelo'|'vermelho'
    taxaPerda: number
  }
  veredito: string
  saude: {
    porVendedor: { nome: string; ativos: number; foraSla: number; semFollowup: number; pctSla: number|null; pctFu: number|null; diagnostico: string|null; diagnosticoEditado: boolean }[]
    totalAtivos: number; totalForaSla: number; totalSemFollowup: number
    pctSlaAgregado: number; pctFuAgregado: number
    estagnado: number
  }
  acao: {
    titulo: string; vendedor: string; fase: string; dias: number; sla: number
  }[]
  acaoTotal: number
}
```

## Notas finais

- **Jane Araujo (BDR)** está fora do placar por decisão explícita do usuário ("quando trouxermos
  leads eu vou colocar ela") — a lógica dela (medida por `crm_leads`, não `crm_deals`: leads
  criados, qualificados via `status_id IN ('UC_7F7HKU','CONVERTED')`, convertidos via
  `status_semantic_id='S'`) está documentada no protótipo Python (`app.py`, funções com "jane" no
  nome) pronta pra reativar quando pedirem.
- Todos os números aqui já foram validados contra o Bitrix24 ao vivo e contra os KPIs reais de
  produção (`getKpisGlobais`, `getOrcamentoKpis`) em múltiplas rodadas de conferência com o
  usuário — não são só uma leitura de código, foram testados numericamente.
