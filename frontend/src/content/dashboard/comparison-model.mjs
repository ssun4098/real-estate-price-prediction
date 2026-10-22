/** Source-bound comparison helpers. Benchmark: 만원/공급평; revenue: 억원. */
const PYEONG_SQM = 3.305785;
const supplied = value => value !== null && value !== undefined && String(value).trim() !== '';
const numeric = value => supplied(value) && Number.isFinite(Number(value)) ? Number(value) : null;
const positive = value => { const n = numeric(value); return n !== null && n > 0 ? n : null; };
const validCoordinates = (lat, lon) => numeric(lat) !== null && numeric(lon) !== null
  && Number(lat) >= -90 && Number(lat) <= 90 && Number(lon) >= -180 && Number(lon) <= 180;

/** Great-circle distance in kilometres. Invalid coordinates return null, never zero. */
export function haversine(lat1, lon1, lat2, lon2) {
  if (!validCoordinates(lat1, lon1) || !validCoordinates(lat2, lon2)) return null;
  const radians = n => Number(n) * Math.PI / 180;
  const dLat = radians(Number(lat2) - Number(lat1));
  const dLon = radians(Number(lon2) - Number(lon1));
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(radians(lat1)) * Math.cos(radians(lat2)) * Math.sin(dLon / 2) ** 2;
  return 6371.0088 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, a))));
}

/** Preserve original row objects so filtered source inspectors retain honest membership. */
export function filterCases(rows, filters = {}, coords = {}) {
  const f = filters ?? {};
  const useRadius = supplied(f.radiusKm);
  const radius = positive(f.radiusKm);
  if (useRadius && (radius === null || !validCoordinates(f.targetLat, f.targetLon))) return [];
  const minArea = supplied(f.minArea) ? numeric(f.minArea) : null;
  const maxArea = supplied(f.maxArea) ? numeric(f.maxArea) : null;
  if ((supplied(f.minArea) && minArea === null) || (supplied(f.maxArea) && maxArea === null)) return [];
  if (minArea !== null && maxArea !== null && minArea > maxArea) return [];
  const search = supplied(f.search) ? String(f.search).trim().toLocaleLowerCase('ko-KR') : '';
  return (Array.isArray(rows) ? rows : []).filter(row => {
    if (row.category !== '민영' || row.saleType !== '분양주택') return false;
    if (positive(row.area) === null || positive(row.pyeongPrice) === null) return false;
    for (const key of ['region', 'district', 'cap', 'renewal']) {
      if (supplied(f[key]) && String(row[key] ?? '') !== String(f[key]).trim()) return false;
    }
    if (search && ![row.name, row.address, row.contractor, row.developer, row.houseId]
      .some(value => String(value ?? '').toLocaleLowerCase('ko-KR').includes(search))) return false;
    if (supplied(f.from) && (!row.date || row.date < String(f.from))) return false;
    if (supplied(f.to) && (!row.date || row.date > String(f.to))) return false;
    if (minArea !== null && Number(row.area) < minArea) return false;
    if (maxArea !== null && Number(row.area) > maxArea) return false;
    if (useRadius) {
      const point = coords instanceof Map ? coords.get(String(row.houseId)) : coords?.[String(row.houseId)];
      const distance = point ? haversine(f.targetLat, f.targetLon, point.lat, point.lon) : null;
      if (distance === null || distance > radius) return false;
    }
    return true;
  });
}

function aggregate(values, method) {
  if (!values.length) return null;
  if (method === 'mean') return values.reduce((sum, value) => sum + value, 0) / values.length;
  const ordered = [...values].sort((a, b) => a - b);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}

/** Project weighting aggregates within each project, then treats projects equally. */
export function summarizeCases(rows, method = 'median', weighting = 'project') {
  if (!['median', 'mean'].includes(method)) throw new TypeError('method must be median or mean');
  if (!['project', 'type'].includes(weighting)) throw new TypeError('weighting must be project or type');
  const groups = new Map();
  const accepted = (Array.isArray(rows) ? rows : []).filter(row => supplied(row.houseId) && positive(row.pyeongPrice) !== null);
  for (const row of accepted) {
    const key = String(row.houseId);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const projectRows = [...groups.entries()].map(([houseId, members]) => ({
    houseId, name: members[0].name ?? '',
    value: aggregate(members.map(row => Number(row.pyeongPrice)), method),
    rows: members.length, address: members[0].address ?? '',
    date: members.map(row => row.date).filter(Boolean).sort().at(-1) ?? null,
  }));
  const values = weighting === 'project' ? projectRows.map(row => row.value) : accepted.map(row => Number(row.pyeongPrice));
  return {
    benchmark: aggregate(values, method), projectCount: projectRows.length, rowCount: accepted.length,
    min: values.length ? Math.min(...values) : null,
    max: values.length ? Math.max(...values) : null,
    projectRows,
  };
}

/** Parse quoted CSV without external dependencies; preserve IDs as strings. */
function readCSV(text) {
  const records = [];
  let fields = [], field = '', quoted = false, line = 1, startLine = 1;
  const content = String(text ?? '').replace(/^\uFEFF/, '');
  for (let i = 0; i < content.length; i++) {
    const char = content[i];
    if (char === '"') {
      if (quoted && content[i + 1] === '"') { field += '"'; i++; }
      else if (quoted || !field.trim()) quoted = !quoted;
      else field += char;
    } else if (char === ',' && !quoted) { fields.push(field.trim()); field = ''; }
    else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && content[i + 1] === '\n') i++;
      fields.push(field.trim());
      if (fields.some(supplied)) records.push({ fields, line: startLine });
      fields = []; field = ''; line++; startLine = line;
    } else { field += char; if (char === '\n') line++; }
  }
  fields.push(field.trim());
  if (fields.some(supplied)) records.push({ fields, line: startLine });
  return { records, unclosedQuote: quoted };
}

