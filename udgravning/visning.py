"""Plotly-figurer: plan (med tegning af kasser) og 3D-model."""
from __future__ import annotations

import math

import numpy as np
import plotly.graph_objects as go
import shapely

AKTIV_FARVE = "rgb(200,30,45)"
AKTIV_FYLD = "rgba(200,30,45,0.22)"
INAKTIV_FARVE = "rgb(120,120,120)"
TERRAEN_FARVE = "rgb(196,190,178)"


def rgb(c):
    return "rgb(%d,%d,%d)" % tuple(int(round(v * 255)) for v in c[:3])


def dk(v, dec=2):
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def dybde_farveskala(intervaller, dmax):
    """Trinvis farveskala (positioner, farver) for dybde 0..zmax plus zmin/zmax."""
    bnd = []
    for iv in intervaller:
        lo, hi = iv["dybde_min"], iv["dybde_max"]
        if hi <= 0:
            continue
        lo = max(lo, 0.0) if math.isfinite(lo) else 0.0
        bnd.append((lo, hi, rgb(iv["farve"])))
    bnd.sort()
    zmin = 0.0
    endelige = [hi for _, hi, _ in bnd if math.isfinite(hi)]
    zmax = max([dmax] + endelige) + 1e-6
    skala = []
    for lo, hi, farve in bnd:
        hi = zmax if not math.isfinite(hi) else min(hi, zmax)
        p0 = (lo - zmin) / (zmax - zmin)
        p1 = (hi - zmin) / (zmax - zmin)
        skala.append([max(0.0, min(1.0, p0)), farve])
        skala.append([max(0.0, min(1.0, p1)), farve])
    if not skala:
        skala = [[0, "rgb(200,200,200)"], [1, "rgb(60,60,60)"]]
    skala[0][0] = 0.0
    skala[-1][0] = 1.0
    return skala, zmin, zmax


def dybderaster(flade, oploesning=0.25):
    x0, y0, x1, y1 = flade.omrids.bounds
    xs = np.arange(math.floor(x0), math.ceil(x1) + oploesning, oploesning)
    ys = np.arange(math.floor(y0), math.ceil(y1) + oploesning, oploesning)
    X, Y = np.meshgrid(xs, ys)
    D = flade.dybde_i(X, Y)
    return xs, ys, D


def kasse_polygon(k):
    h = k.hjoerner()
    return [p[0] for p in h] + [h[0][0]], [p[1] for p in h] + [h[0][1]]


def plan_figur(projekt, flade, raster, res=None, vis_baggrund=True, baggrund_opacitet=0.8,
               vis_dybde=False, vis_inaktive=True, hoejde=680):
    fig = go.Figure()
    bg = projekt.baggrund
    if vis_baggrund and bg:
        fig.add_layout_image(dict(
            source="data:image/jpeg;base64," + bg["jpeg_b64"], xref="x", yref="y",
            x=bg["x0"], y=bg["y1"], sizex=bg["x1"] - bg["x0"], sizey=bg["y1"] - bg["y0"],
            sizing="stretch", layer="below", opacity=baggrund_opacitet))
    if vis_dybde and raster is not None:
        xs, ys, D = raster
        skala, zmin, zmax = dybde_farveskala(projekt.intervaller, float(np.nanmax(D)))
        fig.add_trace(go.Heatmap(
            x=xs, y=ys, z=D, colorscale=skala, zmin=zmin, zmax=zmax, opacity=0.85,
            hovertemplate="Dybde %{z:.2f} m<extra></extra>", name="Dybde",
            colorbar=dict(title="Dybde (m)", thickness=12, len=0.6)))

    # omrids
    for g in shapely.get_parts(flade.omrids):
        for ring in [g.exterior] + list(g.interiors):
            c = np.asarray(ring.coords)
            fig.add_trace(go.Scatter(x=c[:, 0], y=c[:, 1], mode="lines", line=dict(color="black", width=1.6),
                                     hoverinfo="skip", showlegend=False, name="Omrids"))

    # usynligt punktgitter, så rektangelmarkering altid giver en hændelse
    x0, y0, x1, y1 = flade.omrids.bounds
    m = 15.0
    gx = np.arange(math.floor(x0 - m), math.ceil(x1 + m) + 0.01, 0.5)
    gy = np.arange(math.floor(y0 - m), math.ceil(y1 + m) + 0.01, 0.5)
    GX, GY = np.meshgrid(gx, gy)
    fig.add_trace(go.Scattergl(x=GX.ravel(), y=GY.ravel(), mode="markers",
                               marker=dict(size=4, color="rgba(0,0,0,0)"), hoverinfo="none",
                               showlegend=False, name="gitter"))

    # kasser
    for k in projekt.kasser:
        if not k.aktiv and not vis_inaktive:
            continue
        px_, py_ = kasse_polygon(k)
        kr = res.kasser.get(k.id) if res else None
        tekst = "%s %s" % (k.id, k.navn)
        hov = "<b>%s</b><br>%s<br>%s x %s m, rot. %s°<br>Dybde %s - %s m<br>Fradrag %s m³" % (
            k.id, k.navn or "", dk(k.laengde), dk(k.bredde), dk(k.rotation, 1), dk(k.top), dk(k.bund),
            dk(kr.fradrag) if kr else "-")
        if not k.aktiv:
            hov += "<br><i>Slået fra</i>"
        fig.add_trace(go.Scatter(
            x=px_, y=py_, mode="lines", fill="toself",
            fillcolor=AKTIV_FYLD if k.aktiv else "rgba(0,0,0,0)",
            line=dict(color=AKTIV_FARVE if k.aktiv else INAKTIV_FARVE, width=2.2 if k.aktiv else 1.5,
                      dash="solid" if k.aktiv else "dash"),
            hovertemplate=hov + "<extra></extra>", showlegend=False, name=k.id))
        fig.add_trace(go.Scatter(x=[k.cx], y=[k.cy], mode="text", text=[tekst.strip()],
                                 textfont=dict(color=AKTIV_FARVE if k.aktiv else INAKTIV_FARVE, size=12),
                                 hoverinfo="skip", showlegend=False))

    fig.update_layout(
        height=hoejde, margin=dict(l=10, r=10, t=10, b=10), dragmode="select",
        plot_bgcolor="white", uirevision="plan", clickmode="event+select",
        xaxis=dict(range=[x0 - 8, x1 + 8], showgrid=True, gridcolor="rgba(0,0,0,0.08)", zeroline=False,
                   title=None, ticksuffix=" m"),
        yaxis=dict(range=[y0 - 8, y1 + 8], scaleanchor="x", scaleratio=1, showgrid=True,
                   gridcolor="rgba(0,0,0,0.08)", zeroline=False, title=None, ticksuffix=" m"),
        newselection=dict(line=dict(color=AKTIV_FARVE, width=2, dash="dot")),
        activeselection=dict(fillcolor=AKTIV_FYLD, opacity=0.6),
    )
    return fig


