import json
from datetime import datetime, timezone
from core.db import connect
AI_SCHEMA_VERSION="1"
def _now():return datetime.now(timezone.utc).isoformat()
def _remote_push():
    try:
        from core.remote_persistence import push
        return push(force=True)
    except Exception:return {"pushed":False,"reason":"remote_persistence_error"}
def init_ai_db():
    c=connect();c.executescript("""
    CREATE TABLE IF NOT EXISTS ai_match_samples(id INTEGER PRIMARY KEY AUTOINCREMENT,match_id TEXT NOT NULL,dataset_version TEXT NOT NULL,created_at TEXT NOT NULL,cutoff_time TEXT NOT NULL,sport TEXT NOT NULL,competition TEXT,season TEXT,home_team_id TEXT,home_team_name TEXT,away_team_id TEXT,away_team_name TEXT,feature_json TEXT NOT NULL,target_home_goals REAL,target_away_goals REAL,target_result TEXT,target_total_goals REAL,target_btts INTEGER,is_training_ready INTEGER NOT NULL DEFAULT 0,UNIQUE(match_id,dataset_version));
    CREATE TABLE IF NOT EXISTS ai_player_samples(id INTEGER PRIMARY KEY AUTOINCREMENT,match_id TEXT NOT NULL,player_id TEXT NOT NULL,dataset_version TEXT NOT NULL,created_at TEXT NOT NULL,cutoff_time TEXT NOT NULL,team_id TEXT,player_name TEXT,position TEXT,feature_json TEXT NOT NULL,target_json TEXT,is_training_ready INTEGER NOT NULL DEFAULT 0,UNIQUE(match_id,player_id,dataset_version));
    CREATE TABLE IF NOT EXISTS ai_predictions(id INTEGER PRIMARY KEY AUTOINCREMENT,match_id TEXT NOT NULL,model_version TEXT NOT NULL,created_at TEXT NOT NULL,prediction_json TEXT NOT NULL,actual_json TEXT,status TEXT NOT NULL DEFAULT 'PENDING',UNIQUE(match_id,model_version));
    CREATE TABLE IF NOT EXISTS ai_model_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,model_version TEXT NOT NULL,run_type TEXT NOT NULL,created_at TEXT NOT NULL,samples_used INTEGER NOT NULL DEFAULT 0,metrics_json TEXT,notes TEXT);
    CREATE INDEX IF NOT EXISTS idx_ai_match_training ON ai_match_samples(is_training_ready,cutoff_time);
    CREATE INDEX IF NOT EXISTS idx_ai_match_competition ON ai_match_samples(competition,season);
    CREATE INDEX IF NOT EXISTS idx_ai_player_training ON ai_player_samples(is_training_ready,cutoff_time);
    CREATE INDEX IF NOT EXISTS idx_ai_predictions_match ON ai_predictions(match_id);
    """);c.commit();c.close()
def _target_result(home_goals,away_goals):
    if home_goals is None or away_goals is None:return None
    return "HOME" if home_goals>away_goals else "AWAY" if home_goals<away_goals else "DRAW"
