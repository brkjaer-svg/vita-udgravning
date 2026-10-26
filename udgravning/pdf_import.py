"""Indlæs en "Volume Report, Model To Model" (fx Trimble Business Center) fra PDF.

Farvekortet ligger i PDF'en som vektortrekanter, der hver har farven fra et
højdeinterval i legenden. Rekonstruktionen:

1. Målestok: summen af trekantarealerne svarer til rapportens "Flat Areas".
2. Punkter, der deles af to intervaller, ligger på en konturlinje og har
   kendt dybde (intervalgrænsen).
3. De øvrige punkter (TIN-punkter inde i et interval) bestemmes ved mindste
   kvadraters metode: hvor en ret TIN-kant krydser konturlinjer, giver
   krydsningspunkterne lineære ligninger. Resten udglattes svagt (Laplace)
   og klemmes til intervallet.
"""
from __future__ import annotations

import base64
import math
import re
from collections import Counter

import fitz
import numpy as np
import shapely

from .geometri import rens_tin

TAL_RE = re.compile(r"[-+]?\d{1,3}(?:\.\d{3})*,\d+|[-+]?\d+,\d+|[-+]?\d+\.\d+|[-+]?\d+")


class ImportFejl(Exception):
    pass


def parse_tal(s):
    s = s.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


def _farve(c):
    return tuple(round(v, 3) for v in c)


def _dk(v):
    return ("%.3f" % v).replace(".", ",")


def _ord_i_raekke(ordliste, y0, y1, x_min=None, x_max=None):
    ud = []
    for w in ordliste:
        yc = (w[1] + w[3]) / 2
        if y0 - 0.5 <= yc <= y1 + 0.5:
            if x_min is not None and w[0] < x_min:
                continue
            if x_max is not None and w[2] > x_max:
                continue
            ud.append(w)
    return sorted(ud, key=lambda w: w[0])


def _find_legende(tegninger, ordliste):
    """Find farvefelterne i "Height Intervals and Areas" og læs intervallerne."""
    felter = []
    for x in tegninger:
        if x.get("fill") is None:
            continue
        it = x["items"]
        if len(it) == 1 and it[0][0] == "re":
            r = x["rect"]
            felter.append((round(r.x0, 1), round(r.x1, 1), r.y0, r.y1, _farve(x["fill"])))
    grp = {}
    for f in felter:
        grp.setdefault((f[0], f[1]), []).append(f)
    bedst = []
    for k, lst in grp.items():
        lst.sort(key=lambda f: f[2])
        # sammenhængende stak
        kaede = [lst[0]]
        for f in lst[1:]:
            if abs(f[2] - kaede[-1][3]) < 1.0:
                kaede.append(f)
            else:
                if len(kaede) > len(bedst):
                    bedst = kaede
                kaede = [f]
        if len(kaede) > len(bedst):
            bedst = kaede
    if len(bedst) < 3:
        raise ImportFejl("Fandt ikke legenden med højdeintervaller (farvefelter) i PDF'en.")
    intervaller = []
    for x0, x1, y0, y1, farve in bedst:
        bredde = x1 - x0
        venstre = " ".join(w[4] for w in _ord_i_raekke(ordliste, y0, y1, x_min=x0 - 3 * bredde, x_max=x0 + 0.5))
        hoejre = [w[4] for w in _ord_i_raekke(ordliste, y0, y1, x_min=x1 - 0.5, x_max=x1 + 3 * bredde)]
        tal = [parse_tal(t) for t in TAL_RE.findall(venstre)]
        v = venstre.strip()
        if len(tal) >= 2:
            vmin, vmax = sorted(tal[-2:])
        elif ">" in v and tal:
            vmin, vmax = tal[-1], math.inf
        elif "<" in v and tal:
            vmin, vmax = -math.inf, tal[-1]
        else:
            raise ImportFejl(f"Kunne ikke læse intervallet '{venstre}' i legenden.")
        areal = None
        tal_h = [t for t in hoejre if TAL_RE.fullmatch(t)]
        if tal_h:
            areal = parse_tal(tal_h[0])
        # højdeforskel (planlagt - eksisterende) -> dybde under terræn
        if math.isinf(vmax):
            tekst = "> %s" % _dk(vmin)
        elif math.isinf(vmin):
            tekst = "< %s" % _dk(vmax)
        else:
            tekst = "%s - %s" % (_dk(vmin), _dk(vmax))
        intervaller.append({
            "tekst": tekst,
            "dybde_min": -vmax + 0.0,
            "dybde_max": -vmin + 0.0,
            "farve": list(farve),
            "areal_rapport": areal,
        })
    return intervaller, (min(f[0] for f in bedst), min(f[2] for f in bedst), max(f[1] for f in bedst), max(f[3] for f in bedst))


