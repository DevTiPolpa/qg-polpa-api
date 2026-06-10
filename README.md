# README Técnico — Backend / API QG Polpa Brasil

**Projeto:** QG Polpa Brasil  
**Camada:** Backend / API  
**Tecnologia principal recomendada:** Python API  
**Banco de dados:** SQL Server  
**Integração:** Frontend React, CRM/Bitrix, relatórios e rotinas analíticas

---

## Resumo técnico

Este documento descreve a estrutura técnica recomendada para o **backend/API do QG Polpa Brasil**. A API é a camada responsável por conectar o frontend aos dados do projeto, centralizando regras de negócio, autenticação, consultas ao **SQL Server**, integrações externas e entrega de indicadores comerciais.

A API deve ser mantida como serviço independente do frontend, permitindo que as telas React consumam dados por endpoints documentados. Essa separação facilita manutenção, testes, deploy, reaproveitamento em novos projetos e expansão futura para integrações com CRM, automações ou agentes de consulta.[1] [2]

---

## Stack técnica

| Área | Tecnologia | Finalidade |
|---|---|---|
| **API** | Python com FastAPI | Criação de endpoints REST, validação de dados e documentação automática. |
| **Servidor ASGI** | Uvicorn | Execução local e inicialização da aplicação Python. |
| **Banco de dados** | SQL Server | Fonte principal dos dados comerciais, clientes, vendedores, produtos, metas e histórico. |
| **Driver SQL** | pyodbc ou pymssql | Comunicação entre Python e SQL Server. |
| **Validação** | Pydantic | Validação de payloads, parâmetros e respostas da API. |
| **Autenticação** | JWT, cookie seguro ou sessão controlada | Controle de login, permissões e acesso por perfil. |
| **Versionamento** | GitHub | Controle de código, branches, pull requests e histórico técnico. |
| **Túnel local** | ngrok | Exposição temporária da API local para testes externos. |
| **Hospedagem** | VPS, serviço cloud ou runtime compatível com Python | Publicação da API em ambiente permanente. |

---

## Responsabilidades do backend

O backend deve concentrar todas as regras sensíveis do projeto. O frontend não deve consultar o banco diretamente nem reproduzir regras de cálculo críticas.

| Responsabilidade | Descrição |
|---|---|
| **Conexão com SQL Server** | Abrir conexões controladas, executar consultas e retornar dados estruturados. |
| **Endpoints analíticos** | Disponibilizar indicadores de dashboard, vendedores, clientes, produtos, funil e metas. |
| **Autenticação** | Validar login, controlar sessão e aplicar permissões por perfil. |
| **Regras de negócio** | Centralizar cálculos de faturamento, recorrência, orçamento, metas, forecast e funil. |
| **Integração CRM/Bitrix** | Sincronizar ou consultar dados comerciais externos quando aplicável. |
| **Tratamento de erro** | Retornar mensagens padronizadas e códigos HTTP corretos. |
| **Logs técnicos** | Registrar falhas, consultas críticas e comportamento de produção. |
| **Documentação de API** | Manter documentação técnica dos endpoints e parâmetros. |

---

## Estrutura recomendada de diretórios

A estrutura abaixo organiza a API Python de forma clara, separando rotas, serviços, banco, schemas, autenticação e configurações.

```text
backend/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── auth.py
│   ├── dependencies.py
│   ├── routers/
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── dashboard.py
│   │   ├── vendedores.py
│   │   ├── clientes.py
│   │   ├── produtos.py
│   │   ├── metas.py
│   │   ├── funil_vendas.py
│   │   ├── novos_projetos.py
│   │   ├── recorrentes.py
│   │   └── panorama_crm.py
│   ├── services/
│   │   ├── dashboard_service.py
│   │   ├── vendedores_service.py
│   │   ├── clientes_service.py
│   │   ├── produtos_service.py
│   │   ├── crm_service.py
│   │   └── metas_service.py
│   ├── schemas/
│   │   ├── auth_schema.py
│   │   ├── filtros_schema.py
│   │   ├── dashboard_schema.py
│   │   └── usuario_schema.py
│   └── utils/
│       ├── dates.py
│       ├── formatters.py
│       └── errors.py
├── scripts/
│   ├── seed_admin.py
│   └── validar_conexao_sqlserver.py
├── tests/
│   ├── test_health.py
│   └── test_auth.py
├── requirements.txt
├── .env.example
└── README.md
```

