"""Ajustes de interface e execução do pacote core para o Arena 360."""

# Compacta somente a tabela de mercados de palpites, preservando os demais dataframes.
try:
    import streamlit as st
    import pandas as pd

    _arena_dataframe = st.dataframe

    def _arena_compact_dataframe(data=None, *args, **kwargs):
        try:
            if isinstance(data, pd.DataFrame):
                cols=set(data.columns)
                target={'Mercado','Linha','Probabilidade','Média projetada'}
                if target.issubset(cols):
                    frame=data.copy()
                    def compact_line(value):
                        text=str(value or '').strip()
                        return text[5:].strip() if text.startswith('Over ') else text
                    def compact_probability(value):
                        text=str(value or '').strip()
                        if text.startswith('Mais ') and 'Menos ' in text:
                            return text
                        try:
                            over=float(text.replace('%','').replace(',','.'))
                            return f'Mais {over:.1f}% • Menos {100-over:.1f}%'
                        except Exception:
                            return text
                    frame['Linha']=frame['Linha'].map(compact_line)
                    frame['Probabilidade']=frame['Probabilidade'].map(compact_probability)
                    frame=frame.rename(columns={'Média projetada':'Média'})
                    return _arena_dataframe(frame, *args, **kwargs)
        except Exception:
            pass
        return _arena_dataframe(data, *args, **kwargs)

    st.dataframe=_arena_compact_dataframe
except Exception:
    st=None

# O fluxo anterior podia ficar preso em uma coleta ESPN diária por até 120 dias
# para cada equipe. Limitamos somente o fallback operacional, preservando a
# coleta primária e os 10 jogos exigidos pelo histórico.
try:
    import importlib
    import datetime as _dt

    _history = importlib.import_module('core.history')
    _original_build_history = _history.build_history_for_match

    def _serie_b_competition(m):
        text=str(m.get('competition') or '').strip().lower()
        if _history._is_serie_b(text):
            return True
        generic_brazilian = ('brasileirao' in text or 'campeonato brasileiro' in text)
        excluded = ('serie a' in text or 'copa do brasil' in text or 'libertadores' in text or 'sul americana' in text or 'sul-americana' in text)
        return generic_brazilian and not excluded

    def _bounded_espn_history(team_name, before_iso, days=120, serie_b=False):
        provider = _history.ESPNProvider()
        before = _history._parse_start(before_iso) or _dt.datetime.now(_dt.timezone.utc)
        days = min(int(days or 120), 35)
        rows=[]
        seen=set()
        cur=before.date()-_dt.timedelta(days=days)
        end=before.date()
        while cur <= end:
            try:
                found=provider.matches(cur.isoformat(),cur.isoformat(),None)
                for m in found:
                    if serie_b and not _serie_b_competition(m):
                        continue
                    if _history._same_team(team_name,m.get('home_name')) or _history._same_team(team_name,m.get('away_name')):
                        mid=str(m.get('id'))
                        if mid not in seen:
                            _history.upsert_match(m)
                            rows.append(m)
                            seen.add(mid)
            except Exception as exc:
                _history.add_diagnostic('historico','ERROR',f'ESPN fixtures: {exc}',provider.name)
            cur += _dt.timedelta(days=1)
        _history.add_diagnostic('historico','OK',f'ESPN fallback limitado: {len(rows)} partidas para {team_name} em {days} dias; serie_b={serie_b}',provider.name)
        return rows

    _history._collect_team_history_from_espn = _bounded_espn_history

    def _build_history_safe(match, matches_per_team=_history.HISTORY_MATCHES_PER_TEAM, days=_history.HISTORY_DAYS):
        try:
            result = _original_build_history(match, matches_per_team, min(int(days or 180), 90))
            if st is not None:
                st.session_state['_arena_history_result'] = result if isinstance(result, dict) else {}
                st.session_state['_arena_suppress_history_rerun'] = True
            return result
        except Exception as exc:
            if st is not None:
                st.session_state['_arena_history_result'] = {
                    'home_matches': 0,
                    'away_matches': 0,
                    'stats_records': 0,
                    'player_records': 0,
                    'current_players': [],
                    'error': str(exc),
                }
                st.session_state['_arena_suppress_history_rerun'] = True
            raise

    _history.build_history_for_match = _build_history_safe

    if st is not None:
        _original_rerun = st.rerun
        def _arena_rerun(*args, **kwargs):
            if st.session_state.pop('_arena_suppress_history_rerun', False):
                return None
            return _original_rerun(*args, **kwargs)
        st.rerun = _arena_rerun
except Exception:
    pass

# Proteção contra colisão de provider_match_id durante a coleta do histórico.
try:
    import sqlite3 as _sqlite3
    import core.db as _db

    _original_db_upsert_match = _db.upsert_match

    def _safe_db_upsert_match(match):
        source = match.get('source', 'unknown')
        provider_id = str(match.get('provider_match_id', match.get('id') or ''))
        try:
            c = _db.connect()
            row = c.execute(
                'SELECT match_id FROM match_sources WHERE source=? AND provider_match_id=?',
                (source, provider_id),
            ).fetchone()
            c.close()
            if row and row['match_id']:
                existing_id = str(row['match_id'])
                incoming_id = str(match.get('id') or '')
                if existing_id != incoming_id:
                    match = dict(match)
                    match['id'] = existing_id
        except Exception:
            pass
        try:
            return _original_db_upsert_match(match)
        except _sqlite3.IntegrityError:
            try:
                c = _db.connect()
                row = c.execute(
                    'SELECT match_id FROM match_sources WHERE source=? AND provider_match_id=?',
                    (source, provider_id),
                ).fetchone()
                c.close()
                if row and row['match_id']:
                    retry = dict(match)
                    retry['id'] = str(row['match_id'])
                    return _original_db_upsert_match(retry)
            except Exception:
                pass
            raise

    _db.upsert_match = _safe_db_upsert_match
    _history.upsert_match = _safe_db_upsert_match
except Exception:
    pass

# Correção do histórico exibido na tela.
# A análise pré-jogo já encontra os 10 jogos, mas o bloco visual pode receber
# uma identidade de equipe diferente da usada em partidas persistidas por
# outra fonte. O wrapper abaixo usa primeiro o ID e, se necessário, resolve
# a equipe pelo nome normalizado. Não faz chamadas à API.
try:
    import re as _re
    import unicodedata as _unicodedata

    _TEAM_VIEW_ALIASES = {
        'cr flamengo':'flamengo', 'flamengo rj':'flamengo', 'flamengo':'flamengo',
        'se palmeiras':'palmeiras', 'palmeiras':'palmeiras',
        'sao paulo fc':'sao paulo', 'sao paulo':'sao paulo',
        'corinthians paulista':'corinthians', 'sport corinthians paulista':'corinthians',
        'sport club corinthians paulista':'corinthians', 'corinthians':'corinthians',
        'santos fc':'santos', 'santos':'santos',
        'gremio fbpa':'gremio', 'gremio':'gremio',
        'sport club internacional':'internacional', 'internacional':'internacional',
        'cruzeiro esporte clube':'cruzeiro', 'cruzeiro':'cruzeiro',
        'botafogo fr':'botafogo', 'botafogo':'botafogo',
        'fluminense fc':'fluminense', 'fluminense':'fluminense',
        'atletico mineiro':'atletico mineiro', 'atletico mg':'atletico mineiro',
        'ca mineiro':'atletico mineiro', 'clube atletico mineiro':'atletico mineiro',
        'atletico mg':'atletico mineiro',
        'ca paranaense':'athletico paranaense', 'atletico pr':'athletico paranaense',
        'atletico paranaense':'athletico paranaense', 'athletico paranaense':'athletico paranaense',
        'athletico pr':'athletico paranaense',
        'red bull bragantino':'red bull bragantino', 'bragantino':'red bull bragantino',
        'ec bahia':'bahia', 'bahia':'bahia',
        'vitoria':'vitoria', 'ec vitoria':'vitoria',
        'ceara sc':'ceara', 'ceara':'ceara',
        'fortaleza ec':'fortaleza', 'fortaleza':'fortaleza',
        'sport recife':'sport recife', 'sport':'sport recife',
        'vasco da gama':'vasco da gama', 'vasco':'vasco da gama',
        'america mineiro':'america mineiro', 'america mg':'america mineiro',
        'atletico go':'atletico goianiense', 'atletico goianiense':'atletico goianiense',
        'avai fc':'avai', 'avai':'avai',
        'chapecoense af':'chapecoense', 'chapecoense':'chapecoense',
        'cuiaba ec':'cuiaba', 'cuiaba':'cuiaba',
        'criciuma ec':'criciuma', 'criciuma':'criciuma',
        'juventude':'juventude', 'ec juventude':'juventude',
        'mirassol fc':'mirassol', 'mirassol':'mirassol',
        'vila nova fc':'vila nova', 'vila nova':'vila nova',
        'novorizontino':'novorizontino', 'gremio novorizontino':'novorizontino',
        'operario ferroviario ec':'operario', 'operario':'operario',
        'athletico pr':'athletico paranaense',
    }

    def _view_team_key(value):
        text=_unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode().lower()
        text=_re.sub(r'[^a-z0-9]+',' ',text).strip()
        return _TEAM_VIEW_ALIASES.get(text,text)

    def _view_team_name(value):
        key=_view_team_key(value)
        labels={
            'flamengo':'Flamengo','palmeiras':'Palmeiras','sao paulo':'São Paulo',
            'corinthians':'Corinthians','santos':'Santos','gremio':'Grêmio',
            'internacional':'Internacional','cruzeiro':'Cruzeiro','botafogo':'Botafogo',
            'fluminense':'Fluminense','atletico mineiro':'Atlético-MG',
            'athletico paranaense':'Athletico-PR','red bull bragantino':'Bragantino',
            'bahia':'Bahia','vitoria':'Vitória','ceara':'Ceará','fortaleza':'Fortaleza',
            'sport recife':'Sport','vasco da gama':'Vasco','america mineiro':'América-MG',
            'atletico goianiense':'Atlético-GO','avai':'Avaí','chapecoense':'Chapecoense',
            'cuiaba':'Cuiabá','criciuma':'Criciúma','juventude':'Juventude',
            'mirassol':'Mirassol','vila nova':'Vila Nova','novorizontino':'Novorizontino',
            'operario':'Operário',
        }
        return labels.get(key,value)

    def _canonicalize_match_view(row):
        item=dict(row)
        if item.get('home_name'): item['home_name']=_view_team_name(item['home_name'])
        if item.get('away_name'): item['away_name']=_view_team_name(item['away_name'])
        return item

    _original_get_matches=_db.get_matches
    _original_get_match=_db.get_match
    _original_team_history=_db.team_history

    def _safe_get_matches(*args,**kwargs):
        return [_canonicalize_match_view(x) for x in _original_get_matches(*args,**kwargs)]

    def _safe_get_match(*args,**kwargs):
        row=_original_get_match(*args,**kwargs)
        return _canonicalize_match_view(row) if row else row

    def _safe_team_history(team_id,before_iso=None,limit=10):
        rows=_original_team_history(team_id,before_iso,limit)
        if len(rows)>=limit:
            return [_canonicalize_match_view(x) for x in rows[:limit]]

        # Recupera duplicatas históricas que ficaram associadas a outra
        # identidade canônica do mesmo time em uma fonte diferente.
        try:
            c=_db.connect()
            team=c.execute('SELECT name,normalized_name FROM teams WHERE id=?', (team_id,)).fetchone()
            if not team:
                c.close();return [_canonicalize_match_view(x) for x in rows]
            wanted=_view_team_key(team['name'])
            sql="SELECT * FROM matches WHERE sport='Futebol' AND status='FINISHED'"
            params=[]
            if before_iso:
                sql+=' AND start_time<?';params.append(before_iso)
            sql+=' ORDER BY start_time DESC LIMIT 500'
            candidates=[dict(r) for r in c.execute(sql,params).fetchall()]
            c.close()
            existing={str(x.get('id')) for x in rows}
            for item in candidates:
                if len(rows)>=limit:break
                hk=_view_team_key(item.get('home_name'));ak=_view_team_key(item.get('away_name'))
                if wanted in {hk,ak} and str(item.get('id')) not in existing:
                    rows.append(item);existing.add(str(item.get('id')))
            rows.sort(key=lambda x:x.get('start_time') or '',reverse=True)
        except Exception:
            pass
        return [_canonicalize_match_view(x) for x in rows[:limit]]

    _db.get_matches=_safe_get_matches
    _db.get_match=_safe_get_match
    _db.team_history=_safe_team_history
except Exception:
    pass
