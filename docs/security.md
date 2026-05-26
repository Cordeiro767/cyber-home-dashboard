# Security Notes

## Objetivo Defensivo

Este projeto foi criado para monitoramento defensivo em redes próprias ou autorizadas. Ele não inclui exploração, brute force, bypass de autenticação ou scan público.

## Limites Técnicos

- O scanner é limitado por `ALLOWED_NETWORK`.
- `USE_NMAP=false` pode ser usado para evitar scans pesados.
- `FALLBACK_SWEEP=false` usa apenas hosts já visíveis na tabela ARP.
- O monitor de internet faz apenas ping controlado para gateway e `8.8.8.8`.
- O Safe Terminal não aceita comando livre.
- Comandos allowlistados têm timeout de 5 segundos.

## O Que Não Fazer

- Não usar contra redes de terceiros.
- Não apontar `ALLOWED_NETWORK` para IP público.
- Não abrir portas no roteador para expor o dashboard.
- Não adicionar execução livre de comandos.
- Não usar para tentar credenciais ou explorar serviços.

## Recomendações

- Rode em `127.0.0.1` para uso pessoal.
- Se expor para a LAN, adicione autenticação local antes.
- Mantenha `.env` fora do Git.
- Não versionar `data/network.db`, logs ou capturas de tráfego.
- Revise qualquer novo comando antes de adicioná-lo à allowlist.

## Publicação No GitHub

Antes de publicar:

- Confirme que `.env` não foi commitado.
- Remova bancos locais, logs e arquivos `.pcapng`/`.etl`.
- Use screenshots sem dados sensíveis.
- Revise IPs, MACs, nomes de dispositivos e anotações.
