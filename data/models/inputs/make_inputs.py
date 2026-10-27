"""팀원 전달 자료(data/) → 서버가 읽는 작은 CSV 4개 (이 폴더). 자료를 새로 받았을 때만 한 번 실행한다.

    pip install pandas pyarrow        # 이 변환에만 필요 (서버에는 필요 없음)
    python make_inputs.py <전달자료 폴더> <이 폴더>
    예) python make_inputs.py C:/받은자료/개발자전달_CatBoost23_20261027 data/models/inputs
"""
import csv, gzip, sys
from pathlib import Path
import pandas as pd
PKG, OUT = Path(sys.argv[1]), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

h = pd.read_parquet(PKG / "data/land_price_monthly.parquet")
h = h.sort_values(["land_group_key", "month"])
with gzip.open(OUT / "group_history.csv.gz", "wt", encoding="utf-8", newline="", compresslevel=9, ) as f:
    w = csv.writer(f); w.writerow(["land_group_key", "month", "unit_price_won_m2", "median_area_m2", "trade_count"])
    for r in h.itertuples(index=False):
        w.writerow([r.land_group_key, r.month.strftime("%Y-%m"), repr(float(r.unit_price_won_m2)), repr(float(r.median_area_m2)), int(r.trade_count)])

r = pd.read_csv(PKG / "data/region_map.csv", dtype=str, keep_default_na=False)
r[["lawd_cd", "sido_nm", "sigungu_nm", "입력지역키", "지역대응방법"]].to_csv(OUT / "region_map.csv", index=False, encoding="utf-8")

m = pd.read_csv(PKG / "data/macro_regional_month.csv", dtype=str, keep_default_na=False)
m["월"] = m["월"].str[:7]
# COFIX 열은 일부러 뺀다: 공시일 기준으로 cofix_release_history 에서 고른다 (입력계약 문서).
m[["지역키", "월", "지가변동률", "건축허가면적", "경제심리지수_원계열", "동행종합지수_전월비", "M1_평잔_원계열", "비은행_주택관련대출"]] \
    .to_csv(OUT / "macro_region_month.csv", index=False, encoding="utf-8")

c = pd.read_csv(PKG / "data/cofix_release_history.csv", dtype=str, keep_default_na=False)
c["월"] = c["월"].str[:7]; c["COFIX_공시일"] = c["COFIX_공시일"].str[:10]
c[["월", "신규취급액기준_COFIX", "COFIX_공시일"]].to_csv(OUT / "cofix_release.csv", index=False, encoding="utf-8")
