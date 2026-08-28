from datetime import timedelta


def resolve_espn_event_id(match, provider, get_provider_id, same_team, parse_start, add_diagnostic):
    """Resolve ESPN event using persisted provider ID first, then +/- 1 day scoreboard."""
    existing = get_provider_id(match.get('id'), provider.name)
    if existing:
        add_diagnostic('diagnostico_jogadores','OK',f'ESPN: ID do evento recuperado do banco ({existing})',provider.name,match.get('id'))
        return existing
    dt = parse_start(match.get('start_time'))
    if not dt:
        return None
    dates = []
    for delta in (-1, 0, 1):
        d = (dt + timedelta(days=delta)).date().isoformat()
        if d not in dates:
            dates.append(d)
    candidates = 0
    try:
        for d in dates:
            rows = provider.matches(d, d, None)
            candidates += len(rows)
            for m in rows:
                if same_team(match.get('home_name'), m.get('home_name')) and same_team(match.get('away_name'), m.get('away_name')):
                    return m.get('provider_match_id')
                if same_team(match.get('home_name'), m.get('away_name')) and same_team(match.get('away_name'), m.get('home_name')):
                    return m.get('provider_match_id')
    except Exception as e:
        add_diagnostic('diagnostico_jogadores','ERROR',f'ESPN resolver: {e}',provider.name,match.get('id'))
        return None
    add_diagnostic('diagnostico_jogadores','INFO',f'ESPN: nenhum evento encontrado em +/-1 dia; candidatos={candidates} para {match.get("home_name")} x {match.get("away_name")}',provider.name,match.get('id'))
    return None
