"""Projektfil (JSON): dybdeflade, intervaller, kilde, baggrund, indstillinger og kasser."""
from __future__ import annotations

import datetime
import json
import math
import re
from dataclasses import asdict, fields

import numpy as np

from . import APP_VERSION
from .geometri import Flade, Kasse

FORMAT = "vita-udgravningsmodel"
FORMAT_VERSION = 1


def _nu():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _brutto_raa(xy, d, tri):
    a, b, c = xy[tri[:, 0]], xy[tri[:, 1]], xy[tri[:, 2]]
    ar = np.abs((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])) / 2
    return float((ar * d[tri].mean(axis=1)).sum())


class Projekt:
    def __init__(self, navn, flade, intervaller, kilde, baggrund=None, kasser=None,
                 indstillinger=None, oprettet=None, gemt=None):
        self.navn = navn
        self.xy = np.asarray(flade["xy"], float)
        self.d = np.asarray(flade["d"], float)
        self.tri = np.asarray(flade["tri"], np.int64)
        self.baand = np.asarray(flade.get("baand", np.zeros(len(self.tri))), np.int64)
        self.intervaller = intervaller
        self.kilde = kilde
        self.baggrund = baggrund
        self.kasser = list(kasser or [])
        self.indstillinger = {"terraenkote": 0.0, "kalibrer": True}
        self.indstillinger.update(indstillinger or {})
        self.oprettet = oprettet or _nu()
        self.gemt = gemt
        self._raa_brutto = _brutto_raa(self.xy, self.d, self.tri)

    # -- beregningsgrundlag ----------------------------------------------------
    @property
    def raa_volumen(self):
        return self._raa_brutto

    @property
    def reference_volumen(self):
        return self.kilde.get("reference_volumen")

    def kalibreringsfaktor(self):
        ref = self.reference_volumen
        if self.indstillinger.get("kalibrer") and ref and self._raa_brutto > 0:
            return ref / self._raa_brutto
        return 1.0

    def byg_flade(self):
        return Flade(self.xy, self.d * self.kalibreringsfaktor(), self.tri, self.baand)

    @property
    def terraenkote(self):
        return float(self.indstillinger.get("terraenkote", 0.0))

    # -- kasser ----------------------------------------------------------------
    def naeste_kasse_id(self):
        nr = [int(m.group(1)) for k in self.kasser for m in [re.fullmatch(r"K(\d+)", k.id or "")] if m]
        return "K%d" % (max(nr, default=0) + 1)

    def kasse_noegle(self):
        return tuple((k.id, bool(k.aktiv)) + k.geometrinoegle() for k in self.kasser)

    # -- JSON ----------------------------------------------------------------------
    def til_dict(self):
        iv = []
        for i in self.intervaller:
            j = dict(i)
            for k in ("dybde_min", "dybde_max"):
                if j.get(k) is not None and not math.isfinite(j[k]):
                    j[k] = None
            iv.append(j)
        return {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "app_version": APP_VERSION,
            "navn": self.navn,
            "oprettet": self.oprettet,
            "gemt": _nu(),
            "kilde": self.kilde,
            "indstillinger": self.indstillinger,
            "intervaller": iv,
            "kasser": [asdict(k) for k in self.kasser],
            "flade": {
                "xy": np.round(self.xy, 4).tolist(),
                "d": np.round(self.d, 4).tolist(),
                "tri": self.tri.tolist(),
                "baand": self.baand.tolist(),
            },
            "baggrund": self.baggrund,
        }

    def til_json(self):
        return json.dumps(self.til_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def fra_dict(cls, data):
        if data.get("format") != FORMAT:
            raise ValueError("Filen er ikke en udgravningsmodel (%s)." % data.get("format"))
        iv = []
        for i in data["intervaller"]:
            j = dict(i)
            if j.get("dybde_min") is None:
                j["dybde_min"] = -math.inf
            if j.get("dybde_max") is None:
                j["dybde_max"] = math.inf
            iv.append(j)
        navne = {f.name for f in fields(Kasse)}
        kasser = [Kasse(**{k: v for k, v in kd.items() if k in navne}) for kd in data.get("kasser", [])]
        return cls(data.get("navn", "Udgravning"), data["flade"], iv, data.get("kilde", {}),
                   baggrund=data.get("baggrund"), kasser=kasser, indstillinger=data.get("indstillinger"),
                   oprettet=data.get("oprettet"), gemt=data.get("gemt"))

    @classmethod
    def fra_json(cls, tekst):
        return cls.fra_dict(json.loads(tekst))

    @classmethod
    def fra_import(cls, navn, imp, kildefil=None):
        kilde = dict(imp["kilde"])
        if kildefil:
            kilde["fil"] = kildefil
        return cls(navn, imp["flade"], imp["intervaller"], kilde, baggrund=imp.get("baggrund"))


def interval_tekst(iv):
    """Dybdeinterval som tekst, fx '0,20 - 0,40 m' eller 'over 3,00 m'."""
    lo, hi = iv["dybde_min"] + 0.0, iv["dybde_max"] + 0.0  # + 0.0 fjerner -0
    f = lambda v: ("%.2f" % (v + 0.0)).replace(".", ",")
    if not math.isfinite(hi):
        return "over %s m" % f(lo)
    if not math.isfinite(lo):
        return "under %s m" % f(hi)
    return "%s - %s m" % (f(lo), f(hi))


def filnavn(navn):
    s = re.sub(r"[^\w\-. æøåÆØÅ]", "", navn).strip().replace(" ", "_")
    return (s or "udgravning") + ".json"
