from collections import Counter
from datetime import datetime, timezone
import re
import unicodedata
from core.db import connect, init_db, get_matches
from core.ai_dataset import build_dataset_v1, load_dataset
VALIDATOR_VERSION="AI-QUALITY-V1"
def _norm(v):
 s=unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().lower(); return re.sub(r"[^a-z0-9]+"," ",s).strip()
def _fp(m): return (_norm(m.get("home_name")),_norm(m.get("away_name")),str(m.get("start_time") or "")[:16])
def _iso(v):
 try:return datetime.fromisoformat(str(v).replace("Z","+00:00"))
 except (TypeError,ValueError):return None
def _source_checks():
 init_db(); ms=get_matches("Futebol",10000); fin=[m for m in ms if m.get("status")=="FINISHED"]; dup=sum(n-1 for n in Counter(_fp(m) for m in fin).values() if n>1); issues=[]
 for m in fin:
  name=f"{m.get('home_name')} × {m.get('away_name')}"
  if not m.get("home_id") or not m.get("away_id"):issues.append(("equipe_sem_id",name,"Mandante ou visitante sem ID canônico."))
  if m.get("home_score") is None or m.get("away_score") is None:issues.append(("placar_incompleto",name,"FINISHED sem os dois placares."))
  if not _iso(m.get("start_time")):issues.append(("data_invalida",name,"start_time ausente ou inválido."))
 c=connect(); orphan_stats=c.execute("SELECT COUNT(*) FROM match_stats s LEFT JOIN matches m ON m.id=s.match_id WHERE m.id IS NULL").fetchone()[0]; wrong_stats=c.execute("SELECT COUNT(*) FROM match_stats s JOIN matches m ON m.id=s.match_id WHERE s.team_id NOT IN (m.home_id,m.away_id)").fetchone()[0]; orphan_players=c.execute("SELECT COUNT(*) FROM player_stats p LEFT JOIN matches m ON m.id=p.match_id WHERE m.id IS NULL").fetchone()[0]; wrong_players=c.execute("SELECT COUNT(*) FROM player_stats p JOIN matches m ON m.id=p.match_id WHERE p.team_id IS NOT NULL AND p.team_id NOT IN (m.home_id,m.away_id)").fetchone()[0]; stats_total=c.execute("SELECT COUNT(*) FROM match_stats").fetchone()[0]; player_stats_total=c.execute("SELECT COUNT(*) FROM player_stats").fetchone()[0]; players_total=c.execute("SELECT COUNT(*) FROM players").fetchone()[0]; c.close()
 checks=[("duplicidade_partidas",dup,f"{dup} registro(s) duplicado(s) por equipes + minuto."),("estatistica_orfa",orphan_stats,f"{orphan_stats} estatística(s) sem partida."),("estatistica_equipe_invalida",wrong_stats,f"{wrong_stats} estatística(s) com equipe fora da partida."),("jogador_stat_orfao",orphan_players,f"{orphan_players} registro(s) individual(is) sem partida."),("jogador_equipe_invalida",wrong_players,f"{wrong_players} registro(s) individual(is) com equipe fora da partida.")]
 for k,n,msg in checks:
  if n:issues.append((k,"base histórica",msg))
 return {"matches_total":len(ms),"finished_matches":len(fin),"duplicate_matches":dup,"stats_total":stats_total,"player_stats_total":player_stats_total,"players_total":players_total,"orphan_stats":orphan_stats,"wrong_team_stats":wrong_stats,"orphan_player_stats":orphan_players,"wrong_team_player_stats":wrong_players,"issues":issues}
def _dataset_checks():
 rows=load_dataset(training_ready=False);issues=[];cutoff_bad=invalid_targets=low_quality=0;c=connect()
 for r in rows:
  m=c.execute("SELECT * FROM matches WHERE id=?",(r.get("match_id"),)).fetchone()
  if not m:issues.append(("dataset_partida_inexistente",str(r.get("match_id")),"Amostra sem partida correspondente."));continue
  cutoff=_iso(r.get("cutoff_time"));start=_iso(m["start_time"])
  if not cutoff or not start or cutoff!=start:cutoff_bad+=1
  if r.get("target_result") not in {"HOME","DRAW","AWAY"}:invalid_targets+=1
  if float(r.get("quality_score") or 0)<.50:low_quality+=1
 c.close()
 if cutoff_bad:issues.append(("violacao_corte_temporal","dataset IA",f"{cutoff_bad} amostra(s) com corte temporal inconsistente."))
 if invalid_targets:issues.append(("target_invalido","dataset IA",f"{invalid_targets} alvo(s) inválido(s)."))
 if low_quality:issues.append(("qualidade_baixa","dataset IA",f"{low_quality} amostra(s) abaixo de 0,50."))
 return {"dataset_rows":len(rows),"cutoff_violations":cutoff_bad,"invalid_targets":invalid_targets,"low_quality":low_quality,"issues":issues}
def validate_ai_data():
 source=_source_checks();dataset=_dataset_checks();issues=source["issues"]+dataset["issues"];return {"validator_version":VALIDATOR_VERSION,"checked_at":datetime.now(timezone.utc).isoformat(),"ok":not issues,"source":source,"dataset":dataset,"issues":issues}
def build_and_validate_ai_dataset(max_matches=5000):
 summary=build_dataset_v1(max_matches=max_matches);result=validate_ai_data();result["dataset_summary"]=summary;return result