def _find_rapporttal(ordliste):
    """Volumen og areal fra rækkerne 'Cut:' og 'Fill:' i rapporttabellen."""
    def raekke(navn):
        for w in ordliste:
            if w[4] == navn:
                yc = (w[1] + w[3]) / 2
                tal = sorted((x[0], x[4]) for x in ordliste
                             if abs((x[1] + x[3]) / 2 - yc) < 2.5 and x[0] > w[2] and TAL_RE.fullmatch(x[4]))
                if len(tal) >= 2:
                    return parse_tal(tal[0][1]), parse_tal(tal[1][1])
        return None
    cut = raekke("Cut:")
    fill = raekke("Fill:")
    dato = None
    for i, w in enumerate(ordliste):
        if w[4] == "Created:" and i + 1 < len(ordliste):
            dato = ordliste[i + 1][4]
    return cut, fill, dato


def _er_konveks(pts):
    n = len(pts)
    tegn = 0
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        cx, cy = pts[(i + 2) % n]
        k = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if abs(k) < 1e-12:
            continue
        s = 1 if k > 0 else -1
        if tegn == 0:
            tegn = s
        elif s != tegn:
            return False
    return True


def importer_pdf(data, w_lap=0.5, side=0, status=None):
    """Læs PDF (bytes) og returnér et dict med flade, intervaller, kilde og baggrund."""
    def meld(t):
        if status:
            status(t)

    doc = fitz.open(stream=data, filetype="pdf")
    if len(doc) <= side:
        raise ImportFejl("PDF'en har ingen side %d." % (side + 1))
    p = doc[side]
    meld("Læser vektorer i PDF'en")
    tegninger = p.get_drawings()
    ordliste = p.get_text("words")
    intervaller, leg_bbox = _find_legende(tegninger, ordliste)
    cut, fill, dato = _find_rapporttal(ordliste)
    if cut is None:
        raise ImportFejl("Fandt ikke rækken 'Cut:' med volumen og areal i rapporttabellen.")
    ref_vol, ref_areal_cut = cut
    ref_areal = ref_areal_cut + (fill[1] if fill else 0.0)

    farve_idx = {}
    for i, iv in enumerate(intervaller):
        farve_idx[tuple(iv["farve"])] = i

    polys = []
    for x in tegninger:
        f = x.get("fill")
        if f is None:
            continue
        k = _farve(f)
        if k not in farve_idx:
            continue
        r = x["rect"]
        if leg_bbox[0] - 1 <= r.x0 and r.x1 <= leg_bbox[2] + 1 and leg_bbox[1] - 1 <= r.y0 and r.y1 <= leg_bbox[3] + 1:
            continue
        pts = []
        for it in x["items"]:
            if it[0] == "l":
                if not pts:
                    pts.append((it[1].x, it[1].y))
                pts.append((it[2].x, it[2].y))
            elif it[0] == "re":
                rr = it[1]
                pts = [(rr.x0, rr.y0), (rr.x1, rr.y0), (rr.x1, rr.y1), (rr.x0, rr.y1)]
            elif it[0] == "qu":
                qq = it[1]
                pts = [(qq.ul.x, qq.ul.y), (qq.ur.x, qq.ur.y), (qq.lr.x, qq.lr.y), (qq.ll.x, qq.ll.y)]
            else:
                pts.append((it[-1].x, it[-1].y))
        keys = []
        for q in pts:
            kk = (round(q[0], 3), round(q[1], 3))
            if not keys or keys[-1] != kk:
                keys.append(kk)
        if len(keys) > 1 and keys[0] == keys[-1]:
            keys.pop()
        if len(keys) >= 3:
            polys.append((farve_idx[k], keys))
    if not polys:
        raise ImportFejl("Fandt ingen farvede trekanter med legendens farver.")

    # målestok
    pt_areal = 0.0
    pr_baand = Counter()
    for b, keys in polys:
        a = abs(shapely.Polygon(keys).area)
        pt_areal += a
        pr_baand[b] += a
    S = math.sqrt(ref_areal / pt_areal)  # m pr. pt
    afv = []
    for b, a in pr_baand.items():
        ar = intervaller[b]["areal_rapport"]
        if ar:
            afv.append(abs(a * S * S / ar - 1))
    meld("Målestok fundet: 1:%d" % round(S / (0.0254 / 72)))

    # punkter
    vid = {}
    for b, keys in polys:
        for kk in keys:
            vid.setdefault(kk, len(vid))
    n = len(vid)
    xy_pt = np.zeros((n, 2))
    for kk, i in vid.items():
        xy_pt[i] = kk
    xy = np.column_stack([xy_pt[:, 0] * S, -xy_pt[:, 1] * S])
    ox = math.floor(xy[:, 0].min())
    oy = math.floor(xy[:, 1].min())
    xy[:, 0] -= ox
    xy[:, 1] -= oy

    baand_pkt = [set() for _ in range(n)]
    nab = [set() for _ in range(n)]
    tri = []
    tri_baand = []
    for b, keys in polys:
        ids = [vid[k] for k in keys]
        for i in ids:
            baand_pkt[i].add(b)
        for a, c in zip(ids, ids[1:] + ids[:1]):
            nab[a].add(c)
            nab[c].add(a)
        if len(ids) == 3 or _er_konveks(keys):
            for j in range(1, len(ids) - 1):
                tri.append((ids[0], ids[j], ids[j + 1]))
                tri_baand.append(b)
        else:
            for g in shapely.get_parts(shapely.constrained_delaunay_triangles(shapely.Polygon(keys))):
                c = list(g.exterior.coords)[:3]
                try:
                    tri.append(tuple(vid[(round(x, 3), round(y, 3))] for x, y in c))
                    tri_baand.append(b)
                except KeyError:
                    pass

    meld("Rekonstruerer dybder")
    d = _rekonstruer(xy, nab, baand_pkt, intervaller, w_lap)
    meld("Renser trekantnettet")
    xy, d, tri, tri_baand = rens_tin(xy, d, np.array(tri, np.int64), np.array(tri_baand, np.int64))

    fyld = any(math.isinf(intervaller[b]["dybde_min"]) or intervaller[b]["dybde_max"] <= 0 for b in pr_baand)

    # baggrund: kortudsnit (største billede eller hele siden)
    klip = p.rect
    bedst_areal = 0
    for info in p.get_image_info():
        r = fitz.Rect(info["bbox"])
        if r.width * r.height > bedst_areal:
            bedst_areal = r.width * r.height
            klip = r
    zoom = min(2400 / max(klip.width, klip.height), 4.0)
    pix = p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=klip)
    jpeg = pix.tobytes("jpeg", jpg_quality=82)
    baggrund = {
        "jpeg_b64": base64.b64encode(jpeg).decode("ascii"),
        "x0": klip.x0 * S - ox, "x1": klip.x1 * S - ox,
        "y0": -klip.y1 * S - oy, "y1": -klip.y0 * S - oy,
    }

    kilde = {
        "type": "Volume Report, Model To Model",
        "dato": dato,
        "reference_volumen": ref_vol,
        "reference_areal": ref_areal,
        "fyld_volumen": fill[0] if fill else 0.0,
        "m_pr_pt": S,
        "maalestok": round(S / (0.0254 / 72)),
        "origo_pt": [ox / S, -oy / S],
        "maks_arealafvigelse_pct": round(max(afv) * 100, 3) if afv else None,
        "har_fyld": bool(fyld),
    }
    return {
        "flade": {"xy": xy, "d": d, "tri": np.array(tri, np.int64), "baand": np.array(tri_baand, np.int64)},
        "intervaller": intervaller,
        "kilde": kilde,
        "baggrund": baggrund,
    }


