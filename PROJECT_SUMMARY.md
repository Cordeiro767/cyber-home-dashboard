# Project Summary - Cyber Home Dashboard

## Objetivo

O Cyber Home Dashboard é uma central local de monitoramento defensivo para redes domésticas e pequenos laboratórios. Ele combina inventário de rede, eventos em tempo real, monitoramento do notebook, saúde da internet e ferramentas seguras de diagnóstico.

O projeto foi preparado para portfólio com foco em utilidade real, clareza arquitetural e limites explícitos de segurança.

## Arquitetura

O sistema é dividido em:

- Backend FastAPI em `backend/`.
- Frontend estático em `frontend/`.
- Banco SQLite em `data/network.db`.
- Logs locais em `logs/events.log`.
- Configuração por `.env`.

O FastAPI serve tanto a API quanto os arquivos estáticos do frontend. O frontend consome endpoints REST e WebSocket para manter a interface atualizada.

## Backend

Principais módulos:

- `main.py`: define a aplicação FastAPI, rotas REST, WebSocket e lifecycle.
- `scanner.py`: faz descoberta limitada à sub-rede configurada em `ALLOWED_NETWORK`.
- `network_profile.py`: detecta gateway, sub-rede e SSID para separar inventários por rede.
- `database.py`: gerencia SQLite, dispositivos, eventos, histórico e exportações.
- `baseline.py`: compara estado atual de dispositivos contra baseline conhecida.
- `topology.py`: monta nós e arestas do mapa de rede.
- `system_monitor.py`: coleta CPU, RAM, disco, uptime, processos e temperatura quando disponível.
- `internet_health.py`: faz pings controlados para gateway e `8.8.8.8`.
- `safe_tools.py`: executa apenas ações allowlistadas.
- `autoscan.py`: gerencia loop de auto-scan.
- `ws_manager.py` e `realtime.py`: coordenam WebSocket e snapshots live.

## Frontend

O frontend usa HTML, CSS e JavaScript vanilla:

- `index.html`: estrutura dos painéis.
- `style.css`: visual cyberpunk, layout, cards e responsividade.
- `app.js`: estado principal, polling leve, WebSocket e ações do usuário.
- `topology.js`: mapa de rede com vis-network.
- `device-details.js`: modal de detalhes do dispositivo.

## Banco SQLite

O SQLite mantém:

- Perfis de rede.
- Dispositivos conhecidos.
- Eventos de rede.
- Histórico agregado.
- Baselines de dispositivos.
- Posições persistidas dos nós de topologia.

Os módulos de sistema e internet usam memória inicialmente para dados transitórios, mantendo compatibilidade com o banco atual.

## WebSocket

O WebSocket em `WS /ws/events` envia snapshots e mensagens de terminal live para a interface. Ele reduz a necessidade de polling para eventos de inventário e melhora a sensação de dashboard em tempo real.

## Módulos de Rede e Sistema

### Perfis de Rede

Cada rede recebe um registro próprio em `networks`. Dispositivos, eventos, mudanças de baseline e posições da topologia passam a ser associados por `network_id`, evitando que dispositivos de uma casa apareçam como offline em outra.

### Inventário de Rede

Escaneia apenas a rede configurada em `ALLOWED_NETWORK`. Pode usar Nmap opcionalmente, mas por padrão suporta fallback leve baseado em ARP/ping/portas comuns.

### Monitor do Notebook

Usa `psutil` para coletar métricas locais. Temperatura é exibida apenas quando o Windows expõe sensores compatíveis.

### Monitor de Internet

Executa ping no gateway local e em `8.8.8.8`, mantendo os últimos 60 pontos em memória para visualização rápida de estabilidade.

### Safe Commands

Não aceita texto livre. O usuário escolhe ações fixas e o backend valida pelo nome da ação.
