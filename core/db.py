import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path("data/arena360.db")


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = connect()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS matches(
        id INTEGER PRIMARY KEY, sport TEXT, competition TEXT, season TEXT,
        start_time TEXT, status TEXT, minute INTEGER,
        home_id INTEGER, home_name TEXT, home_short TEXT,
        away_id INTEGER, away_name TEXT, away_short TEXT,
        home_score INTEGER, away_score INTEGER, source TEXT, updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS match_stats(
        match_id INTEGER, team_id INTEGER, metric TEXT, value REAL,
        source TEXT, observed_at TEXT,
        PRIMARY KEY(match_id, team_id, metric)
    );
    CREATE TABLE IF NOT EXISTS players(
        id INTEGER PRIMARY KEY, team_id INTEGER, name TEXT, position TEXT
    );
    CREATE TABLE IF NOT EXISTS player_stats(
        match_id INTEGER, player_id INTEGER, metric TEXT, value REAL,
        source TEXT, observed_at TEXT,
        PRIMARY KEY(match_id, player_id, metric)
    );
    CREATE TABLE IF NOT EXISTS diagnostics(
        id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER,
        stage TEXT, status TEXT, message TEXT, created_at TEXT
    );
    ''')
    c.commit()
    c.close()


def seed_demo():
    c = connect()
    if c.execute('SELECT COUNT(*) FROM matches').fetchone()[0]:
        c.close()
        return

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (1, 'Futebol', 'Brasileirão', '2026', '2026-08-27T20:00:00-04:00', 'LIVE', 78,
         10, 'Palmeiras', 'PAL', 11, 'Flamengo', 'FLA', 2, 1, 'DEMO', now),
        (2, 'Futebol', 'La Liga', '2026', '2026-08-27T16:00:00-04:00', 'SCHEDULED', 0,
         40, 'Barcelona', 'BAR', 41, 'Athletic', 'ATH', None, None, 'DEMO', now),
        (3, 'Futebol', 'Brasileirão', '2026', '2026-08-31T20:00:00-04:00', 'SCHEDULED', 0,
         50, 'Corinthians', 'COR', 51, 'Santos', 'SAN', None, None, 'DEMO', now),
    ]
    c.executemany('INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)

    stats = [
        (1,10,'shots',14,'DEMO',now),(1,11,'shots',8,'DEMO',now),
        (1,10,'shots_on_target',6,'DEMO',now),(1,11,'shots_on_target',3,'DEMO',now),
        (1,10,'corners',5,'DEMO',now),(1,11,'corners',2,'DEMO',now),
        (1,10,'possession',54,'DEMO',now),(1,11,'possession',46,'DEMO',now),
        (1,10,'passes_completed',283,'DEMO',now),(1,11,'passes_completed',241,'DEMO',now),
        (1,10,'yellow_cards',0,'DEMO',now),(1,11,'yellow_cards',2,'DEMO',now),
    ]
    c.executemany('INSERT INTO match_stats VALUES (?,?,?,?,?,?)', stats)

    players = [
        (1001,10,'Weverton','GK'),(1002,10,'Gustavo Gómez','DF'),
        (1003,10,'Raphael Veiga','MF'),(1004,10,'Flaco López','FW'),
        (1101,11,'Rossi','GK'),(1102,11,'Léo Pereira','DF'),
        (1103,11,'Arrascaeta','MF'),(1104,11,'Pedro','FW'),
    ]
    c.executemany('INSERT INTO players VALUES (?,?,?,?)', players)

    pstats = [
        (1,1001,'minutes',78,'DEMO',now),(1,1002,'minutes',78,'DEMO',now),
        (1,1003,'minutes',78,'DEMO',now),(1,1004,'minutes',72,'DEMO',now),
        (1,1004,'shots',3,'DEMO',now),(1,1004,'shots_on_target',2,'DEMO',now),
        (1,1101,'minutes',78,'DEMO',now),(1,1102,'minutes',78,'DEMO',now),
        (1,1103,'minutes',78,'DEMO',now),(1,1104,'minutes',78,'DEMO',now),
        (1,1104,'shots',2,'DEMO',now),
    ]
    c.executemany('INSERT INTO player_stats VALUES (?,?,?,?,?,?)', pstats)
    c.commit()
    c.close()
