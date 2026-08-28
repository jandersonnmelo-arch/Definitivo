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

    def _bounded_espn_history(team_name, before_iso, days=120):
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
                    if _history._same_team(team_name,m.get('home_name')) or _history._same_team(team_name,m.get('away_name')):
                        mid=str(m.get('id'))
                        if mid not in seen:
                            _history.upsert_match(m)
                            rows.append(m)
                            seen.add(mid)
            except Exception as exc:
                _history.add_diagnostic('historico','ERROR',f'ESPN fixtures: {exc}',provider.name)
            cur += _dt.timedelta(days=1)
        _history.add_diagnostic('historico','OK',f'ESPN fallback limitado: {len(rows)} partidas para {team_name} em {days} dias',provider.name)
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
    # O patch é defensivo: qualquer falha mantém o comportamento original.
    pass
