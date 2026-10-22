"""Durable public land trades only. Never store keys or Geocoder responses."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sqlite3
from contextlib import contextmanager

FORMAT = 'land-pages-v1'
FIELDS = frozenset(('id','date','dong','jimok','landUse','areaM2','priceManwon',
    'cancelled','shareTrade','eligible','exclusionReason','group','sourceUrl',
    'jibun','sggCode','shareDealingType','cancellationDate','coordinateStatus',
    'sourceEligible','sourceExclusionReasons','ruleVersion'))


class LandStoreError(Exception):
    pass


class LandStore:
    def __init__(self, path, secrets=(), clock=None):
        self.path = pathlib.Path(path).resolve()
        self.secrets = tuple(s for s in secrets if s)
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as db:
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS land_complete (
                      sgg TEXT, month TEXT, format TEXT, fetched_at TEXT,
                      total INTEGER, rows_json TEXT, PRIMARY KEY(sgg,month));
                    CREATE TABLE IF NOT EXISTS land_pages (
                      sgg TEXT, month TEXT, page INTEGER, format TEXT,
                      started_at TEXT, total INTEGER, page_size INTEGER,
                      rows_json TEXT, PRIMARY KEY(sgg,month,page));
                    CREATE TABLE IF NOT EXISTS land_errors (
                      sgg TEXT, month TEXT, code TEXT, failed_at TEXT,
                      PRIMARY KEY(sgg,month));
                ''')
        except (OSError, sqlite3.Error) as exc:
            raise LandStoreError('토지 로컬 저장소를 열 수 없습니다. 저장 폴더 권한·디스크 상태를 확인하세요.') from exc

    @contextmanager
    def connect(self):
        try:db = sqlite3.connect(self.path, timeout=15)
        except sqlite3.Error as exc:raise LandStoreError('토지 로컬 저장소를 열지 못했습니다. 파일·권한 상태를 확인하세요.') from exc
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        except sqlite3.Error as exc:
            raise LandStoreError('토지 로컬 저장소를 읽거나 기록하지 못했습니다. 저장 공간·파일 상태를 확인하세요.') from exc
        finally:
            db.close()

    def key(self, sgg, month):
        if not re.fullmatch(r'\d{5}', sgg) or not re.fullmatch(r'\d{6}', month):
            raise LandStoreError('토지 저장 지역·년월 형식을 확인하세요.')
        try: dt.date(int(month[:4]),int(month[4:]),1)
        except ValueError: raise LandStoreError('유효하지 않은 저장 년월입니다.') from None

    def age(self, timestamp):
        try: return (self.clock()-dt.datetime.fromisoformat(timestamp)).total_seconds()
        except (TypeError,ValueError): return float('inf')

    def encode(self, rows):
        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
            raise LandStoreError('토지 행 형식이 올바르지 않습니다.')
        # Positive selection excludes every unrelated API response and UI flag.
        body=json.dumps([{k:v for k,v in r.items() if k in FIELDS} for r in rows],ensure_ascii=False,allow_nan=False,separators=(',',':'))
        if any(secret in body for secret in self.secrets):
            raise LandStoreError('인증정보를 포함한 자료는 로컬 저장소에 기록할 수 없습니다.')
        return body

    def decode(self, body):
        try:
            rows=json.loads(body)
            if not isinstance(rows,list) or any(not isinstance(r,dict) or set(r)-FIELDS for r in rows):raise ValueError()
            return rows
        except (ValueError,TypeError):
            raise LandStoreError('저장된 토지자료 형식이 손상되었습니다. 원본 보존 후 저장소 점검이 필요합니다.') from None

    def complete(self, sgg, month, force=False):
        self.key(sgg,month)
        with self.connect() as db:
            row=db.execute('SELECT * FROM land_complete WHERE sgg=? AND month=?',(sgg,month)).fetchone()
            error=db.execute('SELECT failed_at FROM land_errors WHERE sgg=? AND month=?',(sgg,month)).fetchone()
        if row is None or row['format']!=FORMAT:return None
        if error and error['failed_at']>=row['fetched_at']:return None
        recent=month >= (self.clock().date().replace(day=1)-dt.timedelta(days=1)).strftime('%Y%m')
        ttl=3600 if recent else 30*86400
        if force or not 0<=self.age(row['fetched_at'])<ttl:return None
        values=self.decode(row['rows_json'])
        if len(values)!=row['total']:raise LandStoreError('저장된 토지 행 수가 수집 완료 기록과 다릅니다.')
        return {'rows':values,'fetchedAt':row['fetched_at'],'total':row['total']}

    def pending(self, sgg, month, force=False):
        self.key(sgg,month)
        with self.connect() as db:
            pages=db.execute('SELECT * FROM land_pages WHERE sgg=? AND month=? ORDER BY page',(sgg,month)).fetchall()
        if force or not pages or any(p['format']!=FORMAT or not 0<=self.age(p['started_at'])<86400 for p in pages):return []
        if [p['page'] for p in pages]!=list(range(1,len(pages)+1)):return []
        if len({(p['total'],p['page_size'],p['started_at']) for p in pages})!=1:return []
        return [dict(p)|{'rows':self.decode(p['rows_json'])} for p in pages]

    def save_page(self, sgg, month, page, rows, total, page_size):
        self.key(sgg,month)
        body=self.encode(rows)
        with self.connect() as db:
            if page==1:
                db.execute('DELETE FROM land_pages WHERE sgg=? AND month=?',(sgg,month))
                started=self.clock().isoformat()
            else:
                first=db.execute('SELECT started_at,total,page_size FROM land_pages WHERE sgg=? AND month=? AND page=1',(sgg,month)).fetchone()
                if first is None or (first['total'],first['page_size'])!=(total,page_size):raise LandStoreError('토지 페이지의 전체 건수가 변경돼 다시 조회해야 합니다.')
                started=first['started_at']
            db.execute('INSERT OR REPLACE INTO land_pages VALUES (?,?,?,?,?,?,?,?)',
                (sgg,month,page,FORMAT,started,total,page_size,body))

    def finish(self, sgg, month, rows, total):
        if len(rows)!=total:raise LandStoreError('미완료 자료를 토지 수집 완료로 저장할 수 없습니다.')
        body=self.encode(rows);stamp=self.clock().isoformat()
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO land_complete VALUES (?,?,?,?,?,?)',(sgg,month,FORMAT,stamp,total,body))
            db.execute('DELETE FROM land_pages WHERE sgg=? AND month=?',(sgg,month))
            db.execute('DELETE FROM land_errors WHERE sgg=? AND month=?',(sgg,month))
        return stamp

    def failure(self,sgg,month,code):
        self.key(sgg,month)
        # Error messages/URLs can contain credentials; persist only our own code.
        if not re.fullmatch(r'[A-Z_]{1,64}',code):code='UPSTREAM_ERROR'
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO land_errors VALUES (?,?,?,?)',(sgg,month,code,self.clock().isoformat()))

    def summary(self,sgg=None):
        if sgg is not None and not re.fullmatch(r'\d{5}',sgg):raise LandStoreError('시군구 코드는 5자리여야 합니다.')
        where,params=(' WHERE sgg=?',(sgg,)) if sgg else ('',())
        with self.connect() as db:
            months=[dict(r) for r in db.execute('SELECT sgg,month,total,fetched_at FROM land_complete'+where+' ORDER BY sgg,month',params)]
            pending=[dict(r) for r in db.execute('SELECT sgg,month,MAX(page) AS saved_pages,MAX(total) AS total FROM land_pages'+where+' GROUP BY sgg,month',params)]
            failures=[dict(r) for r in db.execute('SELECT * FROM land_errors'+where+' ORDER BY sgg,month',params)]
        return {'enabled':True,'fileName':self.path.name,'completedMonths':len(months),
            'storedRows':sum(r['total'] for r in months),'months':months,
            'pending':pending,'failures':failures,'policy':'recent_1h_history_30d',
            'note':'토지 원자료만 로컬 보관 · 인증키·Geocoder 위치자료 제외'}
