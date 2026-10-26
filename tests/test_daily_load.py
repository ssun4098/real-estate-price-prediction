"""매일 적재(features/daily_load.py)를 가짜 공공데이터 API와 SQLite로 끝까지 돌려 본다."""
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from server.features.daily_load import LAND_URL, DailyLoader, recent_months
    from server.features.land_trade_table import LandTradeTable
    HAVE_DB = True
except ImportError:
    HAVE_DB = False

from server.domain.public_api import ApiError, Collector

SCHEMA = [
    """CREATE TABLE land_trade (id INTEGER PRIMARY KEY AUTOINCREMENT, lawd_cd CHAR(5), deal_ym CHAR(6), deal_date DATE,
       umd_nm VARCHAR(40), jibun VARCHAR(40), jimok VARCHAR(20), land_use VARCHAR(60), deal_amount_manwon BIGINT,
       deal_area_m2 DECIMAL(14,2), dealing_gbn VARCHAR(20), share_dealing_type VARCHAR(20), cdeal_type VARCHAR(10),
       cdeal_day VARCHAR(20), agent_sgg_nm VARCHAR(100), extra JSON)""",
    "CREATE TABLE land_trade_job (lawd_cd CHAR(5), deal_ym CHAR(6), total_count INT, loaded_rows INT, loaded_at DATETIME, PRIMARY KEY (lawd_cd, deal_ym))",
    "CREATE TABLE land_trade_fail (lawd_cd CHAR(5), deal_ym CHAR(6), error VARCHAR(500), attempts INT, last_failed_at DATETIME, PRIMARY KEY (lawd_cd, deal_ym))",
    """CREATE TABLE applyhome_apt_notice (house_manage_no VARCHAR(20), pblanc_no VARCHAR(20), house_nm VARCHAR(200),
       house_secd VARCHAR(10), house_dtl_secd VARCHAR(10), rent_secd VARCHAR(10), hssply_adres VARCHAR(300),
       rcrit_pblanc_de DATE, bsns_mby_nm VARCHAR(200), cnstrct_entrps_nm VARCHAR(200), pblanc_url VARCHAR(500),
       extra JSON, PRIMARY KEY (house_manage_no, pblanc_no))""",
    """CREATE TABLE applyhome_apt_model (house_manage_no VARCHAR(20), pblanc_no VARCHAR(20), model_no VARCHAR(20),
       house_ty VARCHAR(30), suply_ar DECIMAL(12,4), suply_hshldco INT, spsply_hshldco INT, lttot_top_amount BIGINT,
       extra JSON, PRIMARY KEY (house_manage_no, pblanc_no, model_no))""",
    "CREATE TABLE applyhome_fail (endpoint VARCHAR(20), page INT, error VARCHAR(500), attempts INT, last_failed_at DATETIME, PRIMARY KEY (endpoint, page))",
    "CREATE TABLE app_settings (`key` VARCHAR(64) PRIMARY KEY, value VARCHAR(255))",
]
NEW, BROKEN, EMPTY = recent_months(3) if HAVE_DB else ('', '', '')


def land_xml(items, code='000'):
    body = ''.join('<item>' + ''.join(f'<{k}>{v}</{k}>' for k, v in it.items()) + '</item>' for it in items)
    return ET.fromstring(f'<response><header><resultCode>{code}</resultCode></header><body><items>{body}</items>'
                         f'<totalCount>{len(items)}</totalCount></body></response>')


TRADE = {'sggCd': '41271', 'umdNm': '장상동', 'jibun': '1**', 'jimok': '답', 'landUse': '자연녹지지역',
         'dealAmount': '52,000', 'dealArea': '1200.5', 'dealYear': NEW[:4], 'dealMonth': str(int(NEW[4:])), 'dealDay': '5',
         'dealingGbn': '중개거래', 'shareDealingType': '', 'cdealType': '', 'cdealDay': '', 'estateAgentSggNm': '안산',
         'newField': 'x'}


