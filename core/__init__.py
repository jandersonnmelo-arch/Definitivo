"""Ajustes de interface do pacote core para o Arena 360."""

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
    pass
