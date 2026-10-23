# Backend do Teleprompter

API FastAPI com WebSocket para sincronizar telas do operador e do apresentador e persistir as sessões, roteiros, matérias, páginas e preferências.

## Requisitos

- Python 3.10+
- PostgreSQL 16+ (recomendado para uso compartilhado) ou SQLite local para desenvolvimento
- Docker Compose apenas para subir o PostgreSQL incluído

## Desenvolvimento com PostgreSQL

No diretório deste projeto:

```bash
cp .env.example .env
# Altere POSTGRES_PASSWORD e mantenha DATABASE_URL com a mesma senha.
docker compose up -d postgres
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

No Windows PowerShell, ative o ambiente com `.venv\Scripts\Activate.ps1`. Para rodar rapidamente sem PostgreSQL, não crie o arquivo `.env`: o backend usa `teleprompter.db` (SQLite) no diretório de execução.

O backend cria as tabelas ao iniciar. Configure `DATABASE_URL` para outro endereço PostgreSQL em produção; codifique caracteres especiais da senha conforme URL encoding. Proteja o arquivo `.env` e não reutilize as credenciais de desenvolvimento em produção.

## API e WebSocket

- Saúde e conexão ao banco: `GET http://localhost:8000/api/health`
- Documentação interativa: `http://localhost:8000/docs`
- Estado persistido: `GET /api/sessions/{session_id}/state`
- Atualizar estado: `POST /api/sessions/{session_id}/state`, corpo `{"state": {...}}`
- Importar espelho: `POST /api/sessions/{session_id}/rundown`, corpo `{"stories": [...]}`. Valida o roteiro, preserva a ordem e os campos editoriais, persiste matérias/páginas e transmite a atualização aos clientes conectados.
- WebSocket: `ws://localhost:8000/ws/{session_id}`

Na conexão WebSocket o cliente recebe `welcome` com o último estado persistido. Mensagens `sync` salvam e distribuem o estado. Comandos executáveis:

```json
{"type":"command","command":"pause"}
{"type":"command","command":"resume"}
{"type":"command","command":"next"}
{"type":"command","command":"previous"}
{"type":"command","command":"select_story","selectedStory":1}
{"type":"command","command":"select_page","pageIndex":0}
{"type":"command","command":"take_control"}
```

O formato dos roteiros e páginas pode ser visto em `../Residencia-Globo-Front/src/data/stories.json`. Preferências da leitura (fonte, cores e contraste), tamanho do texto, velocidade e estado operacional também são salvos por sessão.

## Testes

```bash
python -m pytest
```

Os testes cobrem saúde do banco, importação e persistência do espelho e comandos WebSocket.

## Operação em computadores diferentes

1. Inicie o PostgreSQL e o backend no computador servidor com `--host 0.0.0.0`.
2. Permita a porta 8000 na rede confiável e configure no front `VITE_API_URL=http://IP-DO-SERVIDOR:8000`.
3. Se a origem do front não for localhost, inclua-a em `CORS_ORIGINS` no `.env` do backend e reinicie o servidor.
4. Execute o front com `npm run dev -- --host 0.0.0.0`.
5. Abra o front nos dois computadores usando o mesmo parâmetro de sessão, por exemplo `http://IP-DO-FRONT:5173/?session=estudio-a`.

Os clientes conectados ao mesmo processo do backend recebem comandos e atualizações em tempo real; o PostgreSQL preserva os dados após reinicializações. Para produção, use HTTPS/WSS, autenticação, credenciais seguras, backup e proxy reverso. A lista de conexões WebSocket é mantida no processo; execute uma única instância do backend enquanto não houver um broker pub/sub distribuído.

## iNEWS: estado e dependências

Não existe integração direta configurada neste projeto. O backend aceita importação JSON no modelo atual, mas não autentica nem se conecta a um servidor iNEWS. Não há endpoint, versão do produto, método de autenticação, documentação da instalação ou credenciais fornecidas para implementar e testar esse conector. A compatibilidade de exportação e os metadados disponíveis precisam ser confirmados com o administrador iNEWS/Avid da redação; não se deve enviar credenciais para a interface demonstrativa.
