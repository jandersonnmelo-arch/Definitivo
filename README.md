# Arena 360

Núcleo de futebol multi-fonte em Streamlit.

## Papéis das fontes

- ESPN e Football-Data.org: calendário e base de partidas.
- FotMob: enriquecimento de estatísticas e jogadores.
- API-Football: enriquecimento operacional pontual, sem alimentar a coleta histórica.

## Segurança de consumo

- Cache de consultas HTTP com TTL.
- API-Football protegida por limite interno de 80 chamadas/dia e 8 chamadas/minuto.
- Enriquecimento máximo de 5 partidas por operação.
- Diagnóstico persistido no banco.

## Persistência

SQLite em `data/definitivo.db`, com WAL, identidade canônica de partidas/equipes/jogadores e mapeamento dos IDs de cada fonte.
