# Geração de Listas → produção no QG Polpa — Brief do Agente de Backend

Você é um dos dois agentes trabalhando nesta integração. O outro agente cuida do
frontend (React) do QG Polpa Brasil. **Vocês não conversam diretamente** — o
usuário (Ramon) relê mensagens de um lado pro outro copiando e colando. Sempre
que você precisar de algo do agente de frontend, ou quando tiver algo pronto que
ele precisa saber, escreva um bloco assim, bem no fim da sua resposta:

```
>>> MENSAGEM PARA O AGENTE DE FRONTEND >>>
(o que ele precisa saber ou decidir)
<<< FIM DA MENSAGEM <<<
```

Não trave esperando resposta. Se tiver que tomar uma decisão de contrato sozinho
pra continuar, tome a decisão mais razoável, documente no bloco de mensagem, e
sinalize que pode ser revista.

---

## Contexto

**Geração de Listas** é uma ferramenta de deduplicação de prospecção: a vendedora
descreve o que quer prospectar (segmento, aplicação, região, porte, look-alike),
o sistema monta um prompt pronto pra colar na Manus (já com uma lista de empresas
a excluir porque já são clientes ou já estão no CRM), a vendedora cola a lista que
a Manus devolveu, e o sistema classifica cada empresa em **Livre** / **Revisar** /
**Bloqueada** cruzando contra `fato_vendas` (clientes ativos) e as tabelas
`crm_*` (Bitrix sincronizado). No final gera um Excel de saída e mantém um
histórico auditável de cada lista gerada.

Ela já existe **inteira e funcionando** como um app standalone em Python/FastAPI
em `c:\DEV\Dahsboard Polpa Brasil\geracao-listas\`, rodando local na porta 5090,
lendo do mesmo SQL Server (`PolpaBrasil`) que o QG Polpa já usa. Foi construída,
testada e ajustada em cima de dados reais ao longo de várias rodadas de revisão
manual do Ramon — **a lógica de classificação já está calibrada, não reinvente**.

**Sua tarefa NÃO é reescrever essa lógica em TypeScript.** É expor o que já
existe em Python para o QG Polpa consumir via tRPC, seguindo exatamente o mesmo
padrão que o QG Polpa já usa para conversar com o outro serviço Python do
projeto ("Polpa Brasil IA", que atende o chat de IA hoje).

### Por que não reescrever em TypeScript

A lógica de classificação (normalização de nome, fuzzy matching, detecção de
termo raro, filtro de referência estrangeira, etc.) foi ajustada em várias
iterações reais — incluindo pelo menos um bug sutil de regex que só apareceu
testando contra nomes reais do banco. Reescrever em TS significa re-validar tudo
de novo com risco de reintroduzir esses mesmos bugs, além de precisar achar
equivalentes de `rapidfuzz` e `unidecode` em npm. Não vale o risco — o padrão de
"Node chama um serviço Python interno" já existe e já está em produção neste
exato projeto.

---

## Arquitetura alvo

```
Browser (React, QG Polpa)
   │  tRPC (via cookie de sessão qg_session)
   ▼
Node/Express (qg-polpa-brasil) ── protectedProcedure valida usuário
   │  fetch() com header X-Internal-Secret
   ▼
Python/FastAPI (geracao-listas, porta 5090, 127.0.0.1 apenas)
   │  toda a logica de classificacao + acesso a dados
   ▼