def _bandgraenser(iv):
    lo = iv["dybde_min"]
    hi = iv["dybde_max"]
    return (lo if math.isfinite(lo) else None), (hi if math.isfinite(hi) else None)


def _konturvaerdi(baandset, intervaller):
    bs = sorted(baandset, key=lambda b: (intervaller[b]["dybde_min"], intervaller[b]["dybde_max"]))
    vaerdier = []
    for a, b in zip(bs, bs[1:]):
        g1 = intervaller[a]["dybde_max"]
        g2 = intervaller[b]["dybde_min"]
        if math.isfinite(g1) and math.isfinite(g2):
            vaerdier.append((g1 + g2) / 2)
        elif math.isfinite(g1):
            vaerdier.append(g1)
        elif math.isfinite(g2):
            vaerdier.append(g2)
    return float(np.mean(vaerdier)) if vaerdier else None


def _rekonstruer(xy, nab, baand_pkt, intervaller, w_lap):
    n = len(xy)
    zk = np.full(n, np.nan)
    for i in range(n):
        if len(baand_pkt[i]) > 1:
            v = _konturvaerdi(baand_pkt[i], intervaller)
            if v is not None:
                zk[i] = v
    kendt = ~np.isnan(zk)
    ukendte = np.where(~kendt)[0]
    m = len(ukendte)
    if m == 0:
        return zk
    uidx = {int(v): j for j, v in enumerate(ukendte)}

    def naeste_kollinear(prev, cur):
        u = xy[cur] - xy[prev]
        L = math.hypot(*u)
        u = u / L
        for y_ in nab[cur]:
            if y_ == prev:
                continue
            v = xy[y_] - xy[cur]
            Lv = math.hypot(*v)
            if Lv < 1e-9 or u[0] * v[0] + u[1] * v[1] <= 0:
                continue
            if abs(u[0] * v[1] - u[1] * v[0]) / Lv < 1e-3:
                return y_
        return None

    rk, ck, vk = [], [], []
    b_vec = np.zeros(m)

    def ligning(co, rhs, w):
        js = list(co.keys())
        for a in js:
            b_vec[a] += w * w * co[a] * rhs
            for b in js:
                rk.append(a)
                ck.append(b)
                vk.append(w * w * co[a] * co[b])

    set_kaeder = set()
    for P in ukendte:
        P = int(P)
        for N in nab[P]:
            if not kendt[N]:
                continue
            kaede = [P, N]
            while len(kaede) < 80:
                nx = naeste_kollinear(kaede[-2], kaede[-1])
                if nx is None:
                    break
                kaede.append(nx)
                if not kendt[nx]:
                    break
            Q = kaede[-1]
            if not kendt[Q]:
                noegle = (min(P, Q), max(P, Q), len(kaede))
                if noegle in set_kaeder:
                    continue
                set_kaeder.add(noegle)
                L = math.hypot(*(xy[Q] - xy[P]))
                for X in kaede[1:-1]:
                    t = math.hypot(*(xy[X] - xy[P])) / L
                    ligning({uidx[P]: 1 - t, uidx[Q]: t}, zk[X], 1.0)
            else:
                ks = kaede[1:]
                for a_, b_ in zip(ks, ks[1:]):
                    if abs(zk[a_] - zk[b_]) < 1e-9:
                        continue
                    LPa = math.hypot(*(xy[a_] - xy[P]))
                    Lab = math.hypot(*(xy[b_] - xy[a_]))
                    ligning({uidx[P]: 1.0}, zk[a_] + (zk[a_] - zk[b_]) * LPa / Lab, 1.0)
                    break

    # startværdi og svag forankring i intervallets midte
    x0 = np.zeros(m)
    for j, P in enumerate(ukendte):
        b = next(iter(baand_pkt[P]))
        lo, hi = _bandgraenser(intervaller[b])
        if lo is not None and hi is not None:
            x0[j] = (lo + hi) / 2
        elif lo is not None:
            x0[j] = lo + 0.1
        elif hi is not None:
            x0[j] = hi - 0.1
        ligning({j: 1.0}, x0[j], 1e-3)
    for P in ukendte:
        P = int(P)
        nb = list(nab[P])
        if not nb:
            continue
        co = {uidx[P]: 1.0}
        rhs = 0.0
        for q in nb:
            if kendt[q]:
                rhs += zk[q] / len(nb)
            else:
                co[uidx[q]] = co.get(uidx[q], 0.0) - 1.0 / len(nb)
        ligning(co, rhs, w_lap)

    rk = np.asarray(rk)
    ck = np.asarray(ck)
    vk = np.asarray(vk)

    def matvec(x):
        return np.bincount(rk, weights=vk * x[ck], minlength=m)

    # konjugerede gradienter
    x = x0.copy()
    r = b_vec - matvec(x)
    pv = r.copy()
    rs = float(r @ r)
    rs0 = max(float(b_vec @ b_vec), 1e-30)
    for _ in range(20000):
        Ap = matvec(pv)
        alpha = rs / float(pv @ Ap)
        x += alpha * pv
        r -= alpha * Ap
        rsn = float(r @ r)
        if rsn < 1e-24 * rs0:
            break
        pv = r + (rsn / rs) * pv
        rs = rsn

    z = zk.copy()
    for j, P in enumerate(ukendte):
        b = next(iter(baand_pkt[P]))
        lo, hi = _bandgraenser(intervaller[b])
        v = x[j]
        if lo is not None:
            v = max(v, lo)
        if hi is not None:
            v = min(v, hi)
        z[P] = v
    return np.maximum(z, 0.0)
