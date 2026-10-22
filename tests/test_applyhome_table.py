"""청약홈 분양정보를 직접 적재한 DB 테이블(applyhome_apt_*)에서 읽는 경로. SQLite로 MySQL을 대신한다."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from server.features.applyhome_table import ApplyhomeTable
    HAVE_DB = True
except ImportError:
    HAVE_DB = False

from server.domain.public_api import ApiError, Collector

SCHEMA = [
    """CREATE TABLE applyhome_apt_notice (house_manage_no VARCHAR(20), pblanc_no VARCHAR(20), house_nm VARCHAR(200),
       house_secd VARCHAR(10), house_dtl_secd VARCHAR(10), rent_secd VARCHAR(10), hssply_adres VARCHAR(300),
       rcrit_pblanc_de DATE, bsns_mby_nm VARCHAR(200), cnstrct_entrps_nm VARCHAR(200), pblanc_url VARCHAR(500),
       extra JSON, PRIMARY KEY (house_manage_no, pblanc_no))""",
    """CREATE TABLE applyhome_apt_model (house_manage_no VARCHAR(20), pblanc_no VARCHAR(20), model_no VARCHAR(20),
       house_ty VARCHAR(30), suply_ar DECIMAL(12,4), suply_hshldco INT, spsply_hshldco INT, lttot_top_amount BIGINT,
       extra JSON, PRIMARY KEY (house_manage_no, pblanc_no, model_no))""",
]
NOTICES = [
    ('2023000001', '2023000001', '안산 A단지', '01', '01', '0', '경기도 안산시 상록구 장상동 100', '2023-05-10',
     '시행사', '시공사', 'https://example.test/1', json.dumps({'PARCPRC_ULS_AT': 'N', 'HOUSE_NM': '원본 이름'})),
    ('2024000002', '2024000002', '안산 B단지', '01', '01', '0', '경기도 안산시 단원구 고잔동 1', '2024-02-01',
     '', '', '', None),
    ('2024000003', '2024000003', '공공 C단지', '01', '03', '0', '경기도 안산시 상록구 장상동 200', '2024-03-01',
     '', '', '', None),  # 민영이 아님 (상세구분 03)
]
MODELS = [
    ('2023000001', '2023000001', '01', '084.9700A', '84.9700', 120, 40, 52000, json.dumps({'MNYCH_HSHLDCO': 10})),
    ('2023000001', '2023000001', '02', '059.9900A', '59.9900', 80, 20, 39000, None),
]


@unittest.skipUnless(HAVE_DB, 'sqlalchemy not installed')
class ApplyhomeTableTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        engine = create_engine('sqlite:///' + os.path.join(self.folder.name, 'apt.db').replace('\\', '/'))
        with engine.begin() as con:
            for statement in SCHEMA:
                con.execute(text(statement))
            con.execute(text("INSERT INTO applyhome_apt_notice VALUES (:a,:b,:c,:d,:e,:f,:g,:h,:i,:j,:k,:l)"),
                        [dict(zip('abcdefghijkl', row)) for row in NOTICES])
            con.execute(text("INSERT INTO applyhome_apt_model VALUES (:a,:b,:c,:d,:e,:f,:g,:h,:i)"),
                        [dict(zip('abcdefghi', row)) for row in MODELS])
        self.engine = engine
        self.table = ApplyhomeTable(sessionmaker(engine))

    def tearDown(self):
        self.engine.dispose()
        self.folder.cleanup()

    def test_notice_conditions_match_api_semantics(self):
        private = {'cond[HOUSE_SECD::EQ]': '01', 'cond[HOUSE_DTL_SECD::EQ]': '01'}
        period = {**private, 'cond[RCRIT_PBLANC_DE::GTE]': '2023-01-01', 'cond[RCRIT_PBLANC_DE::LTE]': '2024-12-31'}
        self.assertEqual([r['HOUSE_MANAGE_NO'] for r in self.table.query('getAPTLttotPblancDetail', period)],
                         ['2023000001', '2024000002'])
        dong = {**period, 'cond[HSSPLY_ADRES::LIKE]': '장상동'}
        self.assertEqual([r['HOUSE_NM'] for r in self.table.query('getAPTLttotPblancDetail', dong)], ['안산 A단지'])
        self.assertEqual(self.table.count({**private, 'cond[RCRIT_PBLANC_DE::LT]': '2024-01-01'}), 1)

    def test_rows_look_like_api_rows(self):
        row = self.table.query('getAPTLttotPblancDetail', {'cond[HOUSE_MANAGE_NO::EQ]': '2023000001'})[0]
        self.assertEqual(row['RCRIT_PBLANC_DE'], '2023-05-10')  # 날짜 → 문자열
        self.assertEqual(row['HOUSE_NM'], '안산 A단지')          # 열 값이 extra 보다 우선
        self.assertEqual(row['PARCPRC_ULS_AT'], 'N')             # extra 의 원본 필드도 함께
        models = self.table.query('getAPTLttotPblancMdl', {'cond[HOUSE_MANAGE_NO::EQ]': '2023000001',
                                                           'cond[PBLANC_NO::EQ]': '2023000001'})
        self.assertEqual([m['MODEL_NO'] for m in models], ['01', '02'])
        self.assertEqual((float(models[0]['SUPLY_AR']), models[0]['LTTOT_TOP_AMOUNT']), (84.97, 52000))
        self.assertEqual(models[0]['MNYCH_HSHLDCO'], 10)
        json.dumps(models)  # 응답으로 보낼 수 있어야 한다 (Decimal 없음)

    def test_unknown_condition_is_rejected_not_ignored(self):
        with self.assertRaises(ApiError):
            self.table.query('getAPTLttotPblancDetail', {'cond[SUBSCRPT_AREA_CODE::EQ]': '100'})
        with self.assertRaises(ApiError):
            self.table.query('getSomethingElse', {})

    def test_collector_uses_table_instead_of_api(self):
        def no_network(*args, **kwargs):
            raise AssertionError('table mode must not call the public API')
        collector = Collector({'dataGoKr': 'k'}, transport=no_network)
        collector.applyhome_table = self.table
        rows = collector.odcloud('getAPTLttotPblancDetail', {'cond[HOUSE_SECD::EQ]': '01', 'cond[HOUSE_DTL_SECD::EQ]': '01'})
        self.assertEqual(len(rows), 2)
        self.assertEqual(collector._coverage_count({'cond[RCRIT_PBLANC_DE::GTE]': '2024-01-01'}), 1)


if __name__ == '__main__':
    unittest.main()
