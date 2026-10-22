# Backend do Teleprompter

Backend em Python com FastAPI e WebSocket para sincronizar o estado entre operador e apresentador.

## Requisitos
Python 3.10 ou superior.

## Instalar e executar

Linux/macOS:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Windows PowerShell:
```powershell
py -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

- Saúde: http://localhost:8000/api/health
- Documentação da API: http://localhost:8000/docs
- WebSocket: `ws://localhost:8000/ws/{session_id}`

## Configuração CORS
A variável `CORS_ORIGINS` aceita origens separadas por vírgula. Exemplo:
`CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`

## Mensagens WebSocket
Ao conectar, o cliente recebe `welcome` com o estado atual da sessão.
Envie `{"type":"sync","clientId":"operator-01","state":{...}}` para atualizar o estado.
Para comandos, envie `{"type":"command","command":"next","clientId":"operator-01","state":{...}}`.
Comandos permitidos: `pause`, `resume`, `next`, `previous`, `select_story`, `select_page`, `take_control`.
`{"type":"ping"}` responde com `{"type":"pong"}`.

## Testar em dois computadores
1. Execute o backend no computador servidor usando `--host 0.0.0.0`.
2. Descubra o IP local do servidor.
3. Configure o frontend para apontar para esse IP, não para `localhost`.
4. Verifique a mesma rede e as regras do firewall para a porta 8000.
5. Use o mesmo `session_id` nas duas interfaces.

## Limitações
O estado fica em memória e é perdido ao reiniciar. Só é compartilhado entre clientes conectados a este processo. Para produção, implemente autenticação, HTTPS/WSS e armazenamento compartilhado (por exemplo, Redis) para múltiplas instâncias. Integração com iNEWS, áudio e IA não estão incluídos.
