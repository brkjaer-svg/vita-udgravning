"""VITA Udgravningsmodel: Streamlit-brugerflade.

Start:  py -m streamlit run app.py   (eller dobbeltklik start.bat)
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from udgravning import APP_NAVN, APP_VERSION  # noqa: E402
from udgravning.geometri import Kasse, beregn  # noqa: E402
from udgravning.model import Projekt, filnavn, interval_tekst  # noqa: E402
from udgravning.visning import dk, dybderaster, figur_3d, plan_figur  # noqa: E402

def projektmappe():
    """Mappe til projektfiler: miljøvariablen UDGRAVNING_PROJEKTER, ellers første linje i
    projektmappe.txt ved siden af app.py, ellers ./projekter. Sagsdata hører ikke i git."""
    if os.environ.get("UDGRAVNING_PROJEKTER"):
        return Path(os.environ["UDGRAVNING_PROJEKTER"])
    fil = APP_DIR / "projektmappe.txt"
    if fil.exists():
        for linje in fil.read_text(encoding="utf-8-sig").splitlines():
            linje = linje.strip()
            if linje and not linje.startswith("#"):
                return Path(os.path.expandvars(linje))
    return APP_DIR / "projekter"


PROJ_DIR = projektmappe()
PROJ_DIR.mkdir(parents=True, exist_ok=True)

st.set_page_config(page_title="Udgravningsmodel", page_icon=":material/landscape:", layout="wide")
ss = st.session_state
for n, v in {"projekt": None, "sti": None, "gemt_noegle": None, "editor_ver": 0, "plan_ver": 0,
             "proj_ver": 0, "sidst_uploadet": None, "brugt_sel": None, "res_cache": {}, "eksport": {}}.items():
    ss.setdefault(n, v)


# ---------------------------------------------------------------------------
# Tilstand
# ---------------------------------------------------------------------------

def tilstand(p):
    return (p.navn, tuple(sorted(p.indstillinger.items())), tuple(tuple(asdict(k).items()) for k in p.kasser))


def saet_projekt(p, sti=None):
    ss.projekt = p
    ss.sti = Path(sti) if sti else None
    ss.gemt_noegle = tilstand(p) if sti else None
    ss.editor_ver += 1
    ss.plan_ver += 1
    ss.proj_ver += 1
    ss.brugt_sel = None
    ss.res_cache = {}
    ss.eksport = {}
    for n in ("flade_cache", "raster_cache"):
        ss.pop(n, None)


def aaben_fil(sti):
    with open(sti, encoding="utf-8") as fh:
        saet_projekt(Projekt.fra_json(fh.read()), sti)


def gem(p, sti):
    sti = Path(sti)
    tmp = sti.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(p.til_json())
    os.replace(tmp, sti)
    ss.sti = sti
    ss.gemt_noegle = tilstand(p)


def hent_flade(p):
    noegle = (id(p), round(p.kalibreringsfaktor(), 12))
    c = ss.get("flade_cache")
    if not c or c[0] != noegle:
        c = (noegle, p.byg_flade())
        ss.flade_cache = c
    return c[1]


def hent_raster(p, flade):
    noegle = id(flade)
    c = ss.get("raster_cache")
    if not c or c[0] != noegle:
        c = (noegle, dybderaster(flade, 0.25))
        ss.raster_cache = c
    return c[1]


def hent_resultat(p, flade):
    noegle = (id(flade), p.kasse_noegle(), p.terraenkote)
    cache = ss.res_cache
    if noegle not in cache:
        if len(cache) > 12:
            cache.clear()
        cache[noegle] = beregn(flade, p.kasser, terraenkote=p.terraenkote, med_mesh=True)
    return noegle, cache[noegle]


# ---------------------------------------------------------------------------
# Kassetabel
# ---------------------------------------------------------------------------

KOLONNER = ["aktiv", "id", "navn", "cx", "cy", "laengde", "bredde", "rotation", "top", "bund", "note"]


def kasser_df(kasser):
    return pd.DataFrame([{c: getattr(k, c) for c in KOLONNER} for k in kasser], columns=KOLONNER)


def df_til_kasser(df, base_ids, standard):
    nr = [int(i[1:]) for i in base_ids if isinstance(i, str) and i[1:].isdigit()]
    naeste = max(nr, default=0) + 1
    kasser = []
    for _, r in df.iterrows():
        kid = r.get("id")
        if not isinstance(kid, str) or not kid:
            kid = "K%d" % naeste
            naeste += 1

        def tal(navn):
            v = r.get(navn)
            try:
                v = float(v)
            except (TypeError, ValueError):
                return float(standard[navn])
            return float(standard[navn]) if math.isnan(v) else v

        aktiv = r.get("aktiv")
        kasser.append(Kasse(
            id=kid, navn="" if pd.isna(r.get("navn")) else str(r.get("navn")),
            aktiv=True if aktiv is None or pd.isna(aktiv) else bool(aktiv),
            cx=tal("cx"), cy=tal("cy"), laengde=tal("laengde"), bredde=tal("bredde"),
            rotation=tal("rotation"), top=tal("top"), bund=tal("bund"),
            note="" if pd.isna(r.get("note")) else str(r.get("note"))))
    return kasser


def boks_fra_event(ev):
    try:
        sel = ev["selection"] if isinstance(ev, dict) else ev.selection
        bokse = sel["box"] if isinstance(sel, dict) else sel.box
    except Exception:
        return None
    if not bokse:
        return None
    b = bokse[-1]
    xs, ys = b.get("x"), b.get("y")
    if not xs or not ys or len(xs) < 2 or len(ys) < 2:
        return None
    x0, x1 = sorted(float(v) for v in xs[:2])
    y0, y1 = sorted(float(v) for v in ys[:2])
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:
        return None
    return x0, x1, y0, y1


# ---------------------------------------------------------------------------
# Sidepanel
# ---------------------------------------------------------------------------

filer = sorted(PROJ_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
if ss.projekt is None and filer and not ss.get("auto_aabnet"):
    ss.auto_aabnet = True
    try:
        aaben_fil(filer[0])
    except Exception as e:  # noqa: BLE001
        st.toast("Kunne ikke åbne %s: %s" % (filer[0].name, e))

with st.sidebar:
    st.markdown("### :material/landscape: Udgravningsmodel")
    st.caption("%s %s" % (APP_NAVN, APP_VERSION))

    st.markdown("**Projekt**")
    if filer:
        valgt = st.selectbox("Gemte projekter", filer, format_func=lambda f: f.stem,
                             index=filer.index(ss.sti) if ss.sti in filer else 0)
        if st.button("Åbn projekt", icon=":material/folder_open:", width="stretch"):
            aaben_fil(valgt)
            st.rerun()
    up = st.file_uploader("Åbn projektfil (.json)", type=["json"])
    if up is not None and ss.sidst_uploadet != up.file_id:
        ss.sidst_uploadet = up.file_id
        try:
            saet_projekt(Projekt.fra_json(up.getvalue().decode("utf-8")))
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error("Filen kunne ikke åbnes: %s" % e)

    with st.expander("Ny model fra volumenrapport (PDF)", icon=":material/picture_as_pdf:"):
        st.caption("Rapport af typen \"Volume Report, Model To Model\" med farvekort og "
                   "\"Height Intervals and Areas\".")
        pdf = st.file_uploader("Volumenrapport", type=["pdf"], key="pdf_upload")
        nyt_navn = st.text_input("Projektnavn", value=Path(pdf.name).stem if pdf else "")
        if st.button("Opret model", disabled=pdf is None, type="primary", width="stretch"):
            from udgravning.pdf_import import ImportFejl, importer_pdf
            try:
                with st.status("Indlæser volumenrapport", expanded=True) as status:
                    imp = importer_pdf(pdf.getvalue(), status=status.write)
                    status.update(label="Model oprettet", state="complete")
                saet_projekt(Projekt.fra_import(nyt_navn or "Udgravning", imp, kildefil=pdf.name))
                st.rerun()
            except ImportFejl as e:
                st.error(str(e))

    p = ss.projekt
    if p is not None:
        st.divider()
        st.markdown("**Gem**")
        fn = st.text_input("Filnavn", value=ss.sti.name if ss.sti else filnavn(p.navn), key="fn_%d" % ss.proj_ver)
        if not fn.lower().endswith(".json"):
            fn += ".json"
        c1, c2 = st.columns(2)
        if c1.button("Gem", icon=":material/save:", type="primary", width="stretch"):
            gem(p, PROJ_DIR / Path(fn).name)
            st.toast("Gemt: %s" % (PROJ_DIR / Path(fn).name))
        c2.download_button("Download", data=p.til_json(), file_name=Path(fn).name, mime="application/json",
                           icon=":material/download:", width="stretch")
        if ss.gemt_noegle != tilstand(p):
            st.caption(":orange[Ændringer er ikke gemt]")
        elif ss.sti:
            st.caption("Gemt i %s" % ss.sti)

        st.divider()
        st.markdown("**Indstillinger**")
        p.navn = st.text_input("Projektnavn i rapport og IFC", value=p.navn, key="navn_%d" % ss.proj_ver)
        p.indstillinger["terraenkote"] = st.number_input(
            "Terrænkote (top af model), m", value=float(p.terraenkote), step=0.1, format="%.2f",
            key="tk_%d" % ss.proj_ver,
            help="Bruges som kote for modellens top i 3D og IFC. Rapporten er en differensmodel, "
                 "så toppen er vandret.")
        ref = p.reference_volumen
        p.indstillinger["kalibrer"] = st.checkbox(
            "Kalibrér til rapportens volumen", value=bool(p.indstillinger.get("kalibrer", True)),
            disabled=not ref, key="kal_%d" % ss.proj_ver,
            help="Skalerer dybderne en anelse, så volumen uden fradrag svarer præcist til rapportens "
                 "%s m³. Uden kalibrering bruges den rekonstruerede model (%s m³)." % (dk(ref or 0), dk(p.raa_volumen)))


# ---------------------------------------------------------------------------
# Hovedområde
# ---------------------------------------------------------------------------

p = ss.projekt
if p is None:
    st.title("Udgravningsmodel")
    st.info("Åbn et gemt projekt, eller opret en ny model fra en volumenrapport (PDF) i menuen til venstre.")
    st.stop()

flade = hent_flade(p)
res_noegle, res = hent_resultat(p, flade)
maks_d = flade.maks_dybde()
std_bund = math.ceil((maks_d + 0.5) * 10) / 10

st.title(p.navn)
k = p.kilde
st.caption("Grundlag: %s · rapport %s · referencevolumen %s m³ · areal %s m²" % (
    k.get("fil", "-"), k.get("dato") or "-", dk(k.get("reference_volumen") or 0), dk(res.areal)))

aktive = [kk for kk in p.kasser if kk.aktiv]
m1, m2, m3, m4 = st.columns(4)
m1.metric("Volumen uden fradrag", "%s m³" % dk(res.brutto))
m2.metric("Fradrag (aktive kasser)", "%s m³" % dk(-res.fradrag) if res.fradrag > 0 else "0,00 m³")
m3.metric("Volumen med fradrag", "%s m³" % dk(res.netto))
m4.metric("Kasser", "%d af %d aktive" % (len(aktive), len(p.kasser)))

fane_plan, fane_3d, fane_opg, fane_eks = st.tabs([":material/draw: Plan og kasser", ":material/view_in_ar: 3D-model",
                                                  ":material/table: Opgørelse", ":material/ios_share: Eksport"])

# -- Plan og kasser -------------------------------------------------------------
with fane_plan:
    venstre, hoejre = st.columns([3.2, 1])
    with hoejre:
        st.markdown("**Visning**")
        vis_bg = st.toggle("Baggrund fra rapporten", value=True, disabled=not p.baggrund)
        bg_op = st.slider("Baggrundens styrke", 0.1, 1.0, 0.75, 0.05, disabled=not vis_bg)
        vis_d = st.toggle("Modellens dybdekort", value=False,
                          help="Viser den rekonstruerede dybde (kontrol mod rapportens farvekort).")
        vis_ina = st.toggle("Vis kasser, der er slået fra", value=True)
    with venstre:
        fig = plan_figur(p, flade, hent_raster(p, flade) if vis_d else None, res, vis_baggrund=vis_bg,
                         baggrund_opacitet=bg_op, vis_dybde=vis_d, vis_inaktive=vis_ina)
        ev = st.plotly_chart(fig, key="plan_%d" % ss.plan_ver, on_select="rerun", selection_mode=("box",),
                             width="stretch",
                             config={"scrollZoom": True, "displaylogo": False,
                                     "modeBarButtonsToRemove": ["lasso2d", "autoScale2d", "toImage"]})
        st.caption("Tegn en kasse ved at trække et rektangel i planen. Rul for at zoome; vælg "
                   "panorér i værktøjslinjen for at flytte udsnittet. Dobbeltklik nulstiller markeringen.")
    sel = boks_fra_event(ev)
    if sel is not None and sel == ss.brugt_sel:
        sel = None  # markeringen er allerede brugt til en kasse
    with hoejre:
        st.markdown("**Ny kasse**")
        if sel:
            x0, x1, y0, y1 = sel
            st.caption("Markering: %s x %s m, centrum (%s; %s)" % (dk(x1 - x0), dk(y1 - y0),
                                                                  dk((x0 + x1) / 2), dk((y0 + y1) / 2)))
            with st.form("ny_kasse", border=False):
                navn = st.text_input("Navn", placeholder="fx Eksisterende fundament")
                c1, c2 = st.columns(2)
                top = c1.number_input("Top (m u. terræn)", value=0.0, step=0.1, format="%.2f")
                bund = c2.number_input("Bund (m u. terræn)", value=std_bund, step=0.1, format="%.2f")
                rot = st.number_input("Rotation (°, mod uret)", value=0.0, step=1.0, format="%.1f",
                                      help="Kassen drejes om sit centrum.")
                if st.form_submit_button("Tilføj kasse", type="primary", icon=":material/add_box:",
                                         width="stretch"):
                    if bund <= top:
                        st.error("Bunden skal ligge under toppen.")
                    else:
                        p.kasser.append(Kasse(id=p.naeste_kasse_id(), navn=navn, aktiv=True,
                                              cx=round((x0 + x1) / 2, 3), cy=round((y0 + y1) / 2, 3),
                                              laengde=round(x1 - x0, 3), bredde=round(y1 - y0, 3),
                                              rotation=rot, top=top, bund=bund))
                        ss.brugt_sel = sel
                        ss.editor_ver += 1
                        st.rerun()
        else:
            st.caption("Træk et rektangel i planen. Kassen kan bagefter drejes og justeres i tabellen nedenfor.")

    st.markdown("#### Kasser")
    b1, b2, _ = st.columns([1, 1, 5])
    if b1.button("Slå alle til", icon=":material/toggle_on:", width="stretch", disabled=not p.kasser):
        for kk in p.kasser:
            kk.aktiv = True
        ss.editor_ver += 1
        st.rerun()
    if b2.button("Slå alle fra", icon=":material/toggle_off:", width="stretch", disabled=not p.kasser):
        for kk in p.kasser:
            kk.aktiv = False
        ss.editor_ver += 1
        st.rerun()

    if ss.get("editor_base_ver") != ss.editor_ver:
        ss.editor_base = kasser_df(p.kasser)
        ss.editor_base_ver = ss.editor_ver
    x0o, y0o, x1o, y1o = flade.omrids.bounds
    standard = {"cx": round((x0o + x1o) / 2, 2), "cy": round((y0o + y1o) / 2, 2), "laengde": 5.0, "bredde": 5.0,
                "rotation": 0.0, "top": 0.0, "bund": std_bund}
    ed = st.data_editor(
        ss.editor_base, key="editor_%d" % ss.editor_ver, num_rows="dynamic", hide_index=True,
        width="stretch",
        column_config={
            "aktiv": st.column_config.CheckboxColumn("Aktiv", default=True, width="small",
                                                     help="Slå kassen til eller fra i fradraget"),
            "id": st.column_config.TextColumn("ID", disabled=True, width="small"),
            "navn": st.column_config.TextColumn("Navn", width="medium"),
            "cx": st.column_config.NumberColumn("X (m)", format="%.2f", step=0.01, default=standard["cx"]),
            "cy": st.column_config.NumberColumn("Y (m)", format="%.2f", step=0.01, default=standard["cy"]),
            "laengde": st.column_config.NumberColumn("Længde (m)", format="%.2f", min_value=0.01, step=0.01, default=5.0),
            "bredde": st.column_config.NumberColumn("Bredde (m)", format="%.2f", min_value=0.01, step=0.01, default=5.0),
            "rotation": st.column_config.NumberColumn("Rotation (°)", format="%.1f", step=0.5, default=0.0),
            "top": st.column_config.NumberColumn("Top (m u. terræn)", format="%.2f", step=0.05, default=0.0),
            "bund": st.column_config.NumberColumn("Bund (m u. terræn)", format="%.2f", step=0.05, default=std_bund),
            "note": st.column_config.TextColumn("Note", width="medium"),
        },
    )
    nye = df_til_kasser(ed, list(ss.editor_base["id"]), standard)
    if nye != p.kasser:
        nye_id = {kk.id for kk in nye} - set(ss.editor_base["id"])
        p.kasser = nye
        if nye_id:  # vis de tildelte ID'er i tabellen
            ss.editor_ver += 1
        st.rerun()

    if p.kasser:
        rk = []
        for kk in p.kasser:
            kr = res.kasser.get(kk.id)
            rk.append({"ID": kk.id, "Navn": kk.navn, "Status": "Aktiv" if kk.aktiv else "Slået fra",
                       "Areal i udgravning (m²)": kr.areal if kr else None,
                       "Fradrag (m³)": kr.fradrag if kr else None,
                       "Bemærkning": kr.advarsel if kr else ""})
        st.dataframe(pd.DataFrame(rk), hide_index=True, width="stretch",
                     column_config={"Areal i udgravning (m²)": st.column_config.NumberColumn(format="%.2f"),
                                    "Fradrag (m³)": st.column_config.NumberColumn(format="%.2f")})
        if res.overlap > 0.0005:
            st.info("Aktive kasser overlapper: %s m³ indgår i flere kasser og er kun trukket fra én gang."
                    % dk(res.overlap))
    else:
        st.caption("Ingen kasser endnu.")

# -- 3D --------------------------------------------------------------------------
with fane_3d:
    c1, c2, c3, c4 = st.columns(4)
    oh = c1.slider("Overhøjning", 1.0, 10.0, 3.0, 0.5, help="Lodret overdrivelse af dybderne")
    vis_k = c2.toggle("Vis kasser", value=True)
    vis_ki = c2.toggle("Vis kasser, der er slået fra", value=False)
    vis_t = c3.toggle("Vis terrænflade (top)", value=True)
    t_op = c4.slider("Terrænfladens synlighed", 0.0, 1.0, 0.35, 0.05, disabled=not vis_t)
    st.plotly_chart(figur_3d(p, flade, res, overhoejning=oh, vis_kasser=vis_k, vis_inaktive=vis_ki,
                             vis_terraen=vis_t, terraen_opacitet=t_op),
                    width="stretch", key="fig3d", config={"displaylogo": False})
    st.caption("Netto-modellen er et lukket legeme med kasserne skåret ud: %s m³ (beregnet %s m³)." % (
        dk(res.mesh_volumen), dk(res.netto)))

# -- Opgørelse -------------------------------------------------------------------
with fane_opg:
    st.markdown("#### Samlet")
    st.dataframe(pd.DataFrame([
        {"Post": "Udgravning uden fradrag", "Volumen (m³)": res.brutto},
        {"Post": "Fradrag, aktive kasser", "Volumen (m³)": -res.fradrag},
        {"Post": "Udgravning med fradrag", "Volumen (m³)": res.netto},
    ]), hide_index=True, column_config={"Volumen (m³)": st.column_config.NumberColumn(format="%.2f")})
    if aktive:
        st.markdown("#### Fradrag pr. aktiv kasse")
        rk = [{"ID": kk.id, "Navn": kk.navn, "L x B (m)": "%s x %s" % (dk(kk.laengde), dk(kk.bredde)),
               "Rotation (°)": kk.rotation, "Dybde (m u. t.)": "%s - %s" % (dk(kk.top), dk(kk.bund)),
               "Areal (m²)": res.kasser[kk.id].areal, "Fradrag (m³)": res.kasser[kk.id].fradrag} for kk in aktive]
        st.dataframe(pd.DataFrame(rk), hide_index=True, width="stretch",
                     column_config={"Areal (m²)": st.column_config.NumberColumn(format="%.2f"),
                                    "Fradrag (m³)": st.column_config.NumberColumn(format="%.2f"),
                                    "Rotation (°)": st.column_config.NumberColumn(format="%.1f")})
        st.caption("Sum af kasser %s m³, overlap %s m³, fradrag i alt %s m³." % (
            dk(res.sum_enkelt_fradrag), dk(res.overlap), dk(res.fradrag)))
    st.markdown("#### Pr. dybdeinterval")
    rk = []
    for b in sorted(res.brutto_pr_baand, key=lambda b: p.intervaller[b]["dybde_min"]):
        iv = p.intervaller[b]
        rk.append({"Dybde": interval_tekst(iv), "Areal (m²)": res.areal_pr_baand[b],
                   "Areal i rapport (m²)": iv.get("areal_rapport"),
                   "Uden fradrag (m³)": res.brutto_pr_baand[b],
                   "Fradrag (m³)": res.brutto_pr_baand[b] - res.netto_pr_baand[b],
                   "Med fradrag (m³)": res.netto_pr_baand[b]})
    st.dataframe(pd.DataFrame(rk), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.2f") for c in
                                ["Areal (m²)", "Areal i rapport (m²)", "Uden fradrag (m³)", "Fradrag (m³)", "Med fradrag (m³)"]})
    with st.expander("Grundlag og kontrol af modellen"):
        ref = k.get("reference_volumen")
        st.markdown(
            "- Målestok bestemt ud fra rapportens areal: 1:%s på papiret; største arealafvigelse pr. interval %s %%\n"
            "- Rekonstrueret volumen: %s m³ mod rapportens %s m³ (%s %%)\n"
            "- Kalibreringsfaktor på dybderne: %s\n"
            "- Største dybde i modellen: %s m\n"
            "- Trekanter: %d" % (
                k.get("maalestok", "-"), dk(k.get("maks_arealafvigelse_pct") or 0, 3), dk(p.raa_volumen),
                dk(ref or 0), dk(((p.raa_volumen / ref) - 1) * 100 if ref else 0, 3),
                dk(p.kalibreringsfaktor(), 5), dk(maks_d), len(flade.tri)))
        if k.get("har_fyld"):
            st.warning("Rapporten indeholder fyld. Modellen opgør kun afgravning (cut).")

# -- Eksport ---------------------------------------------------------------------
with fane_eks:
    ce1, ce2 = st.columns(2)
    with ce1:
        st.markdown("#### IFC")
        st.caption("IFC4. Udgravningen med fradrag som lukket legeme (IfcBuildingElementProxy) med volumener "
                   "som egenskaber (VITA_Udgravning) og mængder (Qto_Udgravning).")
        i_kasser = st.checkbox("Medtag aktive kasser som objekter", value=True)
        i_inaktive = st.checkbox("Medtag også kasser, der er slået fra", value=False, disabled=not i_kasser)
        i_brutto = st.checkbox("Medtag udgravningen uden fradrag som separat objekt", value=False)
        ifc_noegle = (res_noegle, tilstand(p), i_kasser, i_inaktive, i_brutto)
        if st.button("Lav IFC-fil", icon=":material/deployed_code:", type="primary"):
            from udgravning.ifc_eksport import eksporter_ifc
            with st.spinner("Skriver IFC"):
                ss.eksport["ifc"] = (ifc_noegle, eksporter_ifc(p, flade, res, i_kasser, i_inaktive, i_brutto))
        e = ss.eksport.get("ifc")
        if e and e[0] == ifc_noegle:
            st.download_button("Download IFC (%s kB)" % dk(len(e[1]) / 1024, 0), data=e[1],
                               file_name=Path(filnavn(p.navn)).stem + ".ifc", mime="application/x-step",
                               icon=":material/download:")
        elif e:
            st.caption("Modellen er ændret siden sidste IFC-fil. Lav filen igen.")
    with ce2:
        st.markdown("#### PDF-rapport")
        st.caption("Volumenopgørelse med og uden fradrag, fradrag pr. kasse og pr. dybdeinterval samt plan.")
        udarb = st.text_input("Udarbejdet af", value="")
        bem = st.text_area("Bemærkning", value="", height=80)
        pdf_noegle = (res_noegle, tilstand(p), udarb, bem)
        if st.button("Lav PDF-rapport", icon=":material/picture_as_pdf:", type="primary"):
            from udgravning.rapport import lav_pdf
            with st.spinner("Skriver rapport"):
                ss.eksport["pdf"] = (pdf_noegle, lav_pdf(p, flade, res, udarb, bem))
        e = ss.eksport.get("pdf")
        if e and e[0] == pdf_noegle:
            st.download_button("Download PDF (%s kB)" % dk(len(e[1]) / 1024, 0), data=e[1],
                               file_name=Path(filnavn(p.navn)).stem + "_volumenopgoerelse.pdf",
                               mime="application/pdf", icon=":material/download:")
        elif e:
            st.caption("Modellen eller teksten er ændret siden sidste rapport. Lav rapporten igen.")
