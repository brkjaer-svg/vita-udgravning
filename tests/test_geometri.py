"""Tjek af geometrikernen mod uafhængige beregninger.

Kør:  py -m pytest tests -q
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from udgravning.geometri import Flade, Kasse, beregn, kasse_fradrag  # noqa: E402

PROJEKT = os.environ.get("UDGRAVNING_TESTPROJEKT")


def gitter_tin(nx=12, ny=10, b=12.0, h=10.0, dybde=lambda x, y: 2.0 + 0 * x):
    xs = np.linspace(0, b, nx + 1)
    ys = np.linspace(0, h, ny + 1)
    X, Y = np.meshgrid(xs, ys)
    xy = np.column_stack([X.ravel(), Y.ravel()])
    d = dybde(xy[:, 0], xy[:, 1])
    tri = []
    for j in range(ny):
        for i in range(nx):
            a = j * (nx + 1) + i
            tri.append((a, a + 1, a + nx + 2))
            tri.append((a, a + nx + 2, a + nx + 1))
    return Flade(xy, d, np.array(tri), np.zeros(len(tri), int))


def numerisk_netto(flade, kasser, n=700):
    """Midtpunktsregel på et fint gitter med analytisk søjlelængde."""
    x0, y0, x1, y1 = flade.omrids.bounds
    xs = np.linspace(x0, x1, n + 1)
    ys = np.linspace(y0, y1, n + 1)
    xc = (xs[:-1] + xs[1:]) / 2
    yc = (ys[:-1] + ys[1:]) / 2
    X, Y = np.meshgrid(xc, yc)
    D = flade.dybde_i(X, Y)
    inde = ~np.isnan(D)
    D = np.where(inde, D, 0.0)
    fjernet = np.zeros_like(D)
    # forening af kasseintervaller pr. punkt: diskretiser dybden fint
    zs = np.linspace(0, max(D.max(), 0.01), 400)
    dz = zs[1] - zs[0]
    zc = zs[:-1] + dz / 2
    for zi in zc:
        daekket = np.zeros_like(D, bool)
        for k in kasser:
            if not k.aktiv:
                continue
            a, b = k.interval()
            if not (a <= zi < b):
                continue
            hp = k.halvplaner()
            m = np.ones_like(D, bool)
            for nx_, ny_, c in hp:
                m &= nx_ * X + ny_ * Y <= c
            daekket |= m
        fjernet += np.where(daekket & (zi < D), dz, 0.0)
    celle = (xs[1] - xs[0]) * (ys[1] - ys[0])
    return float((D * inde).sum() * celle), float((fjernet * inde).sum() * celle)


def test_flad_bund_kasse_inde_i():
    f = gitter_tin()
    assert f.brutto() == pytest.approx(240.0)
    k = Kasse("K1", cx=6, cy=5, laengde=4, bredde=3, top=0.5, bund=1.5)
    r = beregn(f, [k])
    assert r.kasser["K1"].fradrag == pytest.approx(12.0)
    assert r.netto == pytest.approx(228.0)
    assert r.mesh_volumen == pytest.approx(r.netto, rel=1e-9)


def test_kasse_gennem_hele_dybden_og_udenfor():
    f = gitter_tin()
    k = Kasse("K1", cx=0, cy=0, laengde=4, bredde=4, top=-1, bund=10)  # kvart i udgravningen
    r = beregn(f, [k])
    assert r.kasser["K1"].areal == pytest.approx(4.0)
    assert r.kasser["K1"].fradrag == pytest.approx(8.0)
    assert r.mesh_volumen == pytest.approx(r.netto, rel=1e-9)
    k2 = Kasse("K2", cx=50, cy=50)
    r2 = beregn(f, [k2])
    assert r2.kasser["K2"].fradrag == 0.0
    assert r2.kasser["K2"].advarsel


def test_skraa_bund_roterede_overlappende_kasser():
    f = gitter_tin(dybde=lambda x, y: 0.5 + 0.2 * x + 0.1 * y)
    kasser = [
        Kasse("K1", cx=5, cy=5, laengde=6, bredde=3, rotation=30, top=0.8, bund=2.2),
        Kasse("K2", cx=7, cy=4, laengde=5, bredde=4, rotation=-15, top=1.5, bund=9),
        Kasse("K3", cx=3, cy=8, laengde=3, bredde=3, rotation=45, top=0, bund=1.0, aktiv=False),
    ]
    r = beregn(f, kasser)
    brutto_num, fjernet_num = numerisk_netto(f, kasser)
    assert r.brutto == pytest.approx(brutto_num, rel=2e-3)
    assert r.fradrag == pytest.approx(fjernet_num, rel=1e-2)
    assert r.overlap > 0  # K1 og K2 overlapper
    assert r.mesh_volumen == pytest.approx(r.netto, rel=1e-9)
    # enkeltfradrag = forening, når kun én kasse er aktiv
    r1 = beregn(f, [kasser[0]])
    assert r1.fradrag == pytest.approx(r.kasser["K1"].fradrag, rel=1e-12)
    # inaktiv kasse trækker ikke fra
    assert "K3" in r.kasser and not r.kasser["K3"].aktiv


def test_kasser_side_om_side_giver_ingen_dobbeltflader():
    f = gitter_tin()
    kasser = [Kasse("K1", cx=4, cy=5, laengde=4, bredde=4, top=0, bund=1),
              Kasse("K2", cx=8, cy=5, laengde=4, bredde=4, top=0, bund=1)]
    r = beregn(f, kasser)
    assert r.fradrag == pytest.approx(32.0)
    assert r.mesh_volumen == pytest.approx(r.netto, rel=1e-9)


@pytest.mark.skipif(not PROJEKT, reason="sæt UDGRAVNING_TESTPROJEKT til en projektfil")
def test_rigtigt_projekt():
    from udgravning.model import Projekt
    with open(PROJEKT, encoding="utf-8") as fh:
        p = Projekt.fra_json(fh.read())
    f = p.byg_flade()
    assert f.brutto() == pytest.approx(p.reference_volumen, rel=1e-9)
    x0, y0, x1, y1 = f.omrids.bounds
    rng = np.random.default_rng(7)
    kasser = []
    for i in range(6):
        kasser.append(Kasse("K%d" % (i + 1), cx=float(rng.uniform(x0, x1)), cy=float(rng.uniform(y0, y1)),
                            laengde=float(rng.uniform(3, 15)), bredde=float(rng.uniform(3, 10)),
                            rotation=float(rng.uniform(-90, 90)), top=float(rng.uniform(-0.5, 1.5)),
                            bund=float(rng.uniform(1.6, 4.0))))
    r = beregn(f, kasser)
    assert r.mesh_volumen == pytest.approx(r.netto, rel=1e-6)
    _, fjernet_num = numerisk_netto(f, kasser, n=500)
    assert r.fradrag == pytest.approx(fjernet_num, rel=2e-2)
    for k in kasser:
        v, _ = kasse_fradrag(f, k)
        assert v == pytest.approx(r.kasser[k.id].fradrag)