@unittest.skipUnless(HAVE_DB, 'sqlalchemy not installed')
class DailyLoadTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + os.path.join(self.folder.name, 'load.db').replace('\\', '/'))
        with self.engine.begin() as con:
            for statement in SCHEMA:
                con.execute(text(statement))
            # 예전에 적재해 둔 자료: 실패할 달(BROKEN)의 기존 1건은 그대로 남아야 한다
            con.execute(text("INSERT INTO land_trade (lawd_cd, deal_ym, umd_nm) VALUES ('41271', :ym, '기존')"), {'ym': BROKEN})
            con.execute(text("INSERT INTO land_trade_job VALUES ('41271', :ym, 1, 1, '2026-01-01 00:00:00')"), {'ym': BROKEN})
        self.sessions = sessionmaker(self.engine)
        self.calls = []

    def tearDown(self):
        self.engine.dispose()
        self.folder.cleanup()

    def transport(self, url, params, kind):
        self.calls.append((url, dict(params)))
        if url == LAND_URL:
            ym = params['DEAL_YMD']
            if ym == BROKEN:
                raise ApiError('UPSTREAM_NETWORK', '연결 실패')
            return land_xml([TRADE, {**TRADE, 'jibun': '2**', 'cdealType': 'O'}] if ym == NEW else [])
        if url.endswith('getAPTLttotPblancDetail'):
            return {'matchCount': 1, 'data': [{'HOUSE_MANAGE_NO': '2025000001', 'PBLANC_NO': '2025000001',
                                                'HOUSE_NM': '새 단지', 'HOUSE_SECD': '01', 'HOUSE_DTL_SECD': '01',
                                                'RENT_SECD': '0', 'HSSPLY_ADRES': '경기도 안산시 상록구',
                                                'RCRIT_PBLANC_DE': '2025-09-01', 'PARCPRC_ULS_AT': 'N'}]}
        return {'matchCount': 1, 'data': [{'HOUSE_MANAGE_NO': '2025000001', 'PBLANC_NO': '2025000001', 'MODEL_NO': '01',
                                            'HOUSE_TY': '084.9700A', 'SUPLY_AR': '84.97', 'SUPLY_HSHLDCO': 100,
                                            'SPSPLY_HSHLDCO': 30, 'LTTOT_TOP_AMOUNT': '55,000', 'MNYCH_HSHLDCO': 10}]}

    def loader(self, transport=None):
        collector = Collector({'dataGoKr': 'TEST-KEY'}, transport=transport or self.transport)
        return DailyLoader(self.sessions, collector, enabled=False, months=3, delay=0, retry_wait=0)

    def test_full_run_writes_tables_like_the_original_loader(self):
        summary = self.loader().run_once()
        self.assertEqual((summary['land']['ok'], summary['land']['failed']), (2, 1))
        self.assertIsNone(summary['error'])
        with self.engine.connect() as con:
            jobs = dict(((r[0], (r[1], r[2])) for r in con.execute(text("SELECT deal_ym, total_count, loaded_rows FROM land_trade_job"))))
            self.assertEqual(jobs[NEW], (2, 2))
            self.assertEqual(jobs[EMPTY], (0, 0))
            self.assertEqual(jobs[BROKEN], (1, 1))  # 실패한 달은 이전 적재 기록 그대로
            self.assertEqual(con.execute(text("SELECT umd_nm FROM land_trade WHERE deal_ym = :ym"), {'ym': BROKEN}).scalar(), '기존')
            fail = con.execute(text("SELECT deal_ym, attempts FROM land_trade_fail")).all()
            self.assertEqual([tuple(f) for f in fail], [(BROKEN, 1)])
            row = con.execute(text("SELECT deal_amount_manwon, deal_area_m2, deal_date, agent_sgg_nm, extra FROM land_trade "
                                   "WHERE deal_ym = :ym ORDER BY id LIMIT 1"), {'ym': NEW}).first()
            self.assertEqual((row[0], float(row[1]), row[3]), (52000, 1200.5, '안산'))
            self.assertIn('newField', row[4])  # 모르는 필드는 extra 에
            self.assertEqual(con.execute(text("SELECT house_nm FROM applyhome_apt_notice")).scalar(), '새 단지')
            self.assertEqual(con.execute(text("SELECT lttot_top_amount FROM applyhome_apt_model")).scalar(), 55000)
            self.assertIn('daily_load_last', [r[0] for r in con.execute(text("SELECT `key` FROM app_settings"))])
        # 서버가 읽는 쪽(LandTradeTable)에서 바로 쓸 수 있어야 한다
        rows = LandTradeTable(self.sessions).complete('41271', NEW)['rows']
        self.assertEqual([r['eligible'] for r in rows], [True, False])  # 두 번째는 해제(취소) 거래

    def test_quota_or_key_error_stops_immediately(self):
        def quota(url, params, kind):
            self.calls.append(url)
            return land_xml([], code='22')
        summary = self.loader(quota).run_once()
        self.assertIn('22', summary['stopped'])
        self.assertEqual(len(self.calls), 1)  # 더 부르지 않는다
        self.assertEqual(summary['applyhome'], {})

    def test_api_key_never_appears_in_saved_errors(self):
        def leaky(url, params, kind):
            raise ApiError('LAND_REJECTED', '오류 serviceKey=TEST-KEY')
        from server.web import set_secrets
        set_secrets(['TEST-KEY'])
        try:
            summary = self.loader(leaky).run_once()
        finally:
            set_secrets([])
        with self.engine.connect() as con:
            errors = [r[0] for r in con.execute(text("SELECT error FROM land_trade_fail"))]
        self.assertTrue(errors)
        self.assertFalse(any('TEST-KEY' in e for e in errors))
        self.assertNotIn('TEST-KEY', str(summary))

    def test_recent_months_skip_current_month(self):
        import datetime as dt
        self.assertEqual(recent_months(3, dt.date(2026, 1, 15)), ['202512', '202511', '202510'])


if __name__ == '__main__':
    unittest.main()
