"""Synthetic public-style polygon evidence for pre-existing calculation tests."""
import copy
from server.domain.boundary import VERSION, PARCEL_LAYER, ZONE_LAYERS, attribute_basis, recompute_boundary
from server.domain.land import classify_zone


def add_boundary(parcel):
    """Explicitly refresh synthetic evidence after a test changes the parcel."""
    pnu = parcel['pnu']
    attrs = parcel.get('attributes') or {}
    rows = (attrs.get('landRegister') or {}).get('rows') or []
    if len(rows) == 1:
        rows[0]['lndpclAr'] = parcel.get('areaM2')
        if rows[0].get('pnu'): rows[0]['pnu'] = pnu
    zones = [row for row in (attrs.get('landUse') or {}).get('rows', []) if isinstance(row, dict) and
             classify_zone(row.get('prposAreaDstrcCodeNm'),row.get('prposAreaDstrcCode'))['status'] == 'ready' and str(row.get('cnflcAt')) in ('1', '2')]
    if not zones: return parcel
    geometry = {'type': 'Polygon', 'coordinates': [[[127.,37.],[127.001,37.],[127.001,37.001],[127.,37.001],[127.,37.]]]}
    feature = {'type':'Feature','id':pnu,'properties':{'pnu':pnu},'geometry':copy.deepcopy(geometry),'sourceLayer':PARCEL_LAYER}
    zone = zones[0]
    zfeature = {'type':'Feature','id':'synthetic-zone','sourceLayer':ZONE_LAYERS[0],
                'properties':{'uname':zone['prposAreaDstrcCodeNm']},'geometry':copy.deepcopy(geometry)}
    stamp='2026-10-10T00:00:00+00:00'
    evidence = {'version':VERSION,'pnu':pnu,'queriedAt':stamp,'parcelFeature':feature,
        'parcelGeometry':geometry,'sourceFeatures':[zfeature],'attributeBasis':attribute_basis(parcel),
        'source':{'provider':'synthetic-test-fixture','parcelLayer':PARCEL_LAYER,'zoningLayers':list(ZONE_LAYERS),
          'crs':'EPSG:4326','areaCrs':'EPSG:5179','queriedAt':stamp,'complete':True,
          'pages':[{'layer':layer,'totalCount':int(layer in (PARCEL_LAYER, ZONE_LAYERS[0])),
                    'rawCount':int(layer in (PARCEL_LAYER, ZONE_LAYERS[0])),
                    'uniqueCount':int(layer in (PARCEL_LAYER, ZONE_LAYERS[0])),
                    'pageCount':1,'complete':True} for layer in (PARCEL_LAYER,*ZONE_LAYERS)]}}
    parcel['boundaryAllocation'] = recompute_boundary(parcel,evidence)
    return parcel
