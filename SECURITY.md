# Security Policy - Cyber Home Dashboard

## Escopo do projeto

O Cyber Home Dashboard é uma ferramenta educacional e defensiva para monitoramento local. Use somente em redes e dispositivos próprios ou para os quais você tenha autorização explícita.

## Controles implementados

- Descoberta limitada pela configuração `ALLOWED_NETWORK`.
- Monitor de internet restrito ao gateway local e a ping controlado para `8.8.8.8`.
- Safe Terminal baseado em uma allowlist fixa, sem entrada de comando livre.
- Timeout curto para ferramentas de diagnóstico.
- Arquivos sensíveis e artefatos locais ignorados pelo Git.

## Uso não permitido

- Escanear redes públicas ou de terceiros sem autorização.
- Tentar senhas, brute force ou bypass de autenticação.
- Explorar vulnerabilidades de dispositivos.
- Expor o dashboard ou equipamentos locais diretamente à internet.
- Versionar credenciais, bancos locais, logs sensíveis ou capturas de tráfego.

## Recomendações de execução

- Mantenha o serviço em `127.0.0.1` durante desenvolvimento e demonstrações pessoais.
- Revise `.env` antes de iniciar qualquer descoberta de rede.
- Use screenshots com dados mascarados ao publicar o projeto.
- Adicione autenticação antes de permitir acesso por outros dispositivos na LAN.

## Relato responsável

Caso identifique um problema de segurança no código, não publique credenciais, IPs reais ou dados de rede em uma issue pública. Abra uma issue descrevendo apenas o componente afetado e solicite um canal privado para detalhes, quando necessário.
