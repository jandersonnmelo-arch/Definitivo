# Catálogo oficial de competições monitoradas pelo Arena 360.
# A lista fixa é sempre coletada; a lista opcional pode ser ampliada pelo usuário.

FIXED_COMPETITIONS = [
    ("🌍 FIFA World Cup", ["fifa world cup", "world cup"]),
    ("🇪🇺 UEFA Champions League", ["uefa champions league", "champions league"]),
    ("🇩🇪 Bundesliga", ["bundesliga"]),
    ("🇳🇱 Eredivisie", ["eredivisie"]),
    ("🇧🇷 Campeonato Brasileiro Série A", ["campeonato brasileiro série a", "campeonato brasileiro serie a", "brazilian serie a", "brasileirao serie a", "brasileirao"]),
    ("🇪🇸 Primera División", ["primera division", "la liga", "laliga"]),
    ("🇫🇷 Ligue 1", ["ligue 1"]),
    ("🇵🇹 Primeira Liga", ["primeira liga", "liga portugal"]),
    ("🇪🇺 European Championship", ["european championship", "uefa european championship", "euro"]),
    ("🇮🇹 Serie A", ["serie a"]),
    ("🏴 Premier League", ["premier league"]),
    ("🇧🇷 Campeonato Brasileiro Série B", ["campeonato brasileiro série b", "campeonato brasileiro serie b", "brazilian serie b", "brasileirao serie b"]),
    ("🏆 Copa Libertadores", ["copa libertadores", "conmebol libertadores", "libertadores"]),
    ("🏆 Copa Sudamericana", ["copa sudamericana", "copa sul-americana", "copa sul americana", "conmebol sudamericana", "sudamericana"]),
    ("🇧🇷 Campeonato Paulista", ["campeonato paulista", "paulista"]),
    ("🇧🇷 Campeonato Carioca", ["campeonato carioca", "carioca"]),
    ("🇧🇷 Campeonato Gaúcho", ["campeonato gaucho", "campeonato gaúcho", "gaucho"]),
    ("🇧🇷 Campeonato Mineiro", ["campeonato mineiro", "mineiro"]),
]

OPTIONAL_COMPETITIONS = [
    ("🇧🇷 Copa do Brasil", ["copa do brasil"]),
    ("🇦🇷 Primera División Argentina", ["primera división argentina", "primera division argentina", "liga profesional argentina"]),
    ("🇺🇸 MLS", ["mls", "major league soccer"]),
    ("🇲🇽 Liga MX", ["liga mx"]),
    ("🇸🇦 Saudi Pro League", ["saudi pro league"]),
    ("🇹🇷 Süper Lig", ["super lig", "süper lig"]),
    ("🇧🇪 Belgian Pro League", ["belgian pro league"]),
    ("🏴 Scottish Premiership", ["scottish premiership"]),
    ("🇨🇴 Primera A Colombia", ["primera a colombia", "liga betplay"]),
    ("🇯🇵 J1 League", ["j1 league"]),
    ("🇰🇷 K League 1", ["k league 1"]),
    ("🇪🇺 UEFA Europa League", ["uefa europa league", "europa league"]),
    ("🇪🇺 UEFA Conference League", ["uefa conference league", "conference league"]),
]

EXCLUDED_COMPETITIONS = {"championship", "efl championship", "english championship"}


def _norm(value):
    return " ".join(str(value or "").strip().lower().replace("-", " ").split())


def competition_matches(actual, selected):
    """Compara o nome retornado pela fonte com os nomes canônicos selecionados."""
    a = _norm(actual)
    if not a or a in EXCLUDED_COMPETITIONS:
        return False
    for label, aliases in FIXED_COMPETITIONS + OPTIONAL_COMPETITIONS:
        if label not in selected:
            continue
        for alias in aliases:
            n = _norm(alias)
            if a == n or n in a or a in n:
                # Evita que 'Serie A' case também com outras séries.
                if label == "🇮🇹 Serie A" and ("serie b" in a or "serie c" in a):
                    continue
                if label == "🇧🇷 Campeonato Brasileiro Série A" and "serie b" in a:
                    continue
                if label == "🇧🇷 Campeonato Brasileiro Série B" and "serie a" in a:
                    continue
                return True
    return False


def selected_labels(extra=None):
    fixed = [x[0] for x in FIXED_COMPETITIONS]
    return fixed + [x for x in (extra or []) if x not in fixed]