SQL Server (PolpaBrasil) — mesmo banco que o QG Polpa ja usa
```

Isso é **exatamente** o padrão já usado para `chat.send` → Polpa Brasil IA
(`PYTHON_API_URL` + `INTERNAL_CHAT_SECRET`, ver `server/src/routers.ts:396-419`).
Você vai fazer a mesma coisa com um novo par de variáveis de ambiente.

O Node **não acessa o SQL Server diretamente para este recurso**. Toda leitura e
escrita das tabelas `gl_*` continua dentro do serviço Python. O Node só faz
proxy + autenticação + injeta `created_by` do usuário logado.

---

## O que já existe e você NÃO deve recriar

### Tabelas no SQL Server (já criadas, migração já aplicada)

`qg-polpa-brasil/migrations/add_geracao_listas_tables.sql` já existe e já rodou
contra o banco `PolpaBrasil`: `gl_cards`, `gl_briefings`, `gl_manus_prompts`,
`gl_raw_items`, `gl_classified_items`, `gl_evaluations`. Não precisa criar nada
novo aqui. `gl_cards.status` assume: `BRIEFING`, `PROMPT_GERADO`,
`AGUARDANDO_UPLOAD` (fluxo "só validar lista", sem briefing), `LISTA_CLASSIFICADA`.

`crm_companies` também já foi estendida com `assigned_by_id` (quem é o
responsável no CRM por aquela empresa), e o sync do Bitrix
(`Polpa Brasil IA/sync_mssql.py`) já foi atualizado e rodado pra popular isso.

### Módulos Python (todos em `geracao-listas/`, todos prontos)

| Arquivo | O que faz |
|---|---|
| `normalize.py` | Normaliza nome de empresa (remove acento/pontuação/sufixo societário) e CNPJ |
| `classify.py` | `classify_company()` — classifica em LIVRE/REVISAR/BLOQUEADA; `find_top_candidates()` — busca avulsa por nome/CNPJ |
| `exclusion_queries.py` | `build_prompt_exclusion_list()` (lista curta p/ prompt, filtrada por segmento) e `build_full_internal_lookup()` (base completa p/ classificação, sem filtro) |
| `evaluation.py` | Calcula os números de avaliação de uma lista classificada |
| `export_excel.py` | Gera o `.xlsx` de saída (4 abas: Resumo/Livre/Revisar/Bloqueada) |
| `ingest.py` | Lê upload `.xlsx` ou texto colado, com fallback pra colunas combinadas |
| `prompt_builder.py` | Monta o prompt determinístico pra Manus (não usa LLM) |
| `agent_briefing.py` | Agente Claude (Haiku 4.5) que conduz o chat de briefing |
| `briefing_config.py` | Perguntas do briefing (editável) |
| `company_pitch.py` | Descrição pública da Polpa Brasil (segura pra sair da empresa) |
| `db.py` | Conexão pyodbc com o SQL Server |

**Regra de ouro do sistema (não mude o comportamento sem confirmar com o
Ramon):** bloquear uma empresa livre por engano é o pior erro. A classificação é
propositalmente assimétrica — fácil cair em Revisar, difícil cair em Bloqueada.

### App FastAPI já rodando (`geracao-listas/app.py`)

Já tem rotas HTML funcionando (histórico, chat de briefing, upload/classificação,
export, busca avulsa, exclusão de card). O seu trabalho é adicionar um conjunto
de rotas **JSON** paralelas a essas (não precisa remover as HTML — elas podem
continuar existindo como ferramenta de uso direto/debug, rodando só localmente).

Duas rotas **já retornam JSON hoje** e já servem como estão:
- `POST /api/briefing/chat` → `{resposta, history, briefing}`
- `POST /api/briefing/finalizar` → `{card_id, prompt, exclusion_count, truncado}`

---

## O trabalho deste agente

### 1. Adicionar autenticação interna ao serviço Python

Nenhuma rota do `geracao-listas/app.py` tem autenticação hoje (é um app
localhost). Antes de expor pro Node, adicione um dependency/middleware do
FastAPI que exige um header `X-Internal-Secret` em **todas as rotas `/api/*`**,
comparando com uma variável de ambiente nova (ex.: `INTERNAL_API_SECRET`) que
você vai adicionar ao `.env` da pasta `geracao-listas` (hoje ela usa o mesmo
`.env` de `Polpa Brasil IA` — pode adicionar a variável lá). Se o header não
bater, retornar 401. As rotas HTML existentes (sem `/api` prefix) continuam sem
autenticação, já que só respondem em `127.0.0.1`.

### 2. Adicionar as rotas JSON que faltam em `geracao-listas/app.py`

Todas reaproveitando as funções Python já existentes — é só trocar
`HTMLResponse`/render por um dict JSON. Lista completa:

- `GET /api/cards` → lista todos os cards (mesma query de `historico()`)
- `GET /api/cards/{id}` → detalhe completo (mesma query de `_carregar_card()`)
- `POST /api/cards` body `{titulo?, created_by}` → cria card `AGUARDANDO_UPLOAD` (mesma lógica de `nova_validar_criar()`)
- `POST /api/cards/{id}/excluir` → mesma lógica de `excluir_card()`, retorna `{ok: true}`
- `POST /api/cards/{id}/classificar` body `{arquivo_base64?, nome_arquivo?, texto_colado?}` → **atenção**: a rota HTML atual usa `UploadFile`/`Form` (multipart). A versão JSON recebe o arquivo como **base64 no corpo**, decodifica com `base64.b64decode()` e passa pro mesmo `parse_upload_xlsx()`. Mesma lógica de classificação depois.
- `GET /api/cards/{id}/export` → em vez de `StreamingResponse`, gera o workbook com `build_workbook()` igual já faz, mas retorna `{nome_arquivo, conteudo_base64}` (o `.xlsx` codificado em base64 dentro do JSON)
- `GET /api/buscar?nome=&cnpj=` → mesma lógica de `buscar()`, retorna `{veredito: {...}, candidatos: [...]}`
- Em `POST /api/briefing/finalizar`: adicionar um campo opcional `created_by` no corpo — quando vier preenchido (é o Node mandando o nome do usuário logado), usa ele; senão mantém o comportamento atual.

Padronize as chaves do JSON em `snake_case` (convenção Python) — a conversão pra
`camelCase` acontece do lado do Node, ver contrato abaixo.

### 3. Criar o router tRPC `geracaoListas` no QG Polpa

Em `qg-polpa-brasil/server/src/routers.ts`, seguindo exatamente o padrão de
`chat.send` (linhas ~396-419) pra chamar o serviço Python, adicione:

```ts
geracaoListas: router({
  listarCards: protectedProcedure.query(async () => {
    const res = await fetch(`${GL_URL}/api/cards`, { headers: internalHeaders() })
    if (!res.ok) throw new TRPCError({ code: 'INTERNAL_SERVER_ERROR', message: 'Geração de Listas indisponível' })
    return res.json()
  }),
  obterCard: protectedProcedure.input(z.object({ cardId: z.number() })).query(async ({ input }) => {
    const res = await fetch(`${GL_URL}/api/cards/${input.cardId}`, { headers: internalHeaders() })
    ...
  }),
  criarCardValidacao: protectedProcedure.input(z.object({ titulo: z.string().optional() }))
    .mutation(async ({ input, ctx }) => {
      const res = await fetch(`${GL_URL}/api/cards`, {
        method: 'POST', headers: internalHeaders(),
        body: JSON.stringify({ titulo: input.titulo, created_by: ctx.user.nome }),
      })
      ...
    }),
  chatBriefing: protectedProcedure.input(z.object({ message: z.string(), history: z.array(z.unknown()) }))
    .mutation(async ({ input }) => { /* fetch POST /api/briefing/chat */ }),
  finalizarBriefing: protectedProcedure.input(z.object({ briefing: z.record(z.unknown()), conversa: z.array(z.unknown()) }))
    .mutation(async ({ input, ctx }) => {
      // injeta created_by: ctx.user.nome no body, NAO deixa o client mandar isso
    }),
  classificarLista: protectedProcedure.input(z.object({
    cardId: z.number(),
    arquivoBase64: z.string().optional(),
    nomeArquivo: z.string().optional(),
    textoColado: z.string().optional(),
  })).mutation(async ({ input }) => { /* fetch POST /api/cards/{id}/classificar */ }),
  exportarExcel: protectedProcedure.input(z.object({ cardId: z.number() })).query(async ({ input }) => {
    // retorna { nomeArquivo, conteudoBase64 } - o client monta o Blob e dispara o download
  }),
  excluirCard: protectedProcedure.input(z.object({ cardId: z.number() })).mutation(async ({ input }) => { ... }),
  buscarEmpresa: protectedProcedure.input(z.object({ nome: z.string(), cnpj: z.string().optional() }))
    .query(async ({ input }) => { ... }),
}),
```

Onde `GL_URL = process.env.GERACAO_LISTAS_API_URL ?? 'http://localhost:5090'` e
`internalHeaders()` monta `{ 'Content-Type': 'application/json', 'X-Internal-Secret': process.env.GERACAO_LISTAS_INTERNAL_SECRET ?? '' }`.

Converta as respostas snake_case do Python pra camelCase antes de devolver pro
client (um helper pequeno de mapeamento, ou zod `.transform()`).

**Não existe rota REST de upload/download neste projeto** (confirmado — o
projeto já usa base64-dentro-de-tRPC pro upload de planilha em
`uploads.processar`, `server/src/routers.ts:553-573`, e não existe nenhum
export/download implementado ainda em lugar nenhum). Siga esse mesmo padrão:
tudo passa por tRPC como JSON com string base64 quando for binário — não crie
uma rota REST nova exceto se o agente de frontend pedir explicitamente por um
motivo técnico concreto (ex.: arquivo muito grande pro limite de 50mb do
`express.json`, o que aqui é improvável — planilhas de prospecção são pequenas).

### 4. Variáveis de ambiente novas

`qg-polpa-brasil/.env`:
```env
GERACAO_LISTAS_API_URL=http://localhost:5090
GERACAO_LISTAS_INTERNAL_SECRET=<string aleatória longa, combinar com o outro .env>
```

`geracao-listas/.env` (hoje ela usa o `.env` de `Polpa Brasil IA` — pode
adicionar a variável lá mesmo, ou criar um `.env` próprio):
```env
INTERNAL_API_SECRET=<mesma string aleatória de cima>
```

### 5. Deploy (quando for pra produção de verdade)

Igual ao padrão já documentado no `CLAUDE.md` raiz pra `Polpa Brasil IA`:

```powershell
pm2 start "app.py" --name geracao-listas --cwd "C:\DEV\Dahsboard Polpa Brasil\geracao-listas" --interpreter "C:\Users\<USER>\AppData\Local\Python\pythoncore-3.14-64\python.exe"
pm2 save
```

Mantenha o `uvicorn.run(app, host="127.0.0.1", ...)` em `geracao-listas/app.py`
— **não** exponha esse serviço publicamente, só o Node deve alcançá-lo.

---

## Contrato de API (fonte da verdade — mesmo texto está no doc do frontend)

### Tipos compartilhados (TypeScript, lado do Node/React)

```ts
type Classe = "LIVRE" | "REVISAR" | "BLOQUEADA"
type StatusCard = "BRIEFING" | "PROMPT_GERADO" | "AGUARDANDO_UPLOAD" | "LISTA_CLASSIFICADA"

