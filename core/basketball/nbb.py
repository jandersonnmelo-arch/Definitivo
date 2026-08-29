from __future__ import annotations

from datetime import date
from io import StringIO
import calendar, re, unicodedata
import pandas as pd
import requests

LNB_URL = "https://lnb.com.br/nbb/tabela-de-jogos/"
LNB_STATS_BASE = "https://lnb.com.br/nbb/estatisticas"
SEASON_ID = "47"  # NBB 2025/2026

TEAMS = {
    "Basket Osasco": ["basket osasco","osasco"], "Bauru Basket":["bauru basket","bauru"], "Botafogo":["botafogo"],
    "CAIXA/Brasília Basquete":["caixa/brasilia basquete","caixa brasilia","brasilia basquete"], "Caxias do Sul Basquete":["caxias do sul basquete","caxias do sul","caxias"],
    "Corinthians":["corinthians","corinthians basquete"], "Cruzeiro":["cruzeiro","cruzeiro basquete"], "Flamengo":["flamengo","clube de regatas do flamengo"],
    "Fortaleza Basquete Cearense":["fortaleza basquete cearense","fortaleza bc","fortaleza"], "Sesi Franca":["sesi franca","franca","franca basquete"],
    "KTO Minas":["kto minas","minas tenis clube","minas tênis clube","minas"], "Mogi Basquete":["mogi basquete","mogi"], "Pato Basquete":["pato basquete","pato"],
    "Paulistano":["paulistano/corpe","paulistano","corpe"], "Pinheiros":["pinheiros","ec pinheiros"], "Conta Simples Rio Claro":["conta simples rio claro","rio claro"],
    "Mr. Moo São José Basketball":["mr. moo são josé basketball","são josé basketball","sao jose basketball","mr. moo são josé","mr. moo sao jose"],
    "Ceisc/União Corinthians":["ceisc/união corinthians","ceisc/uniao corinthians","união corinthians","uniao corinthians"], "UNIFACISA":["unifacisa"], "Vasco da Gama":["vasco da gama","vasco"],
}
CATEGORIES={"Arremessos":"arremessos","Rebotes":"rebotes","Assistências":"assistencias","Eficiência":"eficiencia","Bolas recuperadas":"bolas-recuperadas","Tocos":"tocos","Erros":"erros"}


def norm(v):
    text=unicodedata.normalize("NFKD",str(v or "")); text="".join(c for c in text if not unicodedata.combining(c)); return re.sub(r"\s+"," ",text).strip().casefold()


def canonical_team(v):
    text=norm(v)
    for team,aliases in TEAMS.items():
        if any(text==norm(a) or (len(norm(a))>=5 and re.search(rf"(?<!\w){re.escape(norm(a))}(?!\w)",text)) for a in aliases): return team
    return None


def _request(url, params):
    r=requests.get(url,params=params,headers={"User-Agent":"Mozilla/5.0 Premium-Analytics","Accept-Language":"pt-BR,pt;q=0.9"},timeout=30); r.raise_for_status(); return r.text


def _tables(html):
    tables=pd.read_html(StringIO(html)); return [t.copy() for t in tables if isinstance(t,pd.DataFrame) and len(t)>0]


def _col(df, terms):
    for c in df.columns:
        if any(t in norm(c) for t in terms): return c
    return None


def collect_player_stats(team: str, months: int = 8):
    if team not in TEAMS: raise ValueError(f"Time NBB não reconhecido: {team}")
    rows=[]
    for slug in CATEGORIES.values():
        html=_request(f"{LNB_STATS_BASE}/{slug}/",[("aggr","avg"),("season[]",SEASON_ID),("type","athletes"),("suffered_rule","0"),("wherePlaying","-1")])
        table=next((t for t in _tables(html) if _col(t,["jogador"]) and _col(t,["equipe"])),None)
        if table is None: continue
        ec=_col(table,["equipe"]); filtered=table[table[ec].map(canonical_team).eq(team)].copy()
        for _,r in filtered.iterrows():
            item={"competition":"NBB","Jogador":r.get(_col(filtered,["jogador"])),"Equipe":team,"categoria":slug}
            for c in filtered.columns:
                if c not in (ec,_col(filtered,["jogador"])): item[str(c)]=r[c]
            rows.append(item)
    return rows


def collect_team_history(team: str, months: int = 8):
    if team not in TEAMS: raise ValueError(f"Time NBB não reconhecido: {team}")
    html=_request(LNB_URL,[("season[]",SEASON_ID)]); games=[]
    for table in _tables(html):
        for _,r in table.astype(object).iterrows():
            cells=[str(x) for x in r.tolist()]
            text=" | ".join(cells); teams=[]
            for i,v in enumerate(cells):
                t=canonical_team(v)
                if t and t not in [x[1] for x in teams]: teams.append((i,t))
            if len(teams)<2: continue
            m=re.search(r"(\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2})?)",text)
            if not m: continue
            dt=pd.to_datetime(m.group(1),dayfirst=True,errors="coerce")
            if pd.isna(dt) or team not in [x[1] for x in teams]: continue
            score=None
            for v in cells:
                sm=re.search(r"(?<!\d)(\d{1,3})\s*[xX]\s*(\d{1,3})(?!\d)",v)
                if sm: score=(int(sm.group(1)),int(sm.group(2))); break
            home=teams[0][1]; away=teams[1][1]
            games.append({"competition":"NBB","date":dt.date(),"home":home,"away":away,"PF":score[0] if score else None,"PA":score[1] if score else None,"played":score is not None})
    unique={(x["date"],x["home"],x["away"],x["PF"],x["PA"]):x for x in games}; games=list(unique.values()); return {"competition":"NBB","team":team,"season":SEASON_ID,"games":games,"players":collect_player_stats(team,months)}


def collect_game(game_id: str):
    raise RuntimeError("A LNB não possui nesta integração um endpoint canônico de box score por ID. Use a tabela/súmula oficial para enriquecer a partida.")