/** Coordinates are supplied evidence, not inferred. Conflicting duplicates are excluded. */
export function parseCoordinatesCSV(text) {
  const coords = Object.create(null), errors = [];
  const { records, unclosedQuote } = readCSV(text);
  if (unclosedQuote) return { coords, errors: ['CSV의 따옴표가 닫히지 않았습니다.'] };
  if (!records.length) return { coords, errors: ['좌표 CSV가 비어 있습니다.'] };
  const header = records[0].fields;
  const index = alternatives => header.findIndex(name => alternatives.includes(name));
  const idIndex = index(['houseId', '주택관리번호']);
  const latIndex = index(['lat', '위도']);
  const lonIndex = index(['lon', '경도']);
  if ([idIndex, latIndex, lonIndex].some(i => i < 0)) {
    return { coords, errors: ['필수 컬럼 houseId,lat,lon 또는 주택관리번호,위도,경도가 필요합니다.'] };
  }
  const conflictIds = new Set();
  for (const record of records.slice(1)) {
    const id = record.fields[idIndex]?.trim();
    const lat = numeric(record.fields[latIndex]), lon = numeric(record.fields[lonIndex]);
    if (!id) { errors.push(`${record.line}행: 주택관리번호가 없습니다.`); continue; }
    if (!validCoordinates(lat, lon)) { errors.push(`${record.line}행 (${id}): 위도·경도 값 또는 범위가 잘못되었습니다.`); continue; }
    if (conflictIds.has(id)) continue;
    if (coords[id] && (coords[id].lat !== lat || coords[id].lon !== lon)) {
      delete coords[id]; conflictIds.add(id);
      errors.push(`${record.line}행 (${id}): 서로 다른 중복 좌표가 있어 해당 번호를 제외했습니다.`);
      continue;
    }
    coords[id] = { lat, lon };
  }
  return { coords, errors };
}

/** Strict missingness: partial valid rows must never masquerade as the full project. */
export function calculateRevenue(types, benchmark, priceAdjustmentPct = 0, discountPct = 0) {
  const missing = [];
  const b = positive(benchmark), adjustment = numeric(priceAdjustmentPct), discount = numeric(discountPct);
  if (b === null) missing.push('양수인 비교사례 평당가격');
  if (adjustment === null || adjustment <= -100) missing.push('가격 보정률(-100% 초과)');
  if (discount === null || discount < 0 || discount > 100) missing.push('할인율(0~100%)');
  const list = Array.isArray(types) ? types : [];
  if (!list.length) missing.push('계획 주택형');
  const rows = list.map((type, index) => {
    const area = positive(type.area), units = numeric(type.units);
    const validUnits = units !== null && Number.isInteger(units) && units >= 0;
    const label = type.name || `주택형 ${index + 1}`;
    if (area === null) missing.push(`${label}: 양수 공급면적`);
    if (!validUnits) missing.push(`${label}: 0 이상의 정수 세대수`);
    const calculable = b !== null && area !== null && validUnits && adjustment !== null && adjustment > -100;
    const unitPrice = calculable ? b * (area / PYEONG_SQM) / 10000 * (1 + adjustment / 100) : null;
    const revenue = unitPrice !== null ? unitPrice * units : null;
    return { ...type, area, units: validUnits ? units : null, unitPrice, revenue,
      netRevenue: revenue !== null && discount !== null && discount >= 0 && discount <= 100 ? revenue * (1 - discount / 100) : null };
  });
  const unitsValid = rows.every(row => row.units !== null);
  const totalUnits = list.length && unitsValid ? rows.reduce((sum, row) => sum + row.units, 0) : null;
  if (totalUnits === 0) missing.push('1세대 이상인 총 계획세대수');
  const valid = missing.length === 0;
  return {
    valid, missing,
    grossRevenue: valid ? rows.reduce((sum, row) => sum + row.revenue, 0) : null,
    netRevenue: valid ? rows.reduce((sum, row) => sum + row.netRevenue, 0) : null,
    totalUnits,
    totalArea: list.length && rows.every(row => row.area !== null && row.units !== null) ? rows.reduce((sum, row) => sum + row.area * row.units, 0) : null,
    rows,
  };
}
