"""Local-only PF Study HTTP server and immutable snapshot export."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import re
import sys
import threading
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pf_api import ApiError, Collector, DEFAULT_DOMAIN
from pf_engine import analyze, validate_snapshot, _safe_tree
from pf_config import KEY_FIELDS, read_keys
from pf_persistence import export_snapshot, portfolio_capture_tree, PORTFOLIO_POLICY
from pf_survey import site_survey, enrich_parcel
from pf_land_store import LandStore, LandStoreError

MAX_JSON = 64 * 1024 * 1024
HTML_SNAPSHOT_MARKER = "<!--PF_SNAPSHOT-->"


def render_html(template, snapshot=None, portfolio=None, default_sample_id=None):
    """Embed inert JSON safely before app scripts; prevents </script> breakout."""
    portfolio = portfolio or []
    default_sample = next((item for item in portfolio if item.get('id') == default_sample_id), None)
    # The chosen initial example is stable; saving another working analysis
    # must never replace it implicitly.
    if default_sample:
        snapshot = default_sample['snapshot']
    else:
        default_sample_id = None
    def inert_json(value):
        data=json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",",":"))
        return data.replace("&","\\u0026").replace("<","\\u003c").replace(">","\\u003e").replace("\u2028","\\u2028").replace("\u2029","\\u2029")
    script="<script>window.__PF_SNAPSHOT__="+inert_json(snapshot)+";window.__PF_PORTFOLIO__="+inert_json(portfolio)+";window.__PF_DEFAULT_SAMPLE_ID__="+inert_json(default_sample_id)+";</script>"
    # Browsers sniff only the first 1024 bytes for charset. A large JSON payload
    # before the original meta tag corrupts Korean saved data in file/static mode.
    charset='<meta charset="utf-8">'
    if HTML_SNAPSHOT_MARKER in template:
        rendered=template.replace(HTML_SNAPSHOT_MARKER,script)
        return rendered.replace('<head>','<head>'+charset,1) if '<head>' in rendered else charset+rendered
    if "<head>" in template:return template.replace("<head>","<head>"+charset+script,1)
    return charset+script+template


def atomic_text(path, content):
    temporary=path.with_name(path.name+".tmp-"+uuid.uuid4().hex)
    try:
        temporary.write_text(content,encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class SnapshotStore:
    def __init__(self,directory,template,secrets=(),*,bundled_portfolio=None,bundled_default_id=None):
        self.directory=pathlib.Path(directory).resolve()
        self.snapshots=self.directory/"pf-study-v6-snapshots"
        self.template=template
        self.secrets=tuple(x for x in secrets if x)
        self.lock=threading.RLock()
        self.portfolio=PortfolioStore(self.directory,self.secrets,bundled_entries=bundled_portfolio,bundled_default_id=bundled_default_id)

    def initialize(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        self.snapshots.mkdir(parents=True,exist_ok=True)
        if not (self.directory/"V6.html").exists():
            self.write_html()

    def write_html(self, snapshot=None):
        with self.lock:
            catalog = self.portfolio.entries()
            atomic_text(self.directory/"V6.html", render_html(self.template, snapshot, catalog, self.portfolio.default_id()))

    def validate(self,snapshot):
        serialized=json.dumps(snapshot,ensure_ascii=False,allow_nan=False)
        if len(serialized.encode("utf-8"))>MAX_JSON:raise ValueError("결과 파일이 64MB를 초과했습니다.")
        for secret in self.secrets:
            if secret in serialized or urllib.parse.quote(secret,safe="") in serialized:
                raise ValueError("인증키를 포함한 자료는 저장할 수 없습니다.")
        return export_snapshot(validate_snapshot(snapshot))

    def _paths(self,ident):
        return (self.directory/("pf-study-v6-"+ident+".json"),self.snapshots/(ident+".json"))

    def save(self,snapshot,*,write_html=True):
        snapshot=self.validate(snapshot)
        with self.lock:
            ident=str(snapshot.get("id", ""))
            if not re.fullmatch(r"pf-[A-Za-z0-9_-]{1,100}",ident):ident="pf-"+uuid.uuid4().hex
            if any(path.exists() for path in self._paths(ident)):
                ident="pf-"+uuid.uuid4().hex
                snapshot["createdAt"]=dt.datetime.now(dt.timezone.utc).isoformat()
            snapshot["id"]=ident
            body=json.dumps(snapshot,ensure_ascii=False,allow_nan=False,indent=2)
            path=self._paths(ident)[0]
            atomic_text(path,body+"\n")
            if write_html:self.write_html(snapshot)
            return {"id":ident,"fileName":path.name,"filePath":str(path),"htmlFileName":"V6.html" if write_html else None,"snapshot":snapshot,
                    "exportNotice":"Geocoder 실시간 위치·반경 분양사례 및 의존 수지는 저장에서 제외했습니다."}

    def read(self,ident):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}",ident):raise ValueError("결과 식별자가 올바르지 않습니다.")
        path=next((p for p in self._paths(ident) if p.is_file()),self._paths(ident)[0])
        if not path.is_file():raise ApiError("NOT_FOUND","저장된 분석을 찾을 수 없습니다.",404)
        if path.stat().st_size>MAX_JSON:raise ValueError("결과 파일이 64MB를 초과했습니다.")
        return self.validate(json.loads(path.read_text(encoding="utf-8")))

    def list(self):
        result=[]
        identities={path.stem.removeprefix("pf-study-v6-") for path in self.directory.glob("pf-study-v6-pf-*.json")}
        identities.update(path.stem for path in self.snapshots.glob("*.json"))
        for ident in identities:
            try:
                s=self.read(ident)
                result.append({k:s.get(k) for k in ("id","name","scenario","createdAt")})
            except (ValueError,ApiError,OSError):continue
        return sorted(result,key=lambda x:x.get("createdAt") or "",reverse=True)


class PortfolioStore:
    """Immutable, explicitly captured results for the portfolio sample shelf."""

    def __init__(self, directory, secrets=(), *, bundled_entries=None, bundled_default_id=None):
        self.directory = pathlib.Path(directory).resolve() / 'pf-study-v6-portfolio'
        self.secrets = tuple(value for value in secrets if value)
        self.lock = threading.RLock()
        self.bundled = {}
        for item in bundled_entries or []:
            # Embedded samples use the same v1 envelope as existing captures.
            clean = self.checked(item)
            self.validate_item(clean, clean.get('id'))
            self.bundled[clean['id']] = clean
        self.bundled_default_id = bundled_default_id if bundled_default_id in self.bundled else None

    def checked(self, value):
        # Drop only transport/private fields. Do not remove the actual
        # comparable rows, query status, coordinates or calculated results.
        value = _safe_tree(portfolio_capture_tree(value))
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode('utf-8')) > MAX_JSON:
            raise ValueError('결과 파일이 64MB를 초과했습니다.')
        for secret in self.secrets:
            if secret in serialized or urllib.parse.quote(secret, safe='') in serialized:
                raise ValueError('인증키를 포함한 자료는 저장할 수 없습니다.')
        return value

    def path(self, ident):
        if not re.fullmatch(r'pf-sample-[a-f0-9]{32}', str(ident)):
            raise ValueError('저장한 분석 식별자가 올바르지 않습니다.')
        return self.directory / (ident + '.json')

    def save(self, body):
        if not isinstance(body, dict) or not isinstance(body.get('snapshot'), dict):
            raise ValueError('저장할 분석 결과가 필요합니다.')
        clean = self.checked(body)
        candidate = clean['snapshot']
        prior_results = candidate.get('results')
        validation = prior_results.get('validation') if isinstance(prior_results, dict) else None
        if isinstance(validation, dict) and validation.get('mode') == 'browser-preview':
            # A browser working copy may intentionally contain held fields.
            # Recompute every result on the server using the same partial
            # validation mode as /api/analyze; never trust browser totals.
            validation['mode'] = 'partial'
        snapshot = validate_snapshot(candidate)
        name = str(clean.get('name') or snapshot.get('name') or '저장한 분석').strip()
        if not name or len(name) > 120:
            raise ValueError('분석 이름은 1~120자로 입력하세요.')
        display = clean.get('displayState') or {}
        if not isinstance(display, dict):
            raise ValueError('화면 자료는 객체여야 합니다.')
        display = {key: display[key] for key in ('survey', 'address', 'viewState', 'mapView') if key in display}
        if 'address' in display and not isinstance(display['address'], str):
            raise ValueError('화면 주소는 문자열이어야 합니다.')
        if 'survey' in display and display['survey'] is not None and not isinstance(display['survey'], dict):
            raise ValueError('입지 조사 자료는 객체여야 합니다.')
        if 'viewState' in display:
            view = display['viewState']
            if (not isinstance(view, dict) or view.get('main') not in ('finance', 'survey') or
                    view.get('tab') not in ('parcels', 'regulation', 'location', 'development')):
                raise ValueError('저장할 화면 탭이 올바르지 않습니다.')
            display['viewState'] = {key: view[key] for key in ('main', 'tab')}
        if 'mapView' in display:
            view = display['mapView']
            limits = {'lon': (-180, 180), 'lat': (-85.05112878, 85.05112878), 'z': (0, 22)}
            if not isinstance(view, dict) or any(
                    not isinstance(view.get(key), (int, float)) or isinstance(view.get(key), bool) or
                    not math.isfinite(view[key]) or not low <= view[key] <= high
                    for key, (low, high) in limits.items()):
                raise ValueError('저장할 지도 위치가 올바르지 않습니다.')
            display['mapView'] = {key: view[key] for key in limits}
        item = self.checked({
            'id': 'pf-sample-' + uuid.uuid4().hex,
            'name': name,
            'capturedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
            'readOnly': True,
            'persistencePolicy': PORTFOLIO_POLICY,
            'snapshot': snapshot,
            'displayState': display,
        })
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path(item['id'])
            while path.exists():
                item['id'] = 'pf-sample-' + uuid.uuid4().hex
                path = self.path(item['id'])
            atomic_text(path, json.dumps(item, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
        return {**item, 'fileName': path.name, 'filePath': str(path)}

    def read(self, ident):
        path = self.path(ident)
        if not path.is_file():
            if ident in self.bundled:
                return self.checked(self.bundled[ident])
            raise ApiError('NOT_FOUND', '저장한 분석을 찾을 수 없습니다.', 404)
        if path.stat().st_size > MAX_JSON:
            raise ValueError('결과 파일이 64MB를 초과했습니다.')
        item = self.checked(json.loads(path.read_text(encoding='utf-8')))
        return self.validate_item(item, ident)

    def validate_item(self, item, ident):
        self.path(ident)
        if (not isinstance(item, dict) or item.get('id') != ident or
                item.get('persistencePolicy') != PORTFOLIO_POLICY or
                item.get('readOnly') is not True or
                not isinstance(item.get('snapshot'), dict) or
                not isinstance(item['snapshot'].get('inputs'), dict) or
                not isinstance(item['snapshot'].get('results'), dict)):
            raise ValueError('저장한 분석의 형식이 올바르지 않습니다.')
        try:
            dt.datetime.fromisoformat(str(item.get('capturedAt')).replace('Z', '+00:00'))
        except ValueError:
            raise ValueError('저장 시각이 올바르지 않습니다.') from None
        # Do not run a newer engine over a historical, validated capture.
        return item

    def default_id(self):
        path = self.directory / 'default.json'
        if not path.is_file():
            return self.bundled_default_id
        try:
            if path.stat().st_size > 1024:
                return None
            ident = json.loads(path.read_text(encoding='utf-8')).get('id')
            self.read(ident)
            return ident
        except (ValueError, ApiError, OSError, AttributeError, TypeError):
            # An invalid explicit pointer does not silently select another sample.
            return None

    def set_default(self, ident):
        with self.lock:
            self.read(ident)
            self.directory.mkdir(parents=True, exist_ok=True)
            atomic_text(self.directory / 'default.json', json.dumps({'id': ident}, ensure_ascii=False) + '\n')
        return {'id': ident}

    def entries(self):
        items = dict(self.bundled)
        for path in self.directory.glob('pf-sample-*.json'):
            try:
                item = self.read(path.stem)
                items[item['id']] = item
            except (ValueError, ApiError, OSError, KeyError, TypeError):
                continue
        return sorted(items.values(), key=lambda item: item['capturedAt'], reverse=True)

    def list(self):
        items = []
        default_id = self.default_id()
        for item in self.entries():
            try:
                snapshot = item['snapshot']
                items.append({
                    'id': item['id'], 'name': item['name'], 'capturedAt': item['capturedAt'],
                    'readOnly': True, 'persistencePolicy': PORTFOLIO_POLICY,
                    'isDefault': item['id'] == default_id,
                    'scenario': snapshot.get('scenario'),
                    'parcelCount': len(snapshot['inputs'].get('parcels', [])),
                    'areaM2': snapshot['results'].get('development', {}).get('landAreaM2'),
                })
            except (ValueError, ApiError, OSError, KeyError, TypeError):
                continue
        return sorted(items, key=lambda item: item['capturedAt'], reverse=True)


class LocalServer(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=16
    # Windows SO_REUSEADDR can let two servers bind the same endpoint.
    # Treat a second instance as busy so it gets a separate free port.
    allow_reuse_address=os.name != "nt"
    def __init__(self,port,collector,store):
        self.collector,self.store=collector,store
        self._portfolio = None
        self.jobs=threading.BoundedSemaphore(4)
        super().__init__(("127.0.0.1",port),Handler)

    @property
    def portfolio(self):
        if self._portfolio is None:
            self._portfolio = self.store.portfolio
        return self._portfolio


class Handler(BaseHTTPRequestHandler):
    server_version="PFStudy/6.0"
    sys_version=""

    def log_message(self,*args):
        # Query strings can carry addresses; never print request URLs or raw errors.
        pass

    def guard(self):
        port=self.server.server_port
        allowed={f"127.0.0.1:{port}",f"localhost:{port}"}
        if self.headers.get("Host","").lower() not in allowed:
            raise ApiError("INVALID_HOST","로컬 실행 주소로 접속하세요.",403)
        origin=self.headers.get("Origin")
        if origin is not None and origin not in {"http://"+a for a in allowed}:
            raise ApiError("ORIGIN_REJECTED","다른 사이트에서 로컬 분석 서버에 접근할 수 없습니다.",403)
        if self.headers.get("Sec-Fetch-Site") in ("cross-site",):
            raise ApiError("ORIGIN_REJECTED","다른 사이트에서 로컬 분석 서버에 접근할 수 없습니다.",403)

    def reply(self,body,status=200,content_type="application/json; charset=utf-8",cache=False,retry_after=None):
        if not isinstance(body,bytes):
            body=json.dumps(body,ensure_ascii=False,allow_nan=False).encode("utf-8")
        for secret in self.server.collector.keys.values():
            if secret and (secret.encode('utf-8') in body or urllib.parse.quote(secret,safe='').encode('ascii') in body):
                raise ValueError("응답에 인증정보가 포함되어 전송을 중단했습니다.")
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","private, max-age=300" if cache else "no-store")
        if retry_after is not None:self.send_header("Retry-After",str(retry_after))
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Cross-Origin-Resource-Policy","same-origin")
        self.send_header("X-Frame-Options","DENY")
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass

    def fail(self,exc):
        if isinstance(exc,ApiError):code,message,status=exc.code,exc.message,exc.status
        elif isinstance(exc,(ValueError,KeyError,TypeError)):code,message,status="INVALID_INPUT",str(exc),400
        else:code,message,status="INTERNAL_ERROR","처리 중 오류가 발생했습니다. 입력·파일 권한을 확인하거나 다시 실행하세요.",500
        for secret in self.server.collector.keys.values():
            if secret:message=message.replace(secret,"[비공개]").replace(urllib.parse.quote(secret,safe=""),"[비공개]")
        error={"code":code,"message":message}
        if status==429:
            error.update(retryable=True,retryAfterSeconds=1)
            self.reply({"error":error},status,retry_after=1)
        else:self.reply({"error":error},status)

    def do_OPTIONS(self):
        self.reply({"error":{"code":"METHOD_NOT_ALLOWED","message":"교차 출처 접근은 지원하지 않습니다."}},405)

    def do_GET(self):
        try:
            self.guard()
            parts=urllib.parse.urlsplit(self.path);path=parts.path
            query={k:v[-1] for k,v in urllib.parse.parse_qs(parts.query).items()}
            c,s=self.server.collector,self.server.store
            if path in ("/","/index.html","/V6.html","/pf_study.html"):
                self.reply(render_html(s.template, portfolio=self.server.portfolio.entries(), default_sample_id=self.server.portfolio.default_id()).encode("utf-8"),content_type="text/html; charset=utf-8");return
            if path=="/favicon.ico":self.reply(b"",204,"image/x-icon");return
            if path=="/api/status":
                info=c.status();info['version']='6.0.0';info['exportPolicy']='v5-geocoder-requery'
                info['jsonSaveDirectory']=str(s.directory)
                info['apiStatus'].update({k:'준비' if c.keys.get(k) else '인증 미준비' for k in ('vworldGeocoder','vworldSearch','kosis')})
                info['apiStatus']['sgis']='준비' if c.keys.get('sgisId') and c.keys.get('sgisSecret') else '서비스 ID·비밀값 확인 필요'
                self.reply(info);return
            match=re.fullmatch(r"/api/tiles/(\d+)/(\d+)/(\d+)\.jpeg",path)
            if match:self.reply(c.tile(*map(int,match.groups())),content_type="image/jpeg",cache=True);return
            if not self.server.jobs.acquire(blocking=False):raise ApiError("BUSY","다른 자료를 조회 중입니다. 잠시 후 다시 시도하세요.",429)
            try:
                if path=="/api/parcels":self.reply(c.parcels([float(v) for v in query.get("bbox","").split(",")]))
                elif path=="/api/parcel":
                    year=int(query.get("year",dt.date.today().year))
                    self.reply(enrich_parcel(c,c.parcel(query.get("pnu",""),year,refresh=query.get("refresh")=="1"),year))
                elif path=="/api/boundary-allocation":
                    self.reply(c.boundary_allocation(query.get("pnu",""),int(query.get("year",dt.date.today().year)),refresh=query.get("refresh")=="1"))
                elif path=="/api/site-survey":self.reply(site_survey(c,query))
                elif path=="/api/address":self.reply(c.address(query.get("keyword",""),geocode=True))
                elif path=="/api/regions":self.reply(c.regions(q=query.get("q",""),parent=query.get("parent",""),level=query.get("level","all"),current=query.get("current","1")!="0",refresh=query.get("refresh")=="1"))
                elif path=="/api/data-coverage":self.reply(c.data_coverage())
                elif path=="/api/land-cache":self.reply(c.land_storage(query.get('sgg')))
                elif path=="/api/comparables":
                    self.reply(c.comparables(query.get("sgg",""),query.get("dong",""),query.get("start",""),query.get("end",""),query.get("refresh")=="1",
                        scope=query.get("scope","dong"),lon=query.get("lon"),lat=query.get("lat"),radius_km=query.get("radiusKm",5),
                        land_start=query.get("landStart"),land_end=query.get("landEnd"),revenue_start=query.get("revenueStart"),revenue_end=query.get("revenueEnd"),as_of=query.get("asOf"),land_scope=query.get("landScope","dong"),period_mode="rolling60",
                        selected_pnus=query.get("selectedPnus"),legal_dong_code=query.get("legalDongCode")))
                elif path=="/api/snapshots":self.reply({"items":s.list()})
                elif path=="/api/portfolio-samples":self.reply({"items":self.server.portfolio.list(),"defaultId":self.server.portfolio.default_id()})
                elif path=="/api/portfolio-default":self.reply({"id":self.server.portfolio.default_id()})
                elif path.startswith("/api/portfolio-samples/"):self.reply(self.server.portfolio.read(path.removeprefix("/api/portfolio-samples/")))
                elif path.startswith("/api/snapshots/"):self.reply(s.read(path.removeprefix("/api/snapshots/")))
                elif path.startswith("/pf-study-v6-snapshots/") and path.endswith(".json"):
                    self.reply(s.read(path.removeprefix("/pf-study-v6-snapshots/").removesuffix(".json")))
                else:raise ApiError("NOT_FOUND","요청한 경로를 찾을 수 없습니다.",404)
            finally:self.server.jobs.release()
        except Exception as exc:self.fail(exc)

    def do_POST(self):
        try:
            self.guard()
            if self.headers.get("Content-Type","").split(";")[0].strip()!="application/json":
                raise ApiError("CONTENT_TYPE","JSON 형식만 사용할 수 있습니다.",415)
            try:length=int(self.headers.get("Content-Length","0"))
            except ValueError:raise ValueError("올바른 요청 크기가 필요합니다.") from None
            if length<=0 or length>MAX_JSON:raise ApiError("BODY_LIMIT","요청은 64MB 이하의 JSON이어야 합니다.",413)
            try:body=json.loads(self.rfile.read(length).decode("utf-8"),parse_constant=lambda _: (_ for _ in ()).throw(ValueError("유한한 숫자가 필요합니다.")))
            except (UnicodeError,json.JSONDecodeError):raise ValueError("올바른 JSON이 필요합니다.") from None
            path=urllib.parse.urlsplit(self.path).path
            if path=="/api/analyze":self.reply(analyze(body,partial=True))
            elif path=="/api/save":self.reply(self.server.store.save(body))
            elif path=="/api/export-json":self.reply(self.server.store.save(body,write_html=False))
            elif path=="/api/portfolio-samples":
                saved = self.server.portfolio.save(body)
                self.server.store.write_html()
                self.reply(saved)
            elif path=="/api/portfolio-default":
                if not isinstance(body,dict):raise ValueError('초기 분석 식별자가 필요합니다.')
                result=self.server.portfolio.set_default(body.get('id'))
                self.server.store.write_html()
                self.reply(result)
            else:raise ApiError("NOT_FOUND","요청한 경로를 찾을 수 없습니다.",404)
        except Exception as exc:self.fail(exc)


def open_dashboard(address):
    """Use the Windows URL handler, then report failure rather than fail silently."""
    if os.name == "nt":
        try:
            os.startfile(address)
            return True
        except OSError:
            pass
    try:
        if webbrowser.open(address, new=2):
            return True
    except (OSError, webbrowser.Error):
        pass
    print("브라우저를 자동으로 열지 못했습니다. 아래 주소를 브라우저에 입력하세요:\n" + address)
    return False


def start_local_server(port, collector, store, *, allow_fallback=False):
    try:
        return LocalServer(port, collector, store)
    except OSError as exc:
        # Only a busy default port should select a free port. Never attach to
        # an unknown existing server, or conceal permission/other bind errors.
        import errno
        busy = exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048
        if not allow_fallback or not busy:
            raise
        server = LocalServer(0, collector, store)
        print(f"기본 포트 {port}가 사용 중이어서 {server.server_port}번 포트로 시작합니다.")
        return server


def main(html_template=None,output_dir=None,argv=None,*,bundled_portfolio=None,bundled_default_id=None):
    parser=argparse.ArgumentParser(description="개발사업성 분석 V6: 저장한 분석과 실제 자료 조회")
    parser.add_argument("--port",type=int,default=None,help="기본 4175. 기본 포트 사용 중이면 빈 포트 자동 선택")
    parser.add_argument("--no-browser",action="store_true")
    parser.add_argument("--output-dir",default=output_dir)
    parser.add_argument("--domain",default=os.environ.get("VWORLD_DOMAIN",DEFAULT_DOMAIN),help="브이월드에 등록한 서비스 주소")
    args=parser.parse_args(argv)
    if args.port is not None and not 0<=args.port<=65535:parser.error("포트는 0~65535 범위여야 합니다.")
    destination=pathlib.Path(args.output_dir or pathlib.Path(sys.argv[0]).resolve().parent)
    if html_template is None:
        template_path=pathlib.Path(__file__).with_name("V6.html")
        if not template_path.exists():raise SystemExit("함께 제공된 V6.py를 실행하세요. HTML 원본을 찾을 수 없습니다.")
        html_template=template_path.read_text(encoding="utf-8")
    print("개발사업성 분석 V6 - 실제 조회·계산은 이 Python 실행 창이 열린 동안 작동합니다.")
    print("인증키는 환경변수 또는 프로젝트 .env에서만 읽습니다. 종료: Ctrl+C")
    keys=read_keys()
    missing=[variable for name,variable,_ in KEY_FIELDS[:3] if not keys.get(name)]
    if missing:
        print("미등록 환경변수: " + ", ".join(missing))
        print("저장된 예시는 열람할 수 있습니다. 실제 조회는 .env를 설정한 뒤 다시 실행하세요.")
    collector=Collector(keys,args.domain)
    try:
        collector.land_store=LandStore(destination/'pf-study-v6-cache'/'land-trades.sqlite3',secrets=keys.values())
        print('토지 로컬 저장소: '+str(collector.land_store.path))
        print('완료한 월은 재사용하고 미완료 월·페이지부터 이어받습니다. HTML 저장 시 해당 분석의 토지자료도 포함합니다.')
    except LandStoreError as exc:
        collector.land_store_error='로컬 토지 보관 불가 · '+str(exc)+' 이번 실행은 임시 보관만 사용합니다.'
        print(collector.land_store_error)
    store=SnapshotStore(destination,html_template,keys.values(),bundled_portfolio=bundled_portfolio,bundled_default_id=bundled_default_id);store.initialize()
    try:server=start_local_server(4175 if args.port is None else args.port,collector,store,allow_fallback=args.port is None)
    except OSError:raise SystemExit("포트를 사용할 수 없습니다. --port 4175처럼 다른 포트로 실행하세요.") from None
    address=f"http://127.0.0.1:{server.server_port}/"
    print("대시보드: "+address)
    browser_timer=None
    if not args.no_browser:
        browser_timer=threading.Timer(.5,open_dashboard,args=(address,))
        browser_timer.daemon=True
        browser_timer.start()
    try:server.serve_forever(poll_interval=.4)
    except KeyboardInterrupt:print("\n개발사업성 분석을 종료합니다. 저장된 HTML·JSON 결과는 유지됩니다.")
    finally:
        if browser_timer is not None:browser_timer.cancel()
        server.server_close();collector.keys.clear()


if __name__=="__main__":main()
