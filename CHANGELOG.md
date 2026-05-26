# Changelog

## v1.0.0

- Preparação de portfólio para GitHub.
- Perfis de rede por gateway/sub-rede/SSID.
- Separação de dispositivos, eventos, mudanças e posições por `network_id`.
- Migração de dados antigos para “Rede antiga/importada”.
- README profissional.
- Documentação em `docs/`.
- Licença MIT.
- Organização de roadmap, arquitetura e segurança.
- Revisão de comandos seguros e limites defensivos.

- Historico filtrado corretamente ao selecionar perfis de rede.
- Monitor de internet limitado ao gateway da sub-rede autorizada.
- Interface robusta quando bibliotecas visuais externas nao estao disponiveis.
- Screenshots e video curto de demonstracao para o portfolio.

## v0.9.0

- Monitor do notebook com CPU, RAM, disco, uptime, processos e temperatura quando disponível.
- Monitor de internet com gateway, ping para `8.8.8.8`, status e histórico em memória.
- Safe Commands com allowlist e timeout.
- Endpoint `GET /api/system/status`.
- Endpoint `GET /api/network/health`.
- Endpoint `POST /api/tools/run`.

## v0.8.0

- Baseline de dispositivos.
- Painel de mudanças.
- Reconhecimento de mudanças.
- Detalhes por dispositivo com abas.
- Export JSON por dispositivo.

## v0.7.0

- Modal de detalhes do dispositivo.
- Notas locais.
- Marcação de dispositivo como trusted.
- Histórico de eventos por dispositivo.

## v0.6.0

- Mapa de topologia com vis-network.
- Persistência de posições dos nós em SQLite.
- Controles de zoom e ajuste.

## v0.5.0

- WebSocket para atualizações em tempo real.
- Terminal live feed.
- Gráfico de histórico online/offline.
- Auto-scan controlável pela interface.

## v0.4.0

- Score de risco.
- Tipos de dispositivos e tags.
- Filtros por status, tipo e risco.
- Exportação CSV.

## v0.3.0

- Banco SQLite.
- Eventos de dispositivo novo, offline e retorno online.
- Contadores de status.

## v0.2.0

- Scanner local com Nmap opcional.
- Fallback sem Nmap.
- Restrição por `ALLOWED_NETWORK`.

## v0.1.0

- Primeira versão do dashboard.
- Backend FastAPI.
- Frontend HTML/CSS/JS.
- Inventário básico de rede local.
