# Architecture

## Visão Geral

O Cyber Home Dashboard usa uma arquitetura simples e local-first:

```text
Browser
  |
  | HTTP REST + WebSocket
  v
FastAPI backend
  |
  | SQLite / subprocess seguro / psutil / ping controlado
  v
Sistema local e rede autorizada
```

## Backend

O backend é uma aplicação FastAPI que serve API e frontend estático. Ele centraliza as regras de segurança para scan local, comandos allowlistados e coleta de métricas.

Responsabilidades:

- Expor endpoints REST.
- Gerenciar WebSocket.
- Rodar scans locais.
- Persistir inventário e eventos.
- Coletar métricas do notebook.
- Verificar saúde da internet com ping controlado.

## Frontend

O frontend é estático e usa JavaScript vanilla. Ele combina:

- Polling leve para módulos de sistema e internet.
- WebSocket para eventos de inventário.
- Chart.js para histórico.
- vis-network para topologia.

## Dados

O SQLite guarda estado durável de rede:

- Perfis de rede.
- Dispositivos.
- Eventos.
- Baseline.
- Histórico agregado.
- Posições de topologia.

Dados de sistema e internet são transitórios na v1.0, exceto quando refletidos visualmente na interface.

## Fluxo de Scan

1. Usuário solicita scan ou auto-scan dispara.
2. Backend detecta a rede atual por gateway, sub-rede e SSID quando disponível.
3. Backend valida `ALLOWED_NETWORK`.
4. Scanner usa Nmap, se habilitado, ou fallback local.
5. Resultados são sincronizados com SQLite usando `network_id`.
6. Eventos e mudanças de baseline são gerados apenas para a rede atual.
7. WebSocket notifica frontend.

## Fluxo Safe Commands

1. Usuário clica em um botão predefinido.
2. Frontend envia `{ "action": "nome" }`.
3. Backend valida a ação contra allowlist.
4. Comando roda com timeout de 5 segundos.
5. Saída é exibida no painel terminal seguro.
