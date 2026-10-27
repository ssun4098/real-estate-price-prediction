-- 조회 속도용 인덱스 (토지 실거래·청약홈 테이블)
--
-- 실행:  mysql -uroot -p land_trade < deploy/mysql-indexes.sql
--   Docker:  docker exec -i land-mysql mysql -uroot -p land_trade < deploy/mysql-indexes.sql
--   (land_trade 자리에 .env 의 MYSQL_DATABASE 값)
--
-- 안전장치
--   - 같은 열 순서로 시작하는 인덱스(기본키 포함)가 이미 있으면 만들지 않고 건너뛴다. 여러 번 실행해도 된다.
--   - 테이블이 없으면 건너뛴다. 자료는 바꾸지 않는다 (인덱스만 추가).
--   - ALGORITHM=INPLACE, LOCK=NONE: 만드는 동안에도 조회·적재가 멈추지 않는다.
--   - land_trade(약 760만 행)는 수십 초~몇 분, 디스크 약 200MB 가 더 든다.
--
-- 효과 (같은 크기 760만 행으로 측정): 비교사례 60개월 조회 약 220초 → 0.4초.
--
-- 되돌리기:  ALTER TABLE <테이블> DROP INDEX <인덱스이름>;

SET NAMES utf8mb4;  -- 한글 안내 문구가 깨지지 않게

-- land_trade (lawd_cd, deal_ym)
--   토지 실거래 비교사례: 시군구·월마다 1번씩, 조회 1번에 60번 실행 (WHERE lawd_cd=? AND deal_ym=? ORDER BY id). 매일 적재의 DELETE 도 같은 조건
SET @has_table := (SELECT COUNT(*) FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_name = 'land_trade');
SET @has_index := (SELECT COUNT(*) FROM (
                     SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index) AS cols
                     FROM information_schema.statistics
                     WHERE table_schema = DATABASE() AND table_name = 'land_trade'
                     GROUP BY index_name) AS t
                   WHERE CONCAT(t.cols, ',') LIKE 'lawd_cd,deal_ym,%');
SET @sql := CASE
  WHEN @has_table = 0 THEN 'SELECT ''land_trade: 테이블 없음 · 건너뜀'' AS result'
  WHEN @has_index > 0 THEN 'SELECT ''land_trade: (lawd_cd, deal_ym) 인덱스 이미 있음 · 건너뜀'' AS result'
  ELSE 'ALTER TABLE land_trade ADD INDEX ix_land_trade_sgg_month (lawd_cd, deal_ym), ALGORITHM=INPLACE, LOCK=NONE'
END;
SELECT IF(@has_table > 0 AND @has_index = 0, 'land_trade: ix_land_trade_sgg_month (lawd_cd, deal_ym) 만드는 중…', NULL) AS step;
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- land_trade_job (lawd_cd, deal_ym)
--   월별 적재 완료 확인: 조회 1번에 60번 (보통 기본키가 이미 이 순서라 건너뜀)
SET @has_table := (SELECT COUNT(*) FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_name = 'land_trade_job');
SET @has_index := (SELECT COUNT(*) FROM (
                     SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index) AS cols
                     FROM information_schema.statistics
                     WHERE table_schema = DATABASE() AND table_name = 'land_trade_job'
                     GROUP BY index_name) AS t
                   WHERE CONCAT(t.cols, ',') LIKE 'lawd_cd,deal_ym,%');
SET @sql := CASE
  WHEN @has_table = 0 THEN 'SELECT ''land_trade_job: 테이블 없음 · 건너뜀'' AS result'
  WHEN @has_index > 0 THEN 'SELECT ''land_trade_job: (lawd_cd, deal_ym) 인덱스 이미 있음 · 건너뜀'' AS result'
  ELSE 'ALTER TABLE land_trade_job ADD INDEX ix_land_trade_job_sgg_month (lawd_cd, deal_ym), ALGORITHM=INPLACE, LOCK=NONE'
END;
SELECT IF(@has_table > 0 AND @has_index = 0, 'land_trade_job: ix_land_trade_job_sgg_month (lawd_cd, deal_ym) 만드는 중…', NULL) AS step;
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- land_trade_fail (lawd_cd, deal_ym)
--   적재 실패 기록 갱신 (매일 적재)
SET @has_table := (SELECT COUNT(*) FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_name = 'land_trade_fail');
SET @has_index := (SELECT COUNT(*) FROM (
                     SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index) AS cols
                     FROM information_schema.statistics
                     WHERE table_schema = DATABASE() AND table_name = 'land_trade_fail'
                     GROUP BY index_name) AS t
                   WHERE CONCAT(t.cols, ',') LIKE 'lawd_cd,deal_ym,%');
