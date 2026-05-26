# Cyber Home Dashboard

Central local e defensiva para monitorar uma rede doméstica, o notebook e a saúde da conexão com a internet.

> Projeto de portfólio em Python/FastAPI + frontend vanilla, feito para uso local em redes próprias ou explicitamente autorizadas.

## Screenshots

![Dashboard overview](docs/screenshots/dashboard-overview.png)
![System monitor](docs/screenshots/system-monitor.png)
![Network topology](docs/screenshots/network-topology.png)
![Safe terminal](docs/screenshots/safe-terminal.png)

As imagens de portfolio usam identificadores e enderecos de rede mascarados.

## Demo

Uma gravacao curta da interface em execucao esta disponivel em
[docs/demo/dashboard-demo.webm](docs/demo/dashboard-demo.webm).

## Funcionalidades

- Inventário local de dispositivos da rede autorizada.
- Perfis de rede separados por gateway/sub-rede/SSID para não misturar casa, trabalho e outros locais.
- Detecção de dispositivos novos, offline e retornando online.
- Baseline de dispositivos e alertas para mudanças de portas, hostname, vendor, MAC e IP.
- Mapa de topologia com posições persistidas em SQLite.
- WebSocket para atualizações em tempo real.
- Monitor do notebook: CPU, RAM, disco, uptime, processos pesados e temperatura quando disponível.
- Monitor de internet: gateway, ping para `8.8.8.8`, média de latência e últimos 60 pings em memória.
- Safe Commands: botões allowlistados para diagnósticos locais, sem terminal livre.
- Exportação CSV/JSON para inventário e detalhes de dispositivos.
- Interface cyberpunk responsiva para demonstração visual em portfólio.

## Stack

- Python 3.10+
- FastAPI
- Uvicorn
- SQLite
- WebSocket
- psutil
- HTML, CSS e JavaScript vanilla
- Chart.js
- vis-network
- Nmap opcional

## Segurança e Uso Permitido

Este projeto é defensivo e educacional.

Use apenas em redes próprias ou com autorização explícita. O dashboard não deve ser usado para escanear IP público, explorar vulnerabilidades, burlar autenticação, fazer brute force ou acessar dispositivos de terceiros.

Por padrão, o scanner respeita `ALLOWED_NETWORK` e pode operar sem Nmap usando dados locais de ARP/ping controlado. O módulo de internet faz apenas pings controlados para gateway local e `8.8.8.8`.

## Instalação No Windows

```powershell
cd C:\caminho\cyber-home-dashboard
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Se o PowerShell bloquear ativação de venv, você pode rodar usando o Python da venv diretamente, como nos comandos acima.

## Configuração

Descubra a sub-rede local atual:

```powershell
py -3 .\detect_local_network.py
```

Edite `.env`:

```env
SCAN_INTERVAL_SECONDS=60
ALLOWED_NETWORK=192.168.1.0/24
USE_NMAP=false
FALLBACK_SWEEP=false
```

## Como Rodar

Com Python global:

```powershell
cd C:\caminho\cyber-home-dashboard
py -3 -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir backend
```

Com venv:

```powershell
cd C:\caminho\cyber-home-dashboard
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir backend
```

Abra:

[http://127.0.0.1:8000](http://127.0.0.1:8000)

## Endpoints Principais

- `GET /health`
- `GET /api/status`
- `POST /api/scan`
- `GET /api/devices`
- `GET /api/networks`
- `GET /api/networks/current`
- `PATCH /api/networks/{id}`
- `GET /api/topology`
- `GET /api/system/status`
- `GET /api/network/health`
- `POST /api/tools/run`
- `WS /ws/events`

## Safe Commands

O endpoint `POST /api/tools/run` aceita apenas nomes de ações allowlistadas:

```json
{ "action": "ping_google" }
```

Ações disponíveis:

- `ping_gateway`
- `ping_google`
- `ipconfig`
- `routes`
- `system_status`

Não existe execução livre de comandos.

## Roadmap

- Docker e Docker Compose.
- Autenticação local para proteger o dashboard.
- Notificações para eventos críticos.
- IA analisando eventos e sugerindo ações defensivas.
- Deploy local em mini PC ou Raspberry Pi.
- Persistência do histórico de internet no SQLite.
- Página de relatórios para exportar evidências de monitoramento.

## Licença

MIT. Veja [LICENSE](LICENSE).