type Briefing = {
  segmento: string
  segmentoCanonico: string | null
  aplicacao: string
  quantidade: string
  profundidadePesquisa: "profunda" | "ampla"
  tipoEmpresa: "somente_matriz" | "matriz_e_filiais"
  regiao: string | null
  porte: string | null
  lookAlike: string | null
  observacoes: string | null
}

type CardResumo = {
  id: number
  titulo: string | null
  createdBy: string | null
  createdAt: string        // ISO 8601
  status: StatusCard
  segmento: string | null
  totalManus: number | null
  totalLivre: number | null
  totalRevisar: number | null
  totalBloqueada: number | null
}

type ItemClassificado = {
  nome: string
  cidade: string | null
  uf: string | null
  cnpj: string | null
  site: string | null
  telefone: string | null
  email: string | null
  classe: Classe
  motivo: string
  fonteBloqueio: "FATO_VENDAS" | "CRM_LEAD" | "CRM_DEAL" | "CRM_COMPANY" | null
  matchRefNome: string | null
  matchScore: number | null
  responsavel: string | null
}

type Avaliacao = {
  totalManus: number
  totalLivre: number
  totalRevisar: number
  totalBloqueada: number
  bloqueadaClienteAtivo: number
  bloqueadaCrmLead: number
  bloqueadaCrmDeal: number
  pctAderencia: number
  pctCnpjPresente: number
  pctContatoPresente: number
  saturacaoAlerta: boolean
}

