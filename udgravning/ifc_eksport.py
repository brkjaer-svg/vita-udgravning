"""Eksport af volumenmodellen til IFC4.

- "Udgravning": IfcBuildingElementProxy med netto-modellen (kasserne skåret ud) som
  lukket IfcTriangulatedFaceSet. Volumener som egenskaber og mængder.
- Valgfrit "Udgravning uden fradrag" (bruttomodellen) som separat objekt.
- Kasserne som IfcBuildingElementProxy (ekstruderet rektangel) med deres fradrag.

Koordinater er modellens lokale system (meter), z = kote.
"""
from __future__ import annotations

import math
import os
import tempfile

import ifcopenshell
import ifcopenshell.guid

from . import APP_NAVN, APP_VERSION
from .geometri import beregn

BRUN = (0.62, 0.45, 0.30)
GRAA = (0.70, 0.66, 0.60)
ROED = (0.80, 0.12, 0.18)


def _g():
    return ifcopenshell.guid.new()


class _Skriver:
    def __init__(self, navn, beskrivelse):
        f = ifcopenshell.file(schema="IFC4")
        self.f = f
        try:
            f.header.file_name.name = navn
            f.header.file_name.originating_system = "%s %s" % (APP_NAVN, APP_VERSION)
            f.header.file_name.preprocessor_version = "IfcOpenShell %s" % ifcopenshell.version
            f.header.file_description.description = ("ViewDefinition [ReferenceView_V1.2]",)
        except Exception:
            pass
        units = f.createIfcUnitAssignment([
            f.createIfcSIUnit(None, "LENGTHUNIT", None, "METRE"),
            f.createIfcSIUnit(None, "AREAUNIT", None, "SQUARE_METRE"),
            f.createIfcSIUnit(None, "VOLUMEUNIT", None, "CUBIC_METRE"),
            f.createIfcSIUnit(None, "PLANEANGLEUNIT", None, "RADIAN"),
        ])
        self.origo = f.createIfcCartesianPoint((0.0, 0.0, 0.0))
        self.wcs = f.createIfcAxis2Placement3D(self.origo, None, None)
        ctx = f.createIfcGeometricRepresentationContext(None, "Model", 3, 1.0e-5, self.wcs,
                                                        f.createIfcDirection((0.0, 1.0)))
        self.body = f.create_entity("IfcGeometricRepresentationSubContext", ContextIdentifier="Body",
                                    ContextType="Model", ParentContext=ctx, TargetView="MODEL_VIEW")
        self.projekt = f.create_entity("IfcProject", GlobalId=_g(), Name=navn, Description=beskrivelse,
                                       RepresentationContexts=[ctx], UnitsInContext=units)
        self.site_pl = f.createIfcLocalPlacement(None, self.wcs)
        self.site = f.create_entity("IfcSite", GlobalId=_g(), Name="Byggeplads", ObjectPlacement=self.site_pl,
                                    CompositionType="ELEMENT")
        f.create_entity("IfcRelAggregates", GlobalId=_g(), RelatingObject=self.projekt, RelatedObjects=[self.site])
        self.elementer = []
        self._stile = {}

    def stil(self, navn, farve, transparens=0.0):
        noegle = (navn, farve, transparens)
        if noegle not in self._stile:
            f = self.f
            rend = f.create_entity("IfcSurfaceStyleRendering",
                                   SurfaceColour=f.createIfcColourRgb(None, *farve),
                                   Transparency=transparens, ReflectanceMethod="NOTDEFINED")
            self._stile[noegle] = f.create_entity("IfcSurfaceStyle", Name=navn, Side="BOTH", Styles=[rend])
        return self._stile[noegle]

    def placering(self, punkt=(0.0, 0.0, 0.0), vinkel=0.0):
        f = self.f
        akse = f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint(tuple(float(v) for v in punkt)),
            f.createIfcDirection((0.0, 0.0, 1.0)),
            f.createIfcDirection((math.cos(vinkel), math.sin(vinkel), 0.0)))
        return f.createIfcLocalPlacement(self.site_pl, akse)

    def proxy(self, navn, objekttype, item, reptype, stil, placering, beskrivelse=None):
        f = self.f
        f.create_entity("IfcStyledItem", Item=item, Styles=[stil])
        rep = f.createIfcShapeRepresentation(self.body, "Body", reptype, [item])
        el = f.create_entity("IfcBuildingElementProxy", GlobalId=_g(), Name=navn, Description=beskrivelse,
                             ObjectType=objekttype, ObjectPlacement=placering,
                             Representation=f.createIfcProductDefinitionShape(None, None, [rep]),
                             PredefinedType="USERDEFINED")
        self.elementer.append(el)
        return el

    def mesh(self, verts, faces):
        f = self.f
        pl = f.createIfcCartesianPointList3D([tuple(float(c) for c in v) for v in verts])
        return f.create_entity("IfcTriangulatedFaceSet", Coordinates=pl, Closed=True,
                               CoordIndex=[tuple(int(i) + 1 for i in t) for t in faces])

    def pset(self, el, navn, egenskaber):
        f = self.f
        props = []
        for n, (typ, v) in egenskaber.items():
            if v is None:
                continue
            props.append(f.create_entity("IfcPropertySingleValue", Name=n,
                                         NominalValue=f.create_entity(typ, v)))
        ps = f.create_entity("IfcPropertySet", GlobalId=_g(), Name=navn, HasProperties=props)
        f.create_entity("IfcRelDefinesByProperties", GlobalId=_g(), RelatedObjects=[el],
                        RelatingPropertyDefinition=ps)

    def maengder(self, el, navn, volumener=None, arealer=None, metode=None):
        f = self.f
        q = []
        for n, v in (volumener or {}).items():
            q.append(f.create_entity("IfcQuantityVolume", Name=n, VolumeValue=float(v)))
        for n, v in (arealer or {}).items():
            q.append(f.create_entity("IfcQuantityArea", Name=n, AreaValue=float(v)))
        eq = f.create_entity("IfcElementQuantity", GlobalId=_g(), Name=navn, MethodOfMeasurement=metode, Quantities=q)
        f.create_entity("IfcRelDefinesByProperties", GlobalId=_g(), RelatedObjects=[el],
                        RelatingPropertyDefinition=eq)

    def afslut(self):
        self.f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=_g(), RelatedElements=self.elementer,
                             RelatingStructure=self.site)
        return self.f


