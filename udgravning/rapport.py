"""PDF-rapport: volumenopgørelse med og uden fradrag for de udskærende kasser."""
from __future__ import annotations

import datetime
import math

import fitz
import numpy as np
import shapely

from . import APP_NAVN, APP_VERSION
from .model import interval_tekst

A4 = fitz.paper_rect("a4")
A4L = fitz.paper_rect("a4-l")
M = 42  # margen
SORT = (0.1, 0.1, 0.1)
GRAA = (0.45, 0.45, 0.45)
LYS = (0.93, 0.93, 0.93)
ACCENT = (0.13, 0.30, 0.45)
ROED = (0.78, 0.12, 0.18)


def dk(v, dec=2):
    if v is None:
        return "-"
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _bredde(t, size, bold=False):
    return fitz.get_text_length(t, fontname="hebo" if bold else "helv", fontsize=size)


def _forkort(t, size, bold, maks):
    if _bredde(t, size, bold) <= maks:
        return t
    while t and _bredde(t + "...", size, bold) > maks:
        t = t[:-1]
    return t + "..."


class _Dok:
    def __init__(self, titel, projekt_navn):
        self.doc = fitz.open()
        self.titel = titel
        self.projekt_navn = projekt_navn
        self.page = None
        self.y = 0

    def ny_side(self, rect=A4):
        self.page = self.doc.new_page(width=rect.width, height=rect.height)
        self.y = M
        return self.page

    def tekst(self, x, y, t, size=9, bold=False, farve=SORT, align="l", bredde=None):
        if align == "r":
            x = x + (bredde or 0) - _bredde(t, size, bold)
        elif align == "c":
            x = x + ((bredde or 0) - _bredde(t, size, bold)) / 2
        self.page.insert_text((x, y), t, fontsize=size, fontname="hebo" if bold else "helv", color=farve)

    def afsnit(self, t, size=8.5, farve=SORT, bredde=None):
        bredde = bredde or (self.page.rect.width - 2 * M)
        r = fitz.Rect(M, self.y, M + bredde, self.y + 400)
        # mål højden ved at prøve i et midlertidigt dokument
        tmp = fitz.open()
        tp = tmp.new_page(width=self.page.rect.width, height=self.page.rect.height)
        rest = tp.insert_textbox(fitz.Rect(0, 0, bredde, 400), t, fontsize=size, fontname="helv")
        h = 400 - rest if rest >= 0 else 400
        tmp.close()
        if self.y + h > self.page.rect.height - M - 20:
            self.ny_side()
            r = fitz.Rect(M, self.y, M + bredde, self.y + 400)
        self.page.insert_textbox(r, t, fontsize=size, fontname="helv", color=farve)
        self.y += h + 4

    def overskrift(self, t, size=11.5):
        if self.y + 60 > self.page.rect.height - M - 20:
            self.ny_side()
        self.y += 10
        self.tekst(M, self.y + size, t, size=size, bold=True, farve=ACCENT)
        self.y += size + 7

    def tabel(self, kolonner, raekker, fede=(), sum_raekker=(), size=8.5, farver=None):
        """kolonner: [(titel, bredde, 'l'|'r')]. raekker: lister af tekster.
        Venstrestillet tekst må løbe ind i tomme celler til højre. farver: et
        farvefelt i første kolonne pr. række (None = intet)."""
        rh = size + 7.5
        x0 = M

        def hoved():
            self.page.draw_rect(fitz.Rect(x0, self.y, x0 + sum(k[1] for k in kolonner), self.y + rh),
                                color=None, fill=ACCENT)
            x = x0
            for titel, b, al in kolonner:
                self.tekst(x + 4, self.y + rh - 5, _forkort(titel, size, True, b - 8), size=size, bold=True,
                           farve=(1, 1, 1), align=al, bredde=b - 8)
                x += b
            self.y += rh

        if self.y + 2 * rh > self.page.rect.height - M - 20:
            self.ny_side()
        hoved()
        for i, r in enumerate(raekker):
            if self.y + rh > self.page.rect.height - M - 20:
                self.ny_side()
                hoved()
            bold = i in fede or i in sum_raekker
            if i in sum_raekker:
                self.page.draw_line((x0, self.y), (x0 + sum(k[1] for k in kolonner), self.y), color=SORT, width=0.7)
            elif i % 2 == 1:
                self.page.draw_rect(fitz.Rect(x0, self.y, x0 + sum(k[1] for k in kolonner), self.y + rh),
                                    color=None, fill=LYS)
            x = x0
            for j, ((titel, b, al), celle) in enumerate(zip(kolonner, r)):
                tilg = b
                if al == "l":
                    for (_, b2, _), c2 in zip(kolonner[j + 1:], r[j + 1:]):
                        if str(c2):
                            break
                        tilg += b2
                indryk = 0
                if j == 0 and farver and i < len(farver) and farver[i] is not None:
                    self.page.draw_rect(fitz.Rect(x + 4, self.y + 4, x + 16, self.y + rh - 4), color=GRAA,
                                        fill=tuple(farver[i]), width=0.3)
                    indryk = 17
                self.tekst(x + 4 + indryk, self.y + rh - 5, _forkort(str(celle), size, bold, tilg - 8 - indryk),
                           size=size, bold=bold, align=al, bredde=b - 8 - indryk)
                x += b
            self.y += rh
        self.y += 4

    def sidefoedder(self):
        n = len(self.doc)
        dato = datetime.date.today().strftime("%d-%m-%Y")
        for i, p in enumerate(self.doc):
            w, h = p.rect.width, p.rect.height
            p.draw_line((M, h - M + 8), (w - M, h - M + 8), color=GRAA, width=0.4)
            p.insert_text((M, h - M + 20), "%s  |  %s" % (self.projekt_navn, self.titel), fontsize=7,
                          fontname="helv", color=GRAA)
            t = "%s %s  |  %s  |  Side %d af %d" % (APP_NAVN, APP_VERSION, dato, i + 1, n)
            p.insert_text((w - M - _bredde(t, 7), h - M + 20), t, fontsize=7, fontname="helv", color=GRAA)