def _kasse_kanter(k, z_top, z_bund):
    h = k.hjoerner()
    xs, ys, zs = [], [], []
    for z in (z_top, z_bund):
        for p in h + [h[0]]:
            xs.append(p[0]); ys.append(p[1]); zs.append(z)
        xs.append(None); ys.append(None); zs.append(None)
    for p in h:
        xs += [p[0], p[0], None]
        ys += [p[1], p[1], None]
        zs += [z_top, z_bund, None]
    return xs, ys, zs


def figur_3d(projekt, flade, res, overhoejning=3.0, vis_kasser=True, vis_inaktive=False,
             vis_terraen=True, terraen_opacitet=0.35, hoejde=720):
    z0 = projekt.terraenkote
    v, f = res.verts, res.faces
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    n = np.cross(b - a, c - a)
    nn = np.linalg.norm(n, axis=1)
    op = (n[:, 2] > 0.999 * nn) & (np.abs(a[:, 2] - z0) < 1e-6) & (np.abs(b[:, 2] - z0) < 1e-6) & (np.abs(c[:, 2] - z0) < 1e-6)
    fig = go.Figure()
    dmax = flade.maks_dybde()
    skala, zmin, zmax = dybde_farveskala(projekt.intervaller, dmax)
    rest = f[~op]
    fig.add_trace(go.Mesh3d(
        x=v[:, 0], y=v[:, 1], z=v[:, 2], i=rest[:, 0], j=rest[:, 1], k=rest[:, 2],
        intensity=np.clip(z0 - v[:, 2], zmin, zmax), colorscale=skala, cmin=zmin, cmax=zmax,
        colorbar=dict(title="Dybde (m)", thickness=12, len=0.6), flatshading=False,
        lighting=dict(ambient=0.55, diffuse=0.7, specular=0.05, roughness=0.9),
        lightposition=dict(x=100, y=200, z=300),
        hovertemplate="x %{x:.2f}  y %{y:.2f}<br>Kote %{z:.2f}<extra></extra>", name="Udgravning"))
    if vis_terraen and op.any():
        t = f[op]
        fig.add_trace(go.Mesh3d(
            x=v[:, 0], y=v[:, 1], z=v[:, 2], i=t[:, 0], j=t[:, 1], k=t[:, 2],
            color=TERRAEN_FARVE, opacity=terraen_opacitet, flatshading=True, hoverinfo="skip",
            name="Terræn"))
    if vis_kasser:
        for k in projekt.kasser:
            if not k.aktiv and not vis_inaktive:
                continue
            zt = z0 - max(k.top, 0.0)
            zb = z0 - min(k.bund, dmax + 0.5)
            xs, ys, zs = _kasse_kanter(k, zt, zb)
            farve = AKTIV_FARVE if k.aktiv else INAKTIV_FARVE
            fig.add_trace(go.Scatter3d(x=xs, y=ys, z=zs, mode="lines",
                                       line=dict(color=farve, width=5 if k.aktiv else 3,
                                                 dash="solid" if k.aktiv else "dash"),
                                       hoverinfo="skip", showlegend=False, name=k.id))
            fig.add_trace(go.Scatter3d(x=[k.cx], y=[k.cy], z=[zt + 0.3], mode="text", text=[k.id],
                                       textfont=dict(color=farve, size=13), hoverinfo="skip", showlegend=False))
    x0, y0, x1, y1 = flade.omrids.bounds
    dx, dy = x1 - x0, y1 - y0
    dz = max(dmax, 0.5) * overhoejning
    s = max(dx, dy)
    fig.update_layout(
        height=hoejde, margin=dict(l=0, r=0, t=0, b=0), uirevision="3d",
        scene=dict(
            aspectmode="manual", aspectratio=dict(x=dx / s, y=dy / s, z=dz / s),
            xaxis=dict(title="x (m)", backgroundcolor="white"),
            yaxis=dict(title="y (m)", backgroundcolor="white"),
            zaxis=dict(title="Kote (m)", backgroundcolor="white"),
            camera=dict(eye=dict(x=-0.75, y=-0.95, z=0.62)),
        ),
    )
    return fig
