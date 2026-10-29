"""주소 검색(/api/address → Collector.address) 테스트. 실제 API는 부르지 않는다.

검색어에 해당하는 주소를 5건·20건으로 자르지 않고 모두 돌려주는지,
좌표는 앞의 몇 건만 미리 찾는지(나머지는 화면에서 고를 때 다시 검색) 확인한다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.domain import public_api  # noqa: E402
from server.domain.public_api import Collector  # noqa: E402


def juso_rows(start, count):
    return [{"roadAddr": f"경기도 안산시 상록구 장상길 {i}", "jibunAddr": f"경기도 안산시 상록구 장상동 {i}",
             "admCd": "4127112100", "siNm": "경기도", "sggNm": "안산시 상록구", "emdNm": "장상동", "liNm": ""}
            for i in range(start, start + count)]


class AddressSearchTests(unittest.TestCase):
    def collector(self, total):
        self.pages = []

        def transport(url, params, kind):
            page, size = params["currentPage"], params["countPerPage"]
            self.pages.append(page)
            start = (page - 1) * size
            rows = juso_rows(start + 1, max(0, min(size, total - start)))
            return {"results": {"common": {"errorCode": "0", "totalCount": str(total)}, "juso": rows}}

        collector = Collector({"juso": "k", "vworldGeocoder": "g"}, transport=transport)
        self.geocoded = []

        def geocode(address):
            self.geocoded.append(address)
            return {"coordinateReturned": True, "lon": 126.9, "lat": 37.3}
        collector.geocode = geocode
        return collector

    def test_returns_every_matching_address_not_just_five(self):
        result = self.collector(37).address("장상동", geocode=True)
        self.assertEqual(len(result["candidates"]), 37)
        self.assertEqual((result["totalCount"], result["truncated"]), (37, False))
        self.assertEqual(self.pages, [1])

    def test_reads_all_pages(self):
        result = self.collector(250).address("상록구", geocode=True)
        self.assertEqual(len(result["candidates"]), 250)
        self.assertEqual(self.pages, [1, 2, 3])
        self.assertEqual(len({c["address"] for c in result["candidates"]}), 250)

    def test_only_first_five_get_coordinates_up_front(self):
        result = self.collector(12).address("장상동", geocode=True)
        with_point = [c for c in result["candidates"] if c["lon"] is not None]
        self.assertEqual(len(with_point), 5)
        self.assertEqual(len(self.geocoded), 5)

    def test_very_broad_search_stops_at_limit_and_says_so(self):
        result = self.collector(public_api.ADDRESS_LIMIT + 500).address("경기도", geocode=True)
        self.assertEqual(len(result["candidates"]), public_api.ADDRESS_LIMIT)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(self.pages), public_api.ADDRESS_LIMIT // 100)


if __name__ == "__main__":
    unittest.main()