---

## Endpoints principais recomendados

A tabela abaixo apresenta uma organização sugerida para os endpoints da API. Os nomes podem ser ajustados conforme o padrão adotado no projeto, mas é importante manter agrupamento por domínio funcional.

| Grupo | Endpoint | Método | Finalidade |
|---|---|---:|---|
| **Saúde** | `/health` | GET | Verificar se a API está online. |
| **Autenticação** | `/api/auth/login` | POST | Autenticar usuário e iniciar sessão. |
| **Autenticação** | `/api/auth/me` | GET | Retornar usuário logado. |
| **Autenticação** | `/api/auth/logout` | POST | Encerrar sessão. |
| **Usuários** | `/api/users` | GET | Listar usuários cadastrados. |
| **Usuários** | `/api/users` | POST | Criar novo usuário. |
| **Usuários** | `/api/users/{id}` | PATCH | Atualizar dados de usuário. |
| **Usuários** | `/api/users/{id}/reset-password` | POST | Redefinir senha temporária. |
| **Dashboard** | `/api/dashboard/kpis` | GET | Retornar indicadores globais. |
| **Dashboard** | `/api/dashboard/evolucao-mensal` | GET | Retornar evolução mensal. |
| **Vendedores** | `/api/vendedores/performance` | GET | Retornar desempenho por vendedor. |
| **Clientes** | `/api/clientes/lista` | GET | Listar clientes conforme filtros. |
| **Clientes** | `/api/clientes/{cod_parc}/historico` | GET | Consultar histórico de cliente. |
| **Produtos** | `/api/produtos/performance` | GET | Retornar performance de produtos. |
| **Metas** | `/api/metas` | GET | Listar metas cadastradas. |
| **Metas** | `/api/metas` | POST | Criar ou atualizar meta. |
| **Funil** | `/api/funil/kpis` | GET | Retornar indicadores do funil de vendas. |
| **Novos projetos** | `/api/novos-projetos/kpis` | GET | Retornar indicadores de novos projetos. |
| **Recorrentes** | `/api/recorrentes/kpis` | GET | Retornar visão de recorrência real x orçado. |
| **Panorama CRM** | `/api/panorama-crm/leads` | GET | Retornar visão de leads do CRM. |
| **Panorama CRM** | `/api/panorama-crm/deals` | GET | Retornar visão de negócios e pipeline. |

---

## Variáveis de ambiente do backend

O backend deve utilizar variáveis de ambiente para evitar credenciais fixas no código. O arquivo `.env` não deve ser versionado no GitHub; apenas o `.env.example` deve ser mantido no repositório.

| Variável | Exemplo | Finalidade |
|---|---|---|
| `APP_ENV` | `local` | Define ambiente de execução. |
| `APP_NAME` | `QG Polpa Brasil API` | Nome da aplicação. |
| `PORT` | `5000` | Porta usada pela API. |
| `DB_SERVER` | `localhost` | Servidor SQL Server. |
| `DB_DATABASE` | `polpa_brasil` | Nome do banco de dados. |
| `DB_USER` | `sa` | Usuário de conexão com SQL Server. |
| `DB_PASSWORD` | `********` | Senha do usuário de banco. |
| `DB_PORT` | `1433` | Porta padrão do SQL Server. |
| `DB_ENCRYPT` | `false` | Define uso de criptografia na conexão. |
| `JWT_SECRET` | `trocar_por_chave_segura` | Chave para assinatura de token, se JWT for usado. |
| `COOKIE_SECRET` | `trocar_por_string_segura` | Chave para sessão/cookie, se cookies forem usados. |
| `CORS_ORIGIN` | `http://localhost:5173` | Origem permitida para o frontend local. |
| `BITRIX_BASE_URL` | `https://empresa.bitrix24.com.br` | URL base do Bitrix, quando houver integração. |
| `BITRIX_WEBHOOK` | `********` | Webhook de integração com Bitrix, quando aplicável. |

Exemplo de `.env.example`:

```env
APP_ENV=local
APP_NAME=QG Polpa Brasil API
PORT=5000

DB_SERVER=localhost
DB_DATABASE=polpa_brasil
DB_USER=sa
DB_PASSWORD=SuaSenhaSQLServer
DB_PORT=1433
DB_ENCRYPT=false

JWT_SECRET=troque_por_uma_chave_longa_e_segura
COOKIE_SECRET=troque_por_uma_string_longa_e_segura
CORS_ORIGIN=http://localhost:5173

BITRIX_BASE_URL=
BITRIX_WEBHOOK=
```

---

## Instalação local

Antes de executar a API, é necessário ter Python instalado, acesso ao SQL Server e as credenciais de banco configuradas no `.env`.

```bash
git clone <url-do-repositorio>
cd qg-polpa-brasil/backend
python -m venv .venv
```

Ativar o ambiente virtual no Linux ou macOS:

```bash
source .venv/bin/activate
```

Ativar o ambiente virtual no Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Instalar dependências:

```bash
pip install -r requirements.txt
```

Executar a API localmente:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

Após iniciar, validar a API em:

```text
http://localhost:5000/health
```

---

## Dependências recomendadas

O arquivo `requirements.txt` deve conter as bibliotecas necessárias para execução da API.

```txt
fastapi
uvicorn[standard]
pydantic
pydantic-settings
python-dotenv
pyodbc
python-jose[cryptography]
passlib[bcrypt]
httpx
pandas
openpyxl
```

A lista pode ser ajustada conforme a implementação real. Caso o projeto utilize `pymssql` no lugar de `pyodbc`, manter apenas o driver efetivamente usado.

---

## Configuração de conexão com SQL Server

A conexão com SQL Server deve ficar centralizada em um único módulo, como `database.py`. Isso evita repetição de credenciais e facilita ajuste de timeout, pool e logs.

Exemplo conceitual:

```python
import os
import pyodbc


def get_connection():
    server = os.getenv("DB_SERVER")
    database = os.getenv("DB_DATABASE")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    port = os.getenv("DB_PORT", "1433")
    encrypt = os.getenv("DB_ENCRYPT", "false")

    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        f"Encrypt={encrypt};"
        "TrustServerCertificate=yes;"
    )

    return pyodbc.connect(connection_string)
```

---

## Padrão de filtros globais

Os endpoints analíticos devem aceitar filtros comuns para manter comportamento uniforme entre telas.

| Filtro | Tipo | Descrição |
|---|---|---|
| `dataInicio` | string | Data inicial do período analisado. |
| `dataFim` | string | Data final do período analisado. |
| `mercados` | lista | Mercados ou segmentos comerciais selecionados. |
| `vendedores` | lista | Vendedores selecionados. |
| `projetos` | lista | Projetos comerciais filtrados. |
| `gruposProduto` | lista | Grupos ou famílias de produto. |
| `tiposReceita` | lista | Tipo de receita ou classificação comercial. |
| `uf` | string | Unidade federativa. |
| `codParc` | número | Código do parceiro/cliente. |
| `codProduto` | número | Código do produto. |

---

## Regras de autenticação e perfis

A API deve controlar acesso por perfil. Recomenda-se pelo menos dois papéis: **ADMIN** e **VENDEDOR**.

| Perfil | Permissões recomendadas |
|---|---|
| **ADMIN** | Acesso a todas as telas, usuários, metas, indicadores globais, CRM e configurações. |
| **VENDEDOR** | Acesso limitado aos próprios dados, carteira, clientes e indicadores autorizados. |

O backend deve validar permissões em cada rota protegida. O frontend pode ocultar menus, mas a segurança real precisa estar na API.

---

## Testes com ngrok

O ngrok pode ser usado para expor a API local temporariamente para validações externas, integração com frontend publicado ou testes em ambientes onde o backend ainda não possui hospedagem definitiva.[3]