def lav_pdf(projekt, flade, res, udarbejdet_af="", bemaerkning=""):
    """Returnér rapporten som PDF-bytes."""
    k = projekt.kilde
    titel = "Volumenopgørelse, udgravning"
    D = _Dok(titel, projekt.navn)
    p = D.ny_side()
    W = p.rect.width - 2 * M

    # titel
    D.tekst(M, D.y + 20, titel, size=20, bold=True, farve=ACCENT)
    D.tekst(M, D.y + 40, projekt.navn, size=12.5, bold=False)
    D.y += 52
    p.draw_line((M, D.y), (M + W, D.y), color=ACCENT, width=1.2)
    D.y += 14

    faktor = projekt.kalibreringsfaktor()
    info = [
        ("Grundlag", "%s" % (k.get("fil") or "Volumenrapport (PDF)")),
        ("Rapportdato", k.get("dato") or "-"),
        ("Referencevolumen", "%s m³ (cut), areal %s m²" % (dk(k.get("reference_volumen")), dk(k.get("reference_areal")))),
        ("Terrænkote (top)", "%s m" % dk(projekt.terraenkote)),
        ("Udskrevet", datetime.date.today().strftime("%d-%m-%Y")),
    ]
    if udarbejdet_af:
        info.append(("Udarbejdet af", udarbejdet_af))
    for nav, v in info:
        D.tekst(M, D.y + 9, nav, size=8.5, bold=True, farve=GRAA)
        D.tekst(M + 115, D.y + 9, _forkort(v, 8.5, False, W - 115), size=8.5)
        D.y += 13
    D.y += 4

    aktive = [kk for kk in projekt.kasser if kk.aktiv]
    inaktive = [kk for kk in projekt.kasser if not kk.aktiv]
    arealer_aktive = 0.0
    if aktive:
        u = shapely.union_all([shapely.Polygon(kk.hjoerner()) for kk in aktive if kk.gyldig()])
        arealer_aktive = u.intersection(flade.omrids).area

    # opsummering
    D.overskrift("Opgørelse")
    kol = [("Post", 300, "l"), ("Areal (m²)", 105, "r"), ("Volumen (m³)", W - 405, "r")]
    raekker = [
        ["Udgravning uden fradrag", dk(res.areal), dk(res.brutto)],
        ["Fradrag for aktive kasser (%d stk.)" % len(aktive), dk(arealer_aktive), "-" + dk(res.fradrag)],
        ["Udgravning med fradrag", "", dk(res.netto)],
    ]
    D.tabel(kol, raekker, sum_raekker={2}, size=9.5)
    D.tekst(M, D.y + 8, "Volumener er i fast indbygget mål. Fradragsarealet er kassernes samlede planareal inden for udgravningen.",
            size=7.5, farve=GRAA)
    D.y += 14

    # kasser
    def kasserække(kk):
        kr = res.kasser.get(kk.id)
        return [kk.id, kk.navn or "", "%s x %s" % (dk(kk.laengde), dk(kk.bredde)), dk(kk.rotation, 1),
                "%s - %s" % (dk(kk.top), dk(kk.bund)), dk(kr.areal) if kr else "-", dk(kr.fradrag) if kr else "-"]

    kolk = [("ID", 30, "l"), ("Navn", 146, "l"), ("L x B (m)", 70, "r"), ("Rot. (°)", 42, "r"),
            ("Dybde (m u. t.)", 78, "r"), ("Areal (m²)", 62, "r"), ("Fradrag (m³)", W - 428, "r")]
    D.overskrift("Fradrag pr. kasse")
    if aktive:
        rk = [kasserække(kk) for kk in aktive]
        sum_rk = []
        rk.append(["", "Sum af kasser", "", "", "", "", dk(res.sum_enkelt_fradrag)])
        sum_rk.append(len(rk) - 1)
        if res.overlap > 0.0005:
            rk.append(["", "Overlap mellem kasser (tælles én gang)", "", "", "", "", "-" + dk(res.overlap)])
        rk.append(["", "Fradrag i alt", "", "", "", "", dk(res.fradrag)])
        D.tabel(kolk, rk, fede={len(rk) - 1}, sum_raekker=set(sum_rk))
        adv = [(kk.id, res.kasser[kk.id].advarsel) for kk in aktive if res.kasser.get(kk.id) and res.kasser[kk.id].advarsel]
        for kid, a in adv:
            D.afsnit("%s: %s" % (kid, a), size=7.5, farve=ROED)
    else:
        D.afsnit("Ingen aktive kasser. Volumen med fradrag er lig volumen uden fradrag.")
    if aktive:
        D.tekst(M, D.y + 6, "Areal er kassens planareal inden for udgravningen. Dybder er i meter under terræn.",
                size=7.5, farve=GRAA)
        D.y += 12
    if inaktive:
        D.overskrift("Kasser slået fra (fradraget er ikke medregnet)", size=10)
        D.tabel(kolk, [kasserække(kk) for kk in inaktive])

    # pr. interval
    D.overskrift("Volumen pr. dybdeinterval")
    kol_iv = [("Dybdeinterval", 120, "l"), ("Areal (m²)", 85, "r"), ("Uden fradrag (m³)", 105, "r"),
              ("Fradrag (m³)", 95, "r"), ("Med fradrag (m³)", W - 405, "r")]
    rk = []
    rk_farver = []
    for b in sorted(res.brutto_pr_baand, key=lambda b: projekt.intervaller[b]["dybde_min"] if b < len(projekt.intervaller) else 0):
        iv = projekt.intervaller[b] if b < len(projekt.intervaller) else None
        bt = res.brutto_pr_baand[b]
        nt = res.netto_pr_baand[b]
        rk.append([interval_tekst(iv) if iv else "-", dk(res.areal_pr_baand[b]), dk(bt), dk(bt - nt), dk(nt)])
        rk_farver.append(iv["farve"] if iv else (0.8, 0.8, 0.8))
    rk.append(["I alt", dk(res.areal), dk(res.brutto), dk(res.fradrag), dk(res.netto)])
    rk_farver.append(None)
    D.tabel(kol_iv, rk, sum_raekker={len(rk) - 1}, size=8, farver=rk_farver)

    # metode
    D.overskrift("Grundlag og metode", size=10)
    raa = projekt.raa_volumen
    ref = k.get("reference_volumen")
    tekst = (
        "Volumenmodellen er rekonstrueret fra farvekortet i volumenrapporten (Model To Model, %s). "
        "Farvekortets trekanter er læst som vektorer, og målestokken er bestemt, så det samlede areal svarer til "
        "rapportens areal (1:%s på papiret, største afvigelse pr. interval %s %%). Punkter på konturlinjerne har "
        "kendt dybde; øvrige punkter er bestemt ved mindste kvadraters metode langs TIN-kanterne. "
        % (k.get("dato") or "-", k.get("maalestok", "-"), dk(k.get("maks_arealafvigelse_pct"), 3)))
    if ref:
        tekst += ("Den rekonstruerede model gav %s m³ mod rapportens %s m³ (%s %%). "
                  % (dk(raa), dk(ref), dk((raa / ref - 1) * 100, 3)))
    if abs(faktor - 1) > 1e-12:
        tekst += "Dybderne er kalibreret med faktor %s, så volumen uden fradrag svarer til rapporten. " % dk(faktor, 5)
    tekst += ("Kasserne er lodrette prismer mellem to dybder under terræn. Fradraget er det eksakte snitvolumen "
              "mellem kasse og udgravning; hvor kasser overlapper, tælles overlappet én gang.")
    D.afsnit(tekst, size=8)
    if bemaerkning:
        D.overskrift("Bemærkning", size=10)
        D.afsnit(bemaerkning, size=8.5)

    _plan_side(D, projekt, flade, res)
    D.sidefoedder()
    data = D.doc.tobytes(garbage=3, deflate=True)
    D.doc.close()
    return data