SET @sql := CASE
  WHEN @has_table = 0 THEN 'SELECT ''land_trade_fail: 테이블 없음 · 건너뜀'' AS result'
  WHEN @has_index > 0 THEN 'SELECT ''land_trade_fail: (lawd_cd, deal_ym) 인덱스 이미 있음 · 건너뜀'' AS result'
  ELSE 'ALTER TABLE land_trade_fail ADD INDEX ix_land_trade_fail_sgg_month (lawd_cd, deal_ym), ALGORITHM=INPLACE, LOCK=NONE'
END;
SELECT IF(@has_table > 0 AND @has_index = 0, 'land_trade_fail: ix_land_trade_fail_sgg_month (lawd_cd, deal_ym) 만드는 중…', NULL) AS step;
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- applyhome_apt_notice (house_secd, house_dtl_secd, rcrit_pblanc_de)
--   분양 공고: APT(01·01) + 모집공고일 기간으로 찾기·개수 세기 (조회 1번에 여러 번)
SET @has_table := (SELECT COUNT(*) FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_name = 'applyhome_apt_notice');
SET @has_index := (SELECT COUNT(*) FROM (
                     SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index) AS cols
                     FROM information_schema.statistics
                     WHERE table_schema = DATABASE() AND table_name = 'applyhome_apt_notice'
                     GROUP BY index_name) AS t
                   WHERE CONCAT(t.cols, ',') LIKE 'house_secd,house_dtl_secd,rcrit_pblanc_de,%');
SET @sql := CASE
  WHEN @has_table = 0 THEN 'SELECT ''applyhome_apt_notice: 테이블 없음 · 건너뜀'' AS result'
  WHEN @has_index > 0 THEN 'SELECT ''applyhome_apt_notice: (house_secd, house_dtl_secd, rcrit_pblanc_de) 인덱스 이미 있음 · 건너뜀'' AS result'
  ELSE 'ALTER TABLE applyhome_apt_notice ADD INDEX ix_applyhome_notice_type_date (house_secd, house_dtl_secd, rcrit_pblanc_de), ALGORITHM=INPLACE, LOCK=NONE'
END;
SELECT IF(@has_table > 0 AND @has_index = 0, 'applyhome_apt_notice: ix_applyhome_notice_type_date (house_secd, house_dtl_secd, rcrit_pblanc_de) 만드는 중…', NULL) AS step;
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- applyhome_apt_model (house_manage_no, pblanc_no)
--   공고별 주택형: 단지(공고)마다 1번, 조회 1번에 수십~수백 번 (보통 기본키가 이미 이 순서라 건너뜀)
SET @has_table := (SELECT COUNT(*) FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_name = 'applyhome_apt_model');
SET @has_index := (SELECT COUNT(*) FROM (
                     SELECT GROUP_CONCAT(column_name ORDER BY seq_in_index) AS cols
                     FROM information_schema.statistics
                     WHERE table_schema = DATABASE() AND table_name = 'applyhome_apt_model'
                     GROUP BY index_name) AS t
                   WHERE CONCAT(t.cols, ',') LIKE 'house_manage_no,pblanc_no,%');
SET @sql := CASE
  WHEN @has_table = 0 THEN 'SELECT ''applyhome_apt_model: 테이블 없음 · 건너뜀'' AS result'
  WHEN @has_index > 0 THEN 'SELECT ''applyhome_apt_model: (house_manage_no, pblanc_no) 인덱스 이미 있음 · 건너뜀'' AS result'
  ELSE 'ALTER TABLE applyhome_apt_model ADD INDEX ix_applyhome_model_notice (house_manage_no, pblanc_no), ALGORITHM=INPLACE, LOCK=NONE'
END;
SELECT IF(@has_table > 0 AND @has_index = 0, 'applyhome_apt_model: ix_applyhome_model_notice (house_manage_no, pblanc_no) 만드는 중…', NULL) AS step;
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 결과 확인: 아래 두 줄의 type 이 ALL/index 가 아니라 ref 이고 rows 가 수백 이하면 정상
-- EXPLAIN SELECT id FROM land_trade WHERE lawd_cd = '41271' AND deal_ym = '202606' ORDER BY id;
-- EXPLAIN SELECT * FROM applyhome_apt_model WHERE house_manage_no = '2024000001' AND pblanc_no = '2024000001';