type CardDetalhado = CardResumo & {
  briefing: Briefing | null
  promptTexto: string | null
  exclusionCount: number | null
  truncado: boolean | null
  itens: ItemClassificado[]
  avaliacao: Avaliacao | null
}

type Candidato = {
  nomeOriginal: string
  fonte: "FATO_VENDAS" | "CRM_LEAD" | "CRM_DEAL" | "CRM_COMPANY"
  score: number
  cnpjBate: boolean
  responsavel: string | null
}

type Veredito = {
  classe: Classe
  motivo: string
  fonteBloqueio: string | null
  matchRefNome: string | null
  matchScore: number | null
  responsavel: string | null
}
```

### Procedures tRPC (`geracaoListas.*`, todas `protectedProcedure`)

| Procedure | Input | Output |
|---|---|---|
| `listarCards` | — | `CardResumo[]` |
| `obterCard` | `{ cardId: number }` | `CardDetalhado` |
| `criarCardValidacao` | `{ titulo?: string }` | `{ cardId: number }` |
| `chatBriefing` | `{ message: string, history: unknown[] }` | `{ resposta: string, history: unknown[], briefing: Briefing \| null }` |
| `finalizarBriefing` | `{ briefing: Briefing, conversa: unknown[] }` | `{ cardId: number, prompt: string, exclusionCount: number, truncado: boolean }` |
| `classificarLista` | `{ cardId: number, arquivoBase64?: string, nomeArquivo?: string, textoColado?: string }` | `{ itens: ItemClassificado[], avaliacao: Avaliacao }` |
| `exportarExcel` | `{ cardId: number }` | `{ nomeArquivo: string, conteudoBase64: string }` |
| `excluirCard` | `{ cardId: number }` | `{ ok: true }` |
| `buscarEmpresa` | `{ nome: string, cnpj?: string }` | `{ veredito: Veredito, candidatos: Candidato[] }` |

`created_by` **nunca** vem do client — o Node sempre injeta `ctx.user.nome` (ou
equivalente) antes de repassar pro Python, em `criarCardValidacao` e
`finalizarBriefing`.

---

## Perguntas em aberto (avisar o Ramon, não decidir sozinho)

1. **Nível de permissão de `excluirCard`**: hoje qualquer um pode excluir
   qualquer card (sem checagem de dono). Fica `protectedProcedure` genérico
   (qualquer vendedora logada apaga qualquer lista) ou deveria virar
   `adminProcedure`, ou checar se `ctx.user` é o mesmo que criou o card? Hoje
   `gl_cards.created_by` é texto livre (nome digitado), não teria uma "chave"
   confiável do usuário pra comparar sem migração adicional.
2. **Histórico é global ou por vendedora?** `listarCards` traz tudo hoje. Faz
   sentido pra um gestor auditar todo mundo, mas talvez a vendedora comum só
   devesse ver as próprias listas por padrão (com um toggle "ver todas" pra
   admin). Não decidi isso sozinho — perguntar ao Ramon.
3. **O app standalone (porta 5090, HTML) continua acessível diretamente** como
   ferramenta de backup/debug, ou deve ser desligado assim que a integração no
   QG Polpa estiver no ar? Recomendo manter rodando só internamente (não expor
   a porta) mas isso é decisão do Ramon.

---

## Como coordenar com o agente de frontend

O contrato de tRPC acima é a peça que os dois precisam concordar antes de
seguir em paralelo. Recomendo:

1. Implemente o router `geracaoListas` primeiro com todos os procedures
   retornando dados **mockados** (hardcoded) que seguem exatamente os tipos do
   contrato — isso já desbloqueia o agente de frontend pra construir a UI toda
   sem esperar você terminar a integração real com o Python.
2. Mande uma mensagem pro frontend avisando que o mock está pronto e o router
   existe (ele só precisa saber que `trpc.geracaoListas.*` já responde).
3. Depois troque o mock pela chamada real ao serviço Python, mantendo o
   mesmo formato de retorno — o frontend não deveria precisar mudar nada.
4. Se encontrar qualquer necessidade de mudar o contrato (campo faltando, tipo
   errado), pare, escreva um bloco de mensagem pro frontend explicando a
   mudança, e só ajuste depois de confirmado (ou depois de esperar uma
   resposta razoável do usuário, se o frontend já tiver avançado muito em cima
   do formato antigo).