def _plan_side(D, projekt, flade, res):
    p = D.ny_side(A4L)
    w, h = p.rect.width, p.rect.height
    D.tekst(M, M + 14, "Plan: udgravning og kasser", size=14, bold=True, farve=ACCENT)
    D.tekst(M, M + 28, projekt.navn, size=9, farve=GRAA)
    legende_b = 135
    omr = fitz.Rect(M, M + 40, w - M - legende_b - 10, h - M - 14)

    x0, y0, x1, y1 = flade.omrids.bounds
    for kk in projekt.kasser:
        if not kk.gyldig():
            continue
        bx0, by0, bx1, by1 = shapely.Polygon(kk.hjoerner()).bounds
        # medtag kun kasser i nærheden af udgravningen i udsnittet
        if bx1 > x0 - 30 and bx0 < x1 + 30 and by1 > y0 - 30 and by0 < y1 + 30:
            x0, y0, x1, y1 = min(x0, bx0), min(y0, by0), max(x1, bx1), max(y1, by1)
    mg = 3.0
    x0, y0, x1, y1 = x0 - mg, y0 - mg, x1 + mg, y1 + mg
    ptpm_fuld = 72 / 0.0254
    maal = None
    for s in (100, 200, 250, 300, 400, 500, 600, 750, 1000, 1250, 1500, 2000, 2500, 5000, 10000):
        k = ptpm_fuld / s
        if (x1 - x0) * k <= omr.width and (y1 - y0) * k <= omr.height:
            maal = s
            break
    if maal is None:
        k = min(omr.width / (x1 - x0), omr.height / (y1 - y0))
        maal = round(ptpm_fuld / k)
    k = ptpm_fuld / maal
    ox = omr.x0 + (omr.width - (x1 - x0) * k) / 2
    oy = omr.y0 + (omr.height - (y1 - y0) * k) / 2

    def T(x, y):
        return fitz.Point(ox + (x - x0) * k, oy + (y1 - y) * k)

    # gitter hver 10 m
    sh = p.new_shape()
    gx = math.ceil(x0 / 10) * 10
    while gx <= x1:
        sh.draw_line(T(gx, y0), T(gx, y1))
        gx += 10
    gy = math.ceil(y0 / 10) * 10
    while gy <= y1:
        sh.draw_line(T(x0, gy), T(x1, gy))
        gy += 10
    sh.finish(color=(0.85, 0.85, 0.85), width=0.3)
    sh.commit()
    gx = math.ceil(x0 / 10) * 10
    while gx <= x1:
        q = T(gx, y0)
        D.tekst(q.x - 8, q.y + 9, "%d" % gx, size=6, farve=GRAA)
        gx += 10
    gy = math.ceil(y0 / 10) * 10
    while gy <= y1:
        q = T(x0, gy)
        D.tekst(q.x - 16, q.y + 2, "%d" % gy, size=6, farve=GRAA)
        gy += 10

    # dybdebånd
    xy = flade.xy
    for b in np.unique(flade.baand):
        iv = projekt.intervaller[b] if b < len(projekt.intervaller) else None
        c = tuple(iv["farve"]) if iv else (0.8, 0.8, 0.8)
        sh = p.new_shape()
        for t in flade.tri[flade.baand == b]:
            sh.draw_polyline([T(*xy[t[0]]), T(*xy[t[1]]), T(*xy[t[2]]), T(*xy[t[0]])])
        sh.finish(color=c, fill=c, width=0.25, closePath=True)
        sh.commit()

    # omrids
    sh = p.new_shape()
    for g in shapely.get_parts(flade.omrids):
        for ring in [g.exterior] + list(g.interiors):
            sh.draw_polyline([T(*c) for c in ring.coords])
    sh.finish(color=SORT, width=0.9, closePath=False)
    sh.commit()

    # kasser
    for kk in projekt.kasser:
        if not kk.gyldig():
            continue
        pts = [T(*c) for c in kk.hjoerner()]
        sh = p.new_shape()
        sh.draw_polyline(pts + [pts[0]])
        if kk.aktiv:
            sh.finish(color=ROED, fill=ROED, fill_opacity=0.18, width=1.3, closePath=True)
        else:
            sh.finish(color=GRAA, width=0.9, dashes="[3 2] 0", closePath=True)
        sh.commit()
        c = T(kk.cx, kk.cy)
        kr = res.kasser.get(kk.id)
        farve = ROED if kk.aktiv else GRAA
        D.tekst(c.x - _bredde(kk.id, 8, True) / 2, c.y, kk.id, size=8, bold=True, farve=farve)
        undertekst = ("-%s m³" % dk(kr.fradrag, 1)) if (kr and kk.aktiv) else "slået fra"
        D.tekst(c.x - _bredde(undertekst, 6.5) / 2, c.y + 8, undertekst, size=6.5, farve=farve)

    # nordpil
    nx, ny = omr.x1 - 18, omr.y0 + 10
    sh = p.new_shape()
    sh.draw_polyline([fitz.Point(nx, ny), fitz.Point(nx - 6, ny + 18), fitz.Point(nx, ny + 13), fitz.Point(nx + 6, ny + 18), fitz.Point(nx, ny)])
    sh.finish(color=SORT, fill=SORT, width=0.6, closePath=True)
    sh.commit()
    D.tekst(nx - 3.5, ny + 29, "N", size=9, bold=True)

    # målestokslinje
    laengde = 10 if (x1 - x0) < 120 else 20
    sx, sy = omr.x0 + 4, omr.y1 - 4
    for i in range(2):
        r = fitz.Rect(sx + i * laengde / 2 * k, sy - 4, sx + (i + 1) * laengde / 2 * k, sy)
        p.draw_rect(r, color=SORT, fill=SORT if i == 0 else (1, 1, 1), width=0.5)
    D.tekst(sx - 2, sy - 7, "0", size=6.5)
    D.tekst(sx + laengde * k - 8, sy - 7, "%d m" % laengde, size=6.5)

    # legende
    lx = w - M - legende_b
    ly = M + 48
    D.tekst(lx, ly, "Dybde under terræn", size=8.5, bold=True)
    ly += 8
    for iv in sorted(projekt.intervaller, key=lambda iv: iv["dybde_min"]):
        if iv["dybde_max"] <= 0:
            continue
        p.draw_rect(fitz.Rect(lx, ly, lx + 16, ly + 9), color=GRAA, fill=tuple(iv["farve"]), width=0.3)
        D.tekst(lx + 21, ly + 7.5, interval_tekst(iv), size=7)
        ly += 11.5
    ly += 8
    sh = p.new_shape()
    sh.draw_rect(fitz.Rect(lx, ly, lx + 16, ly + 9))
    sh.finish(color=ROED, fill=ROED, fill_opacity=0.18, width=1.2)
    sh.commit()
    D.tekst(lx + 21, ly + 7.5, "Aktiv kasse (fradrag)", size=7)
    ly += 13
    sh = p.new_shape()
    sh.draw_rect(fitz.Rect(lx, ly, lx + 16, ly + 9))
    sh.finish(color=GRAA, width=0.9, dashes="[3 2] 0")
    sh.commit()
    D.tekst(lx + 21, ly + 7.5, "Kasse slået fra", size=7)
    ly += 22

    # titelblok
    tb = fitz.Rect(lx, h - M - 14 - 92, w - M, h - M - 14)
    p.draw_rect(tb, color=SORT, width=0.6)
    rows = [("Projekt", projekt.navn), ("Indhold", "Volumenmodel og kasser"),
            ("Målestok", "1:%d (A4)" % maal), ("Dato", datetime.date.today().strftime("%d-%m-%Y")),
            ("Med fradrag", "%s m³" % dk(res.netto)), ("Uden fradrag", "%s m³" % dk(res.brutto))]
    yy = tb.y0 + 11
    for nav, v in rows:
        D.tekst(tb.x0 + 4, yy, nav, size=6.5, farve=GRAA)
        D.tekst(tb.x0 + 52, yy, _forkort(v, 7, True, tb.width - 56), size=7, bold=True)
        yy += 14