Executar API local:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 5000 --reload
```

Expor porta local:

```bash
ngrok http 5000
```

Após gerar a URL pública, configurar o frontend para apontar para essa URL:

```env
VITE_API_URL=https://url-gerada.ngrok-free.app
```

Quando usar ngrok, o frontend pode precisar enviar header adicional para evitar tela intermediária de aviso:

```ts
headers: {
  "ngrok-skip-browser-warning": "true"
}
```

---

## Deploy do backend

O backend Python deve ser publicado em ambiente que suporte execução persistente de aplicações Python. A Vercel é adequada para frontend estático, mas a API Python com conexão SQL Server normalmente deve rodar em infraestrutura com processo persistente, acesso controlado à rede e variáveis de ambiente seguras.

| Opção | Uso recomendado |
|---|---|
| **VPS Linux** | Maior controle sobre Python, driver ODBC, rede e SQL Server. |
| **Cloud Run / App Service / Render / Railway** | Deploy gerenciado com variáveis de ambiente e logs. |
| **Servidor interno** | Quando o SQL Server está em rede privada e exige acesso local. |
| **Docker** | Padronização de runtime, dependências e driver SQL. |

O deploy deve conter pelo menos as seguintes etapas: instalação de dependências, configuração de variáveis, validação da conexão SQL Server, execução do serviço, configuração de domínio e ativação de logs.

---

## Fluxo de versionamento no GitHub

| Etapa | Padrão recomendado |
|---|---|
| **Branch principal** | Manter apenas código validado em `main` ou `master`. |
| **Branch de desenvolvimento** | Criar branches como `feature/api-dashboard`, `fix/auth-login` ou `feature/panorama-crm`. |
| **Pull request** | Usar PR para registrar alteração, revisar impacto técnico e manter histórico. |
| **Validação** | Executar testes, validar `/health`, login e endpoints principais antes do merge. |
| **CI/CD** | Automatizar lint, testes e deploy quando possível. |

---

## Checklist de validação da API

| Item | Critério de validação |
|---|---|
| **Inicialização** | API sobe sem erro no ambiente configurado. |
| **Health check** | `/health` retorna status positivo. |
| **Banco de dados** | Conexão com SQL Server funciona com usuário configurado. |
| **Autenticação** | Login, sessão e logout funcionam corretamente. |
| **Permissões** | Rotas administrativas bloqueiam usuários sem permissão. |
| **Dashboard** | KPIs retornam valores coerentes com o banco. |
| **Filtros** | Filtros globais alteram corretamente o resultado. |
| **CRM/Bitrix** | Integrações externas retornam resposta válida ou erro tratado. |
| **Logs** | Falhas são registradas com contexto técnico suficiente. |
| **CORS** | Frontend autorizado consegue consumir a API. |
| **Produção** | Variáveis de ambiente estão configuradas sem credenciais no código. |

---

## Padrões de resposta da API

As respostas devem ser previsíveis para facilitar consumo pelo frontend.

Exemplo de sucesso:

```json
{
  "status": "ok",
  "data": {
    "faturamentoTotal": 1000000,
    "clientesAtivos": 120,
    "volumeTotal": 35000
  }
}
```

Exemplo de erro:

```json
{
  "status": "error",
  "message": "Não foi possível consultar os indicadores do dashboard.",
  "detail": "Erro controlado registrado no log técnico."
}
```

---

## Boas práticas técnicas

A API deve priorizar consultas otimizadas, paginação quando houver listas grandes, uso de parâmetros em consultas SQL, padronização de erros e separação entre rota, serviço e banco. Consultas complexas devem ficar documentadas, especialmente quando forem usadas em indicadores executivos.

Credenciais, webhooks e chaves de integração não devem ser enviadas ao GitHub. Toda configuração sensível deve ficar em variáveis de ambiente no servidor de produção.

---

## Documentação que deve acompanhar o backend

| Documento | Conteúdo recomendado |
|---|---|
| **README técnico** | Instalação, execução, variáveis, endpoints e deploy. |
| **`.env.example`** | Lista de variáveis sem valores sensíveis. |
| **Mapa de endpoints** | Grupo, rota, método, parâmetros e resposta esperada. |
| **Mapa de tabelas** | Principais tabelas SQL usadas por cada domínio. |
| **Guia de deploy** | Como publicar, configurar variáveis e validar produção. |
| **Guia de troubleshooting** | Erros comuns de banco, CORS, login e conexão. |

---

## Referências

[1]: https://fastapi.tiangolo.com/ "FastAPI — Official Documentation"  
[2]: https://learn.microsoft.com/en-us/sql/sql-server/ "Microsoft SQL Server Documentation"  
[3]: https://ngrok.com/docs "ngrok — Documentation"  
[4]: https://docs.github.com/actions "GitHub Actions Documentation"
