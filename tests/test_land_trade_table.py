"""토지 실거래를 직접 적재한 DB 테이블(land_trade)에서 읽는 경로. SQLite로 MySQL을 대신한다."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from server.features.land_trade_table import LandTradeTable
    HAVE_DB = True
except ImportError:
    HAVE_DB = False

from server.domain.public_api import ApiError, Collector, land_trade_row

SCHEMA = [
    """CREATE TABLE land_trade (id INTEGER PRIMARY KEY, lawd_cd CHAR(5), deal_ym CHAR(6), deal_date DATE,
       umd_nm VARCHAR(40), jibun VARCHAR(40), jimok VARCHAR(20), land_use VARCHAR(60),
       deal_amount_manwon BIGINT, deal_area_m2 DECIMAL(14,2), dealing_gbn VARCHAR(20),
       share_dealing_type VARCHAR(20), cdeal_type VARCHAR(10), cdeal_day VARCHAR(20),
       agent_sgg_nm VARCHAR(100), extra JSON)""",
    """CREATE TABLE land_trade_job (lawd_cd CHAR(5), deal_ym CHAR(6), total_count INT, loaded_rows INT,
       loaded_at DATETIME, PRIMARY KEY (lawd_cd, deal_ym))""",
    """CREATE TABLE land_trade_fail (lawd_cd CHAR(5), deal_ym CHAR(6), error VARCHAR(500), attempts INT,
       last_failed_at DATETIME, PRIMARY KEY (lawd_cd, deal_ym))""",
]
ROWS = [  # 2024년 3월 장상동: 일반 거래, 취소 거래, 지분 거래
    (1, '41271', '202403', '2024-03-05', '장상동', '1**', '답', '자연녹지지역', 52000, '1200.50', '중개거래', '', '', ''),
    (2, '41271', '202403', '2024-03-11', '장상동', '2**', '전', '자연녹지지역', 30000, '800.00', '직거래', '', 'O', '24.03.20'),
    (3, '41271', '202403', '2024-03-28', '장상동', '3**', '대', '제1종일반주거지역', 41000, '330.00', '중개거래', '지분', '', ''),
]


@unittest.skipUnless(HAVE_DB, 'sqlalchemy not installed')
class LandTradeTableTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        engine = create_engine('sqlite:///' + os.path.join(self.folder.name, 'land.db').replace('\\', '/'))
        with engine.begin() as con:
            for statement in SCHEMA:
                con.execute(text(statement))
            con.execute(text("""INSERT INTO land_trade (id, lawd_cd, deal_ym, deal_date, umd_nm, jibun, jimok, land_use,
                deal_amount_manwon, deal_area_m2, dealing_gbn, share_dealing_type, cdeal_type, cdeal_day)
                VALUES (:a,:b,:c,:d,:e,:f,:g,:h,:i,:j,:k,:l,:m,:n)"""),
                [dict(zip('abcdefghijklmn', row)) for row in ROWS])
            con.execute(text("INSERT INTO land_trade_job VALUES ('41271','202403',3,3,'2026-10-20 03:00:00')"))  # 다 받음
            con.execute(text("INSERT INTO land_trade_job VALUES ('41271','202404',5,2,'2026-10-20 03:00:00')"))  # 덜 받음
            con.execute(text("INSERT INTO land_trade_job VALUES ('41271','202406',0,0,'2026-10-20 03:00:00')"))  # 거래 0건
            con.execute(text("INSERT INTO land_trade_fail VALUES ('41271','202404','timeout',3,'2026-10-20 03:10:00')"))
        self.engine = engine
        self.table = LandTradeTable(sessionmaker(engine))

    def tearDown(self):
        self.engine.dispose()
        self.folder.cleanup()

    def test_completed_month_uses_same_verdicts_and_ids_as_api(self):
        hit = self.table.complete('41271', '202403')
        rows = hit['rows']
        self.assertEqual(hit['total'], 3)
        self.assertEqual([r['id'] for r in rows], ['land-41271-202403-1-0', 'land-41271-202403-1-1', 'land-41271-202403-1-2'])
        self.assertEqual([r['eligible'] for r in rows], [True, False, False])
        self.assertIn('취소 거래', rows[1]['exclusionReason'])
        self.assertIn('지분 거래', rows[2]['exclusionReason'])
        # 같은 거래를 API 응답 모양으로 넣었을 때와 결과가 완전히 같아야 한다.
        api_item = {'dealAmount': '52,000', 'dealArea': '1200.5', 'dealYear': '2024', 'dealMonth': '3', 'dealDay': '5',
                    'umdNm': '장상동', 'jibun': '1**', 'jimok': '답', 'landUse': '자연녹지지역', 'sggCd': '41271',
                    'shareDealingType': '', 'cdealType': '', 'cdealDay': ''}
        self.assertEqual(rows[0], land_trade_row('41271', '202403', 1, 0, api_item))

    def test_partial_or_missing_month_is_not_treated_as_zero_trades(self):
        self.assertIsNone(self.table.complete('41271', '202404'))  # 5건 중 2건만 적재
        self.assertIsNone(self.table.complete('41271', '202405'))  # 적재 기록 없음
        self.assertEqual(self.table.complete('41271', '202406')['rows'], [])  # 실제로 거래 0건

    def test_collector_table_mode_never_calls_api(self):
        def no_network(*args, **kwargs):
            raise AssertionError('table mode must not call the public API')
        collector = Collector({'dataGoKr': 'k'}, transport=no_network, land_store=self.table, land_source='table')
        self.assertEqual(len(collector.land_month('41271', '202403')), 3)
        with self.assertRaises(ApiError) as error:
            collector.land_month('41271', '202405')
        self.assertEqual(error.exception.code, 'LAND_NOT_LOADED')

    def test_summary_counts_only_completed_months(self):
        summary = self.table.summary('41271')
        self.assertEqual((summary['completedMonths'], summary['storedRows']), (2, 3))
        self.assertEqual([m['month'] for m in summary['months']], ['202403', '202406'])
        self.assertEqual([f['month'] for f in summary['failures']], ['202404'])
        self.assertEqual(self.table.summary()['completedMonths'], 2)


if __name__ == '__main__':
    unittest.main()
