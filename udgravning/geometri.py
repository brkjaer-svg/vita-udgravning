"""Eksakt geometri for udgravningsmodellen.

Udgravningen er rummet mellem terræn (dybde 0) og bunden (dybde d(x, y) > 0),
hvor d er en TIN. En kasse er et lodret prisme: et roteret rektangel i plan
mellem to dybder. Alle volumener beregnes eksakt: trekanterne klippes med
kassernes sider og med de vandrette niveauer, så integranden er lineær i hver
celle (integral = areal x værdi i tyngdepunktet).

Koordinater: x mod øst, y mod nord (meter). Dybder er positive nedad.
Kote = terrænkote - dybde.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely

MIN_AREAL = 1e-10
TOL = 1e-9


# ---------------------------------------------------------------------------
# Små polygonværktøjer (konvekse polygoner som lister af (x, y))
# ---------------------------------------------------------------------------

def areal_og_tp(poly):
    """Areal (positivt mod uret) og tyngdepunkt af et polygon."""
    a = cx = cy = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    a *= 0.5
    if abs(a) < 1e-14:
        return 0.0, (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)
    return a, (cx / (6 * a), cy / (6 * a))


def areal(poly):
    if len(poly) < 3:
        return 0.0
    a = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return 0.5 * a


def klip(poly, nx, ny, c):
    """Sutherland-Hodgman: behold delen af et konvekst polygon, hvor nx*x + ny*y <= c."""
    ud = []
    n = len(poly)
    if n == 0:
        return ud
    fs = [nx * p[0] + ny * p[1] - c for p in poly]
    for i in range(n):
        P, fp = poly[i], fs[i]
        j = (i + 1) % n
        Q, fq = poly[j], fs[j]
        if fp <= 0:
            ud.append(P)
        if (fp < 0 < fq) or (fq < 0 < fp):
            t = fp / (fp - fq)
            ud.append((P[0] + t * (Q[0] - P[0]), P[1] + t * (Q[1] - P[1])))
    return ud


def _gyldig(poly):
    return len(poly) >= 3 and abs(areal(poly)) > MIN_AREAL


# ---------------------------------------------------------------------------
# Kasse
# ---------------------------------------------------------------------------

@dataclass
class Kasse:
    """Udskærende kasse. Rotation i grader mod uret fra x-aksen (øst).
    top og bund er dybder i meter under terræn (top < bund)."""
    id: str
    navn: str = ""
    aktiv: bool = True
    cx: float = 0.0
    cy: float = 0.0
    laengde: float = 5.0
    bredde: float = 5.0
    rotation: float = 0.0
    top: float = 0.0
    bund: float = 5.0
    note: str = ""

    def gyldig(self):
        return self.laengde > 0 and self.bredde > 0 and self.bund > self.top

    def hjoerner(self):
        a = math.radians(self.rotation)
        ca, sa = math.cos(a), math.sin(a)
        hl, hb = self.laengde / 2, self.bredde / 2
        ud = []
        for lx, ly in ((-hl, -hb), (hl, -hb), (hl, hb), (-hl, hb)):
            ud.append((self.cx + lx * ca - ly * sa, self.cy + lx * sa + ly * ca))
        return ud  # mod uret

    def halvplaner(self):
        """Fire halvplaner (nx, ny, c), hvor indersiden er nx*x + ny*y <= c."""
        h = self.hjoerner()
        ud = []
        for i in range(4):
            (x0, y0), (x1, y1) = h[i], h[(i + 1) % 4]
            # indre til venstre for kanten -> udadrettet normal til højre
            nx, ny = (y1 - y0), -(x1 - x0)
            L = math.hypot(nx, ny)
            nx, ny = nx / L, ny / L
            ud.append((nx, ny, nx * x0 + ny * y0))
        return ud

    def interval(self):
        """Dybdeinterval, klemt til terræn (dybde >= 0)."""
        return (max(self.top, 0.0), self.bund)

    def geometrinoegle(self):
        return (round(self.cx, 4), round(self.cy, 4), round(self.laengde, 4), round(self.bredde, 4),
                round(self.rotation, 4), round(self.top, 4), round(self.bund, 4))


def _indenfor(hp, x, y, tol=0.0):
    return all(nx * x + ny * y - c < -tol for nx, ny, c in hp)


# ---------------------------------------------------------------------------
# Dybdeflade (TIN)
# ---------------------------------------------------------------------------

def _randkanter(tri, n):
    """Kanter brugt af præcis én trekant: (kanter (k, 2), trekantindeks (k,))."""
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    eier = np.concatenate([np.arange(len(tri))] * 3)
    lo = np.minimum(e[:, 0], e[:, 1])
    hi = np.maximum(e[:, 0], e[:, 1])
    _, inv, ant = np.unique(lo * (n + 1) + hi, return_inverse=True, return_counts=True)
    m = ant[inv.reshape(-1)] == 1
    return e[m], eier[m]


def rens_t_kryds(xy, tri, baand, tol=1e-5):
    """Fjern T-kryds: del trekanter, hvor et punkt ligger midt på en kant, der kun
    bruges af én trekant. Giver et vandtæt net, hvor kun den ydre rand er åben."""
    tri = np.array(tri, np.int64).reshape(-1, 3)
    baand = np.asarray(baand).copy()
    for _ in range(20):
        kanter, eier = _randkanter(tri, len(xy))
        if not len(kanter):
            break
        pkt = np.unique(kanter)
        tree = shapely.STRtree(shapely.points(xy[pkt]))
        segs = shapely.linestrings(np.stack([xy[kanter[:, 0]], xy[kanter[:, 1]]], axis=1))
        ik, ip = tree.query(segs, predicate="dwithin", distance=tol)
        deling = {}
        for k, j in zip(ik, ip):
            v = int(pkt[j])
            a, b = int(kanter[k, 0]), int(kanter[k, 1])
            if v in (a, b):
                continue
            A, B, V = xy[a], xy[b], xy[v]
            L2 = float(((B - A) ** 2).sum())
            t = float(((V - A) * (B - A)).sum()) / L2
            if not (1e-9 < t < 1 - 1e-9):
                continue
            ti = int(eier[k])
            if ti in deling and deling[ti][0] != (a, b):
                continue  # én kant pr. trekant pr. runde
            deling.setdefault(ti, [(a, b), []])[1].append((t, v))
        if not deling:
            break
        nye, nye_b, behold = [], [], np.ones(len(tri), bool)
        for ti, ((a, b), punkter) in deling.items():
            t0 = tri[ti]
            c = [x for x in t0 if x not in (a, b)][0]
            raekke = [a] + [v for _, v in sorted(set(punkter))] + [b]
            for p_, q_ in zip(raekke, raekke[1:]):
                nye.append((p_, q_, c))
                nye_b.append(baand[ti])
            behold[ti] = False
        tri = np.concatenate([tri[behold], np.array(nye, np.int64)])
        baand = np.concatenate([baand[behold], np.array(nye_b)])
    return tri, baand


def rens_tin(xy, d, tri, baand):
    """Byg en ren plan inddeling af trekanter, der overlapper en smule (som i PDF'er):
    alle kanter knudes, fladerne polygoniseres og trianguleres, og dybden i nye
    knuder tages fra de dækkende trekanters planer. Eksisterende punkter beholder
    deres dybde."""
    xy = np.round(np.asarray(xy, float), 4)  # 0,1 mm-gitter (samme som projektfilen)
    d = np.asarray(d, float)
    tri = np.asarray(tri, np.int64).reshape(-1, 3)
    baand = np.asarray(baand)
    e = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    e = e[np.any(xy[e[:, 0]] != xy[e[:, 1]], axis=1)]
    linjer = shapely.linestrings(np.stack([xy[e[:, 0]], xy[e[:, 1]]], axis=1))
    knudet = shapely.union_all(linjer, grid_size=1e-4)
    flader = shapely.get_parts(shapely.polygonize(shapely.get_parts(knudet)))
    gamle_tri = shapely.polygons(np.stack([xy[tri[:, 0]], xy[tri[:, 1]], xy[tri[:, 2]], xy[tri[:, 0]]], axis=1))
    tree = shapely.STRtree(gamle_tri)
    # behold kun flader, der er dækket af en trekant (ikke huller i nettet)
    ip, _ = tree.query(shapely.point_on_surface(flader), predicate="intersects")
    flader = flader[np.unique(ip)]
    nye = shapely.get_parts(shapely.constrained_delaunay_triangles(flader))
    nye = nye[shapely.area(nye) > 1e-12]
    koord = shapely.get_coordinates(nye).reshape(-1, 4, 2)[:, :3, :]
    # planer for de gamle trekanter
    A, B, C = xy[tri[:, 0]], xy[tri[:, 1]], xy[tri[:, 2]]
    dA, dB, dC = d[tri[:, 0]], d[tri[:, 1]], d[tri[:, 2]]
    ux, uy, uz = B[:, 0] - A[:, 0], B[:, 1] - A[:, 1], dB - dA
    vx, vy, vz = C[:, 0] - A[:, 0], C[:, 1] - A[:, 1], dC - dA
    nz = ux * vy - uy * vx
    nzs = np.where(np.abs(nz) > 1e-12, nz, 1.0)
    px = -(uy * vz - uz * vy) / nzs
    py = -(uz * vx - ux * vz) / nzs
    p0 = dA - px * A[:, 0] - py * A[:, 1]

    flad = koord.reshape(-1, 2)
    noegle = np.round(flad * 1e6).astype(np.int64)
    uniq, inv = np.unique(noegle, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    nxy = np.zeros((len(uniq), 2))
    nxy[inv] = flad
    nd = np.full(len(uniq), np.nan)
    gml = {tuple(k): i for i, k in enumerate(np.round(xy * 1e6).astype(np.int64).tolist())}
    for j, k in enumerate(uniq.tolist()):
        i = gml.get(tuple(k))
        if i is not None:
            nd[j] = d[i]
    mangler = np.where(np.isnan(nd))[0]
    if len(mangler):
        ip, it = tree.query(shapely.points(nxy[mangler]), predicate="dwithin", distance=1e-6)
        sum_d = np.zeros(len(mangler))
        ant = np.zeros(len(mangler))
        ok = np.abs(nz[it]) > 1e-12
        np.add.at(sum_d, ip[ok], px[it[ok]] * nxy[mangler][ip[ok], 0] + py[it[ok]] * nxy[mangler][ip[ok], 1] + p0[it[ok]])
        np.add.at(ant, ip[ok], 1)
        nd[mangler] = np.where(ant > 0, sum_d / np.maximum(ant, 1), np.nan)
        if np.isnan(nd).any():  # nærmeste kendte punkt som nødløsning
            for j in np.where(np.isnan(nd))[0]:
                nd[j] = d[np.argmin(((xy - nxy[j]) ** 2).sum(axis=1))]
    ntri = inv.reshape(-1, 3)
    tp = shapely.points(koord.mean(axis=1))
    ip, it = tree.query(tp, predicate="intersects")
    nb = np.zeros(len(ntri), baand.dtype)
    _, forst = np.unique(ip, return_index=True)
    nb[ip[forst]] = baand[it[forst]]
    return nxy, np.maximum(nd, 0.0), ntri, nb


class Flade:
    """Dybdeflade som TIN. xy: (n, 2) meter, d: (n,) dybde (positiv nedad),
    tri: (m, 3) punktindeks, baand: (m,) intervalnummer pr. trekant."""

    def __init__(self, xy, d, tri, baand=None):
        xy = np.asarray(xy, float)
        d = np.asarray(d, float)
        tri = np.array(tri, np.int64).reshape(-1, 3)
        if baand is None:
            baand = np.zeros(len(tri), int)
        baand = np.asarray(baand)

        def krydsprodukt(t):
            a, b, c = xy[t[:, 0]], xy[t[:, 1]], xy[t[:, 2]]
            return (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])

        ok = np.abs(krydsprodukt(tri)) > 1e-12
        tri, baand = rens_t_kryds(xy, tri[ok], baand[ok])
        kr = krydsprodukt(tri)
        ok = np.abs(kr) > 1e-12
        tri, baand, kr = tri[ok], baand[ok], kr[ok]
        vend = kr < 0
        tri[vend] = tri[vend][:, [0, 2, 1]]
        self.xy = xy
        self.d = d
        self.tri = tri
        self.baand = baand.astype(int)
        self.areal = np.abs(kr) / 2

        A, B, C = xy[self.tri[:, 0]], xy[self.tri[:, 1]], xy[self.tri[:, 2]]
        dA, dB, dC = d[self.tri[:, 0]], d[self.tri[:, 1]], d[self.tri[:, 2]]
        ux, uy, uz = B[:, 0] - A[:, 0], B[:, 1] - A[:, 1], dB - dA
        vx, vy, vz = C[:, 0] - A[:, 0], C[:, 1] - A[:, 1], dC - dA
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        # plan pr. trekant: d = px*x + py*y + p0
        self.px = -nx / nz
        self.py = -ny / nz
        self.p0 = dA - self.px * A[:, 0] - self.py * A[:, 1]

        self.trekanter = shapely.polygons(np.stack([A, B, C, A], axis=1))
        self.tree = shapely.STRtree(self.trekanter)
        self._byg_rand()

    # -- rand og omrids ------------------------------------------------------
    def _byg_rand(self):
        rand, _ = _randkanter(self.tri, len(self.xy))  # indre til venstre
        self.randkanter = rand
        naeste = {}
        for a, b in rand:
            naeste.setdefault(int(a), []).append(int(b))

        def vaelg(a, b, kand):
            # ved et knudepunkt: tag den skarpeste venstresving, så ringene forbliver simple
            if len(kand) == 1:
                return kand[0]
            ux, uy = self.xy[b] - self.xy[a]
            bedst, bv = None, None
            for x in kand:
                vx, vy = self.xy[x] - self.xy[b]
                vinkel = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
                if bv is None or vinkel > bv:
                    bedst, bv = x, vinkel
            return bedst

        ringe = []
        brugt = set()
        for a0, b0 in rand:
            if (int(a0), int(b0)) in brugt:
                continue
            ring = [int(a0)]
            a, b = int(a0), int(b0)
            while True:
                brugt.add((a, b))
                ring.append(b)
                if b == ring[0]:
                    break
                kand = [x for x in naeste.get(b, []) if (b, x) not in brugt]
                if not kand:
                    break
                a, b = b, vaelg(a, b, kand)
            if len(ring) >= 4 and ring[0] == ring[-1]:
                ringe.append(ring)
        skaller, huller = [], []
        for ring in ringe:
            ar = areal([tuple(self.xy[i]) for i in ring[:-1]])
            p = shapely.make_valid(shapely.Polygon(self.xy[ring]))
            (skaller if ar > 0 else huller).append(p)
        omr = shapely.union_all(skaller) if skaller else None
        if omr is not None:
            for h in huller:
                omr = omr.difference(h)
        if omr is None or abs(omr.area - self.samlet_areal()) > 1e-6 * max(self.samlet_areal(), 1.0):
            omr = shapely.union_all(self.trekanter)
        self.omrids = omr
        shapely.prepare(self.omrids)

    # -- enkle størrelser -----------------------------------------------------
    def samlet_areal(self):
        return float(self.areal.sum())

    def brutto_pr_trekant(self):
        dd = self.d[self.tri]
        return self.areal * dd.mean(axis=1)

    def brutto(self):
        return float(self.brutto_pr_trekant().sum())

    def maks_dybde(self):
        return float(self.d.max())

    def dybde_i(self, x, y):
        """Dybde i punkter (vektoriseret); nan uden for udgravningen."""
        x = np.atleast_1d(np.asarray(x, float))
        y = np.atleast_1d(np.asarray(y, float))
        ud = np.full(x.shape, np.nan)
        pkt = shapely.points(x.ravel(), y.ravel())
        ip, it = self.tree.query(pkt, predicate="intersects")
        if len(ip):
            _, forst = np.unique(ip, return_index=True)
            ip, it = ip[forst], it[forst]
            flad = ud.ravel()
            flad[ip] = self.px[it] * x.ravel()[ip] + self.py[it] * y.ravel()[ip] + self.p0[it]
            ud = flad.reshape(x.shape)
        return ud

    def plan_d(self, t, x, y):
        return self.px[t] * x + self.py[t] * y + self.p0[t]

    def skaleret(self, faktor):
        return Flade(self.xy, self.d * faktor, self.tri, self.baand)


# ---------------------------------------------------------------------------
# Materiale i en søjle
# ---------------------------------------------------------------------------

def flet_intervaller(iv):
    """Sortér og flet dybdeintervaller (a, b), klemt til a >= 0."""
    iv = sorted((max(a, 0.0), b) for a, b in iv if b > max(a, 0.0))
    ud = []
    for a, b in iv:
        if ud and a <= ud[-1][1]:
            ud[-1] = (ud[-1][0], max(ud[-1][1], b))
        else:
            ud.append((a, b))
    return ud


def materiale(dm, U):
    """Materiale i [0, d] minus de flettede intervaller U, vurderet ved dybden dm.
    Grænser er tal (konstant dybde) eller None (= bunden d)."""
    res = []
    cur = 0.0
    for a, b in U:
        if a >= dm:
            break
        if a > cur:
            res.append((cur, a))
        cur = max(cur, b)
        if cur >= dm:
            return res
    if cur < dm:
        res.append((cur, None))
    return res


def _vaerdi(g, dv):
    return dv if g is None else g


def interval_minus(A, B, dm):
    """A minus B for intervallister med mærkede grænser (vurderet ved dm)."""
    res = []
    for alo, ahi in A:
        stk = [(alo, ahi)]
        for blo, bhi in B:
            ny = []
            vbl, vbh = _vaerdi(blo, dm), _vaerdi(bhi, dm)
            for slo, shi in stk:
                vsl, vsh = _vaerdi(slo, dm), _vaerdi(shi, dm)
                if vbh <= vsl or vbl >= vsh:
                    ny.append((slo, shi))
                    continue
                if vbl > vsl:
                    ny.append((slo, blo))
                if vbh < vsh:
                    ny.append((bhi, shi))
            stk = ny
        res.extend(stk)
    return res


def _skiv(poly, px, py, p0, niveauer):
    """Del et konvekst polygon i skiver ved d = niveau (stigende niveauer)."""
    if not niveauer:
        return [poly]
    ds = [px * x + py * y + p0 for x, y in poly]
    dmin, dmax = min(ds), max(ds)
    lv = [L for L in niveauer if dmin + TOL < L < dmax - TOL]
    if not lv:
        return [poly]
    ud = []
    rest = poly
    for L in lv:
        under = klip(rest, px, py, L - p0)
        if _gyldig(under):
            ud.append(under)
        rest = klip(rest, -px, -py, -(L - p0))
        if len(rest) < 3:
            break
    if _gyldig(rest):
        ud.append(rest)
    return ud


def _celler(poly, hp_liste, ks):
    """Del et konvekst polygon i konvekse celler, hver mærket med de kasser, der dækker den."""
    celler = [(poly, frozenset())]
    for k in ks:
        hp = hp_liste[k]
        ny = []
        for p, K in celler:
            ind = p
            for h in hp:
                ind = klip(ind, *h)
                if len(ind) < 3:
                    break
            a_ind = abs(areal(ind)) if len(ind) >= 3 else 0.0
            if a_ind <= MIN_AREAL:
                ny.append((p, K))
                continue
            ny.append((ind, K | {k}))
            if a_ind >= abs(areal(p)) * (1 - 1e-12):
                continue
            rest = p
            for nx, ny_, c in hp:
                ud = klip(rest, -nx, -ny_, -c)
                if _gyldig(ud):
                    ny.append((ud, K))
                rest = klip(rest, nx, ny_, c)
                if len(rest) < 3:
                    break
        celler = ny
    return celler


# ---------------------------------------------------------------------------
# Beregning
# ---------------------------------------------------------------------------

@dataclass
class KasseResultat:
    id: str
    aktiv: bool
    fradrag: float          # snitvolumen kasse x udgravning (m3), uafhængigt af andre kasser
    areal: float            # kassens planareal inden for udgravningen (m2)
    advarsel: str = ""


@dataclass
class Resultat:
    brutto: float
    netto: float
    areal: float
    kasser: dict = field(default_factory=dict)       # id -> KasseResultat
    brutto_pr_baand: dict = field(default_factory=dict)
    netto_pr_baand: dict = field(default_factory=dict)
    areal_pr_baand: dict = field(default_factory=dict)
    verts: np.ndarray | None = None                  # netto-mesh (koter)
    faces: np.ndarray | None = None
    mesh_volumen: float | None = None

    @property
    def fradrag(self):
        return self.brutto - self.netto

    @property
    def sum_enkelt_fradrag(self):
        return sum(k.fradrag for k in self.kasser.values() if k.aktiv)

    @property
    def overlap(self):
        return self.sum_enkelt_fradrag - self.fradrag


def _kandidater(flade, kasse):
    poly = shapely.Polygon(kasse.hjoerner())
    return flade.tree.query(poly, predicate="intersects")


def kasse_fradrag(flade, kasse):
    """Eksakt snitvolumen og planareal mellem én kasse og udgravningen."""
    a, b = kasse.interval()
    hp = kasse.halvplaner()
    vol = 0.0
    ar = 0.0
    if not kasse.gyldig():
        return 0.0, 0.0
    for t in _kandidater(flade, kasse):
        i0, i1, i2 = flade.tri[t]
        poly = [tuple(flade.xy[i0]), tuple(flade.xy[i1]), tuple(flade.xy[i2])]
        for h in hp:
            poly = klip(poly, *h)
            if len(poly) < 3:
                break
        if not _gyldig(poly):
            continue
        ar += abs(areal(poly))
        if b <= a:
            continue
        px, py, p0 = flade.px[t], flade.py[t], flade.p0[t]
        for stk in _skiv(poly, px, py, p0, [a, b]):
            A, (gx, gy) = areal_og_tp(stk)
            dm = px * gx + py * gy + p0
            if dm <= a:
                continue
            L = (dm - a) if dm < b else (b - a)
            vol += abs(A) * L
    return vol, ar


def beregn(flade, kasser, terraenkote=0.0, med_mesh=True):
    """Volumen uden og med fradrag, fradrag pr. kasse og (valgfrit) netto-mesh."""
    brutto_t = flade.brutto_pr_trekant()
    netto_t = brutto_t.copy()
    res = Resultat(brutto=float(brutto_t.sum()), netto=0.0, areal=flade.samlet_areal())

    for k in kasser:
        v, ar = kasse_fradrag(flade, k)
        adv = ""
        if not k.gyldig():
            adv = "Ugyldig kasse (bund skal være under top, mål > 0)"
        elif ar <= 1e-6:
            adv = "Kassen ligger uden for udgravningen"
        elif v <= 1e-9:
            adv = "Kassen rammer ingen udgravning i sit dybdeinterval"
        res.kasser[k.id] = KasseResultat(k.id, bool(k.aktiv), v, ar, adv)

    aktive = [k for k in kasser if k.aktiv and k.gyldig()]
    hp_liste = [k.halvplaner() for k in aktive]
    iv_liste = [k.interval() for k in aktive]

    pr_tri = {}
    for j, k in enumerate(aktive):
        for t in _kandidater(flade, k):
            pr_tri.setdefault(int(t), []).append(j)

    caps = []   # trekanter som ((x,y,z),(x,y,z),(x,y,z))
    for t, ks in pr_tri.items():
        i0, i1, i2 = flade.tri[t]
        poly = [tuple(flade.xy[i0]), tuple(flade.xy[i1]), tuple(flade.xy[i2])]
        px, py, p0 = flade.px[t], flade.py[t], flade.p0[t]
        netto = 0.0
        for celle, K in _celler(poly, hp_liste, ks):
            U = flet_intervaller([iv_liste[j] for j in K])
            niv = sorted({v for ab in U for v in ab})
            for stk in _skiv(celle, px, py, p0, niv):
                A, (gx, gy) = areal_og_tp(stk)
                dm = px * gx + py * gy + p0
                mat = materiale(dm, U)
                for lo, hi in mat:
                    netto += abs(A) * (_vaerdi(hi, dm) - lo)
                if med_mesh:
                    for lo, hi in mat:
                        top = [(x, y, terraenkote - lo) for x, y in stk]
                        bund = [(x, y, terraenkote - (px * x + py * y + p0 if hi is None else hi)) for x, y in stk]
                        for m in range(1, len(stk) - 1):
                            caps.append((top[0], top[m], top[m + 1]))
                            caps.append((bund[0], bund[m + 1], bund[m]))
        netto_t[t] = netto
    res.netto = float(netto_t.sum())

    for b in np.unique(flade.baand):
        m = flade.baand == b
        res.brutto_pr_baand[int(b)] = float(brutto_t[m].sum())
        res.netto_pr_baand[int(b)] = float(netto_t[m].sum())
        res.areal_pr_baand[int(b)] = float(flade.areal[m].sum())

    if med_mesh:
        _byg_mesh(flade, aktive, hp_liste, iv_liste, set(pr_tri), caps, terraenkote, res)
    return res


def _byg_mesh(flade, aktive, hp_liste, iv_liste, beroert, caps, z0, res):
    xy, d, tri = flade.xy, flade.d, flade.tri
    fri = np.array([t for t in range(len(tri)) if t not in beroert], dtype=np.int64)
    blokke = []
    if len(fri):
        T = tri[fri]
        top = np.concatenate([xy[T], np.full(T.shape + (1,), z0)], axis=2)
        bund = np.concatenate([xy[T], (z0 - d[T])[..., None]], axis=2)
        blokke.append(top)
        blokke.append(bund[:, [0, 2, 1], :])
    if caps:
        blokke.append(np.array(caps, float))
    vaegge = _byg_vaegge(flade, aktive, hp_liste, iv_liste, z0)
    if vaegge:
        blokke.append(np.array(vaegge, float))
    alle = np.concatenate(blokke, axis=0)  # (f, 3, 3)

    # flet punkter
    flad = alle.reshape(-1, 3)
    noegle = np.round(flad / 1e-6).astype(np.int64)
    uniq, inv = np.unique(noegle, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    verts = np.zeros((len(uniq), 3))
    np.add.at(verts, inv, flad)
    tael = np.bincount(inv, minlength=len(uniq))[:, None]
    verts /= tael
    faces = inv.reshape(-1, 3)
    # fjern degenererede trekanter
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    kr = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    ok = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2]) & (kr > 1e-12)
    faces = faces[ok]
    res.verts = verts
    res.faces = faces
    res.mesh_volumen = mesh_volumen(verts, faces)


def mesh_volumen(verts, faces):
    a, b, c = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def _byg_vaegge(flade, aktive, hp_liste, iv_liste, z0):
    """Lodrette flader langs udgravningens rand og kassernes sider."""
    omr = flade.omrids
    linjer = []
    for g in shapely.get_parts(omr):
        linjer.append(g.exterior)
        linjer.extend(g.interiors)
    for k in aktive:
        p = shapely.Polygon(k.hjoerner())
        if p.intersects(omr):
            linjer.append(p.exterior)
    noded = shapely.union_all([shapely.LineString(l.coords) for l in linjer])
    segs = []
    for ls in shapely.get_parts(noded):
        c = np.asarray(ls.coords)
        for i in range(len(c) - 1):
            if math.hypot(*(c[i + 1] - c[i])) > 1e-9:
                segs.append((c[i], c[i + 1]))
    if not segs:
        return []
    P = np.array([s[0] for s in segs])
    Q = np.array([s[1] for s in segs])
    M = (P + Q) / 2
    U = (Q - P) / np.linalg.norm(Q - P, axis=1)[:, None]
    NL = np.stack([-U[:, 1], U[:, 0]], axis=1)
    eps = 1e-5
    L = M + eps * NL
    R = M - eps * NL
    iL = shapely.contains_xy(omr, L[:, 0], L[:, 1])
    iR = shapely.contains_xy(omr, R[:, 0], R[:, 1])

    flader = []
    for s in range(len(segs)):
        if not iL[s] and not iR[s]:
            continue
        KL = [j for j in range(len(aktive)) if _indenfor(hp_liste[j], L[s, 0], L[s, 1])] if iL[s] else []
        KR = [j for j in range(len(aktive)) if _indenfor(hp_liste[j], R[s, 0], R[s, 1])] if iR[s] else []
        if iL[s] and iR[s] and KL == KR:
            continue
        UL = flet_intervaller([iv_liste[j] for j in KL])
        UR = flet_intervaller([iv_liste[j] for j in KR])
        niv = sorted({v for ab in UL + UR for v in ab})
        p, q = P[s], Q[s]
        for t0, t1, t in _segment_i_tin(flade, p, q):
            px, py, p0 = flade.px[t], flade.py[t], flade.p0[t]
            dp = px * p[0] + py * p[1] + p0
            dq = px * q[0] + py * q[1] + p0
            snit = [t0, t1]
            if abs(dq - dp) > 1e-12:
                for Lv in niv:
                    tt = (Lv - dp) / (dq - dp)
                    if t0 + 1e-12 < tt < t1 - 1e-12:
                        snit.append(tt)
            snit.sort()
            for s0, s1 in zip(snit, snit[1:]):
                if s1 - s0 < 1e-12:
                    continue
                dm = dp + (s0 + s1) / 2 * (dq - dp)
                ML = materiale(dm, UL) if iL[s] else []
                MR = materiale(dm, UR) if iR[s] else []
                P0 = p + s0 * (q - p)
                P1 = p + s1 * (q - p)
                d0 = dp + s0 * (dq - dp)
                d1 = dp + s1 * (dq - dp)
                for (lo, hi), mod_venstre in [(iv, False) for iv in interval_minus(ML, MR, dm)] + \
                                             [(iv, True) for iv in interval_minus(MR, ML, dm)]:
                    lo0, lo1 = _vaerdi(lo, d0), _vaerdi(lo, d1)
                    hi0, hi1 = _vaerdi(hi, d0), _vaerdi(hi, d1)
                    if hi0 - lo0 < 1e-9 and hi1 - lo1 < 1e-9:
                        continue
                    A = (P0[0], P0[1], z0 - lo0)
                    B = (P1[0], P1[1], z0 - lo1)
                    C = (P1[0], P1[1], z0 - hi1)
                    D = (P0[0], P0[1], z0 - hi0)
                    if mod_venstre:   # normal mod venstre
                        flader.append((A, B, C))
                        flader.append((A, C, D))
                    else:
                        flader.append((A, D, C))
                        flader.append((A, C, B))
    return flader


def _segment_i_tin(flade, p, q):
    """Del segmentet p-q i stykker [t0, t1] pr. TIN-trekant."""
    kand = flade.tree.query(shapely.LineString([p, q]), predicate="intersects")
    dx, dy = q[0] - p[0], q[1] - p[1]
    stk = []
    for t in kand:
        i = flade.tri[t]
        lo, hi = 0.0, 1.0
        ok = True
        for a, b in ((i[0], i[1]), (i[1], i[2]), (i[2], i[0])):
            A, B = flade.xy[a], flade.xy[b]
            ex, ey = B[0] - A[0], B[1] - A[1]
            # f(X) = ey*(X-A)x - ex*(X-A)y <= tol  (indre til venstre)
            f0 = ey * (p[0] - A[0]) - ex * (p[1] - A[1])
            f1 = ey * dx - ex * dy
            tol = 1e-7 * math.hypot(ex, ey)
            if abs(f1) < 1e-15:
                if f0 > tol:
                    ok = False
                    break
                continue
            tt = (tol - f0) / f1
            if f1 > 0:
                hi = min(hi, tt)
            else:
                lo = max(lo, tt)
            if hi - lo <= 1e-12:
                ok = False
                break
        if ok and hi - lo > 1e-12:
            stk.append((lo, hi, int(t)))
    stk.sort()
    ud = []
    cur = 0.0
    while cur < 1.0 - 1e-12:
        bedst = None
        for lo, hi, t in stk:
            if lo <= cur + 1e-9 and hi > cur + 1e-12:
                if bedst is None or hi > bedst[1]:
                    bedst = (lo, hi, t)
        if bedst is None:
            nste = [lo for lo, hi, t in stk if lo > cur + 1e-12]
            if not nste:
                break
            cur = min(nste)
            continue
        slut = min(bedst[1], 1.0)
        ud.append((cur, slut, bedst[2]))
        cur = slut
    return ud