def eksporter_ifc(projekt, flade, res, medtag_kasser=True, medtag_inaktive=False, medtag_brutto=False):
    """Returnér IFC-filen som bytes."""
    z0 = projekt.terraenkote
    k = projekt.kilde
    beskr = "Volumenmodel af udgravning. Grundlag: %s (%s)." % (k.get("fil", "volumenrapport"), k.get("dato") or "-")
    s = _Skriver(projekt.navn, beskr)
    aktive = [kk for kk in projekt.kasser if kk.aktiv]
    grundlag = "%s, %s" % (k.get("fil", "-"), k.get("dato") or "-")
    faktor = projekt.kalibreringsfaktor()

    el = s.proxy("Udgravning", "Udgravning (med fradrag)", s.mesh(res.verts, res.faces), "Tessellation",
                 s.stil("Udgravning", BRUN), s.placering(), beskrivelse="Udgravning med %d aktive kasser skåret ud" % len(aktive))
    s.pset(el, "VITA_Udgravning", {
        "Volumen_uden_fradrag": ("IfcVolumeMeasure", round(res.brutto, 3)),
        "Fradrag": ("IfcVolumeMeasure", round(res.fradrag, 3)),
        "Volumen_med_fradrag": ("IfcVolumeMeasure", round(res.netto, 3)),
        "Areal": ("IfcAreaMeasure", round(res.areal, 3)),
        "Antal_aktive_kasser": ("IfcInteger", len(aktive)),
        "Terraenkote": ("IfcLengthMeasure", z0),
        "Grundlag": ("IfcText", grundlag),
        "Referencevolumen": ("IfcVolumeMeasure", k.get("reference_volumen")),
        "Kalibreringsfaktor": ("IfcReal", round(faktor, 6)),
        "Volumen_type": ("IfcLabel", "Fast indbygget mål"),
    })
    s.maengder(el, "Qto_Udgravning", volumener={"GrossVolume": res.brutto, "NetVolume": res.netto},
               arealer={"GrossArea": res.areal}, metode="Eksakt TIN-integration, kasser fratrukket")

    if medtag_brutto:
        rb = beregn(flade, [], terraenkote=z0, med_mesh=True)
        eb = s.proxy("Udgravning uden fradrag", "Udgravning (uden fradrag)", s.mesh(rb.verts, rb.faces),
                     "Tessellation", s.stil("Udgravning brutto", GRAA, 0.6), s.placering())
        s.pset(eb, "VITA_Udgravning", {
            "Volumen_uden_fradrag": ("IfcVolumeMeasure", round(rb.brutto, 3)),
            "Areal": ("IfcAreaMeasure", round(rb.areal, 3)),
            "Grundlag": ("IfcText", grundlag),
        })
        s.maengder(eb, "Qto_Udgravning", volumener={"GrossVolume": rb.brutto}, arealer={"GrossArea": rb.areal})

    if medtag_kasser:
        for kk in projekt.kasser:
            if not kk.aktiv and not medtag_inaktive:
                continue
            if not kk.gyldig():
                continue
            f = s.f
            top = kk.top
            h = kk.bund - top
            prof = f.create_entity("IfcRectangleProfileDef", ProfileType="AREA", ProfileName=kk.id,
                                   Position=f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)), None),
                                   XDim=float(kk.laengde), YDim=float(kk.bredde))
            solid = f.create_entity("IfcExtrudedAreaSolid", SweptArea=prof, Position=s.wcs,
                                    ExtrudedDirection=f.createIfcDirection((0.0, 0.0, 1.0)), Depth=float(h))
            kr = res.kasser.get(kk.id)
            ek = s.proxy("%s %s" % (kk.id, kk.navn or ""), "Fradragskasse", solid, "SweptSolid",
                         s.stil("Fradragskasse" if kk.aktiv else "Fradragskasse (slået fra)",
                                ROED if kk.aktiv else GRAA, 0.55 if kk.aktiv else 0.8),
                         s.placering((kk.cx, kk.cy, z0 - kk.bund), math.radians(kk.rotation)),
                         beskrivelse=kk.note or None)
            s.pset(ek, "VITA_Fradragskasse", {
                "ID": ("IfcIdentifier", kk.id),
                "Aktiv": ("IfcBoolean", bool(kk.aktiv)),
                "Top_dybde": ("IfcLengthMeasure", float(kk.top)),
                "Bund_dybde": ("IfcLengthMeasure", float(kk.bund)),
                "Rotation_grader": ("IfcReal", float(kk.rotation)),
                "Fradrag": ("IfcVolumeMeasure", round(kr.fradrag, 3) if kr else None),
                "Areal_i_udgravning": ("IfcAreaMeasure", round(kr.areal, 3) if kr else None),
                "Note": ("IfcText", kk.note or None),
            })
    f = s.afslut()
    with tempfile.TemporaryDirectory() as td:
        sti = os.path.join(td, "udgravning.ifc")
        f.write(sti)
        with open(sti, "rb") as fh:
            return fh.read()