def save_match_sample(match,analysis,training_ready=False):
    init_ai_db();hg=match.get("home_score") if match.get("status")=="FINISHED" else None;ag=match.get("away_score") if match.get("status")=="FINISHED" else None
    features={"analysis_version":AI_SCHEMA_VERSION,"sample_home":analysis.get("sample_home",0),"sample_away":analysis.get("sample_away",0),"xg_home":analysis.get("xg_home"),"xg_away":analysis.get("xg_away"),"probabilities":analysis.get("probabilities",{}),"coverage":analysis.get("coverage",{}),"home":analysis.get("home",{}),"away":analysis.get("away",{}),"markets":analysis.get("markets",{}),"projections":analysis.get("projections",{})}
    ready=bool(training_ready and match.get("status")=="FINISHED" and hg is not None and ag is not None);c=connect();c.execute("""INSERT INTO ai_match_samples(match_id,dataset_version,created_at,cutoff_time,sport,competition,season,home_team_id,home_team_name,away_team_id,away_team_name,feature_json,target_home_goals,target_away_goals,target_result,target_total_goals,target_btts,is_training_ready) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(match_id,dataset_version) DO UPDATE SET created_at=excluded.created_at,cutoff_time=excluded.cutoff_time,sport=excluded.sport,competition=excluded.competition,season=excluded.season,home_team_id=excluded.home_team_id,home_team_name=excluded.home_team_name,away_team_id=excluded.away_team_id,away_team_name=excluded.away_team_name,feature_json=excluded.feature_json,target_home_goals=excluded.target_home_goals,target_away_goals=excluded.target_away_goals,target_result=excluded.target_result,target_total_goals=excluded.target_total_goals,target_btts=excluded.target_btts,is_training_ready=excluded.is_training_ready""",(match.get("id"),AI_SCHEMA_VERSION,_now(),match.get("start_time") or "",match.get("sport","Futebol"),match.get("competition"),match.get("season"),match.get("home_id"),match.get("home_name"),match.get("away_id"),match.get("away_name"),json.dumps(features,ensure_ascii=False,separators=(",",":"),default=str),hg,ag,_target_result(hg,ag),(float(hg)+float(ag)) if hg is not None and ag is not None else None,int(hg>0 and ag>0) if hg is not None and ag is not None else None,int(ready)));c.commit();c.close();_remote_push()
def save_player_samples(match,cutoff_time,players,training_ready=False):
    if not players:return 0
    init_ai_db();c=connect();count=0
    for p in players:
        player_id=str(p.get("player_id") or p.get("id") or "")
        if not player_id:continue
        features={"metrics":{k:p.get(k) for k in ("goals","assists","shots","shots_on_target","passes_completed","tackles","fouls","was_fouled","minutes","started","yellow_cards","red_cards") if p.get(k) is not None}}
        c.execute("""INSERT INTO ai_player_samples(match_id,player_id,dataset_version,created_at,cutoff_time,team_id,player_name,position,feature_json,target_json,is_training_ready) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(match_id,player_id,dataset_version) DO UPDATE SET created_at=excluded.created_at,cutoff_time=excluded.cutoff_time,team_id=excluded.team_id,player_name=excluded.player_name,position=excluded.position,feature_json=excluded.feature_json,target_json=excluded.target_json,is_training_ready=excluded.is_training_ready""",(p.get("match_id",""),player_id,AI_SCHEMA_VERSION,_now(),cutoff_time,p.get("team_id"),p.get("name"),p.get("position"),json.dumps(features,ensure_ascii=False,separators=(",",":"),default=str),json.dumps(p.get("target"),ensure_ascii=False,separators=(",",":"),default=str) if p.get("target") is not None else None,int(training_ready)));count+=1
    c.commit();c.close();_remote_push();return count
def save_prediction(match_id,model_version,prediction,actual=None,status="PENDING"):
    init_ai_db();c=connect();c.execute("""INSERT INTO ai_predictions(match_id,model_version,created_at,prediction_json,actual_json,status) VALUES(?,?,?,?,?,?) ON CONFLICT(match_id,model_version) DO UPDATE SET created_at=excluded.created_at,prediction_json=excluded.prediction_json,actual_json=excluded.actual_json,status=excluded.status""",(match_id,model_version,_now(),json.dumps(prediction,ensure_ascii=False,separators=(",",":"),default=str),json.dumps(actual,ensure_ascii=False,separators=(",",":"),default=str) if actual is not None else None,status));c.commit();c.close();_remote_push()
def ai_training_counts():
    init_ai_db();c=connect();a=c.execute("SELECT COUNT(*) FROM ai_match_samples WHERE is_training_ready=1").fetchone()[0];b=c.execute("SELECT COUNT(*) FROM ai_player_samples WHERE is_training_ready=1").fetchone()[0];p=c.execute("SELECT COUNT(*) FROM ai_match_samples WHERE is_training_ready=0").fetchone()[0];c.close();return {"match_samples":int(a),"player_samples":int(b),"pending_samples":int(p),"schema_version":AI_SCHEMA_VERSION}