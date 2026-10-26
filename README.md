# VITA Udgravningsmodel

Volumenmodel af en udgravning, bygget ud fra en volumenrapport (PDF), med kasser der
skærer ud i modellen. Brugerfladen er Streamlit og kører lokalt i browseren.

## Start

Dobbeltklik `start.bat`, eller kør i mappen:

```
py -m streamlit run app.py --server.address localhost
```

Appen åbner det senest gemte projekt i projektmappen. Kræver Python med pakkerne i
`requirements.txt` (`py -m pip install -r requirements.txt`).

### Projektmappe

Projektfilerne er sagsdata og ligger ikke i git. Appen finder mappen sådan:

1. miljøvariablen `UDGRAVNING_PROJEKTER`, ellers
2. første linje uden `#` i `projektmappe.txt` ved siden af `app.py` (ignoreres af git), ellers
3. `projekter\` ved siden af `app.py` (ignoreres af git).

Eksempel på `projektmappe.txt`:

```
# Mappe til projektfilerne
C:\Users\<bruger>\OneDrive - VITA Ingeniører\Dokumenter\Revit-Claude\Udgravningsmodel\projekter
```

## Arbejdsgang

1. **Projekt:** åbn et gemt projekt, eller opret en ny model under
   *Ny model fra volumenrapport (PDF)*.
2. **Tegn kasser:** træk et rektangel i planen, giv kassen navn, top og bund
   (meter under terræn) og evt. rotation, og tryk *Tilføj kasse*.
3. **Justér:** ret mål, placering, rotation og dybder direkte i tabellen.
   Kasser kan også tilføjes og slettes i tabellen.
4. **Slå til og fra:** afkrydsningen *Aktiv* styrer, om kassen trækkes fra.
   Kasser, der er slået fra, vises stiplet og står i rapporten med deres mulige fradrag.
5. **Gem:** *Gem* skriver projektet til `<projektmappe>\<filnavn>.json`; *Download*
   giver en kopi. Filen indeholder model, kasser og indstillinger, så man kan
   arbejde videre senere.
6. **Eksport:** fanen *Eksport* laver IFC og PDF-rapport.

## Indhold af eksporten

**IFC (IFC4)**
- `Udgravning`: netto-modellen (kasserne skåret ud) som lukket
  `IfcTriangulatedFaceSet` på et `IfcBuildingElementProxy`.
  Egenskaber i `VITA_Udgravning` og mængder i `Qto_Udgravning`
  (GrossVolume, NetVolume, GrossArea).
- Valgfrit: `Udgravning uden fradrag` som separat objekt.
- Valgfrit: kasserne som objekter (ekstruderet rektangel) med `VITA_Fradragskasse`
  (aktiv, dybder, fradrag, areal).

**PDF-rapport**
- Opgørelse uden fradrag, fradrag og med fradrag.
- Fradrag pr. kasse, sum, overlap mellem kasser og fradrag i alt.
- Kasser, der er slået fra, med deres mulige fradrag.
- Volumen pr. dybdeinterval uden og med fradrag.
- Plan i målestok med dybdekort, kasser, legende og titelblok.

## Metode og nøjagtighed

- **Rekonstruktion:** rapportens farvekort ligger i PDF'en som vektortrekanter.
  Målestokken bestemmes, så det samlede areal svarer til rapportens areal (for
  Vejle-rapporten 1:445; arealerne pr. interval rammer rapporten inden for 0,04 %).
  Punkter på konturlinjerne har kendt dybde; øvrige punkter bestemmes ved mindste
  kvadraters metode langs TIN-kanterne. Den rekonstruerede model gav 3.774,19 m³
  mod rapportens 3.775,17 m³ (-0,026 %).
- **Kalibrering:** med *Kalibrér til rapportens volumen* skaleres dybderne
  (faktor 1,00026 for Vejle), så volumen uden fradrag svarer præcist til rapporten.
- **Fradrag:** beregnes eksakt. Trekanterne klippes med kassernes sider og med de
  vandrette niveauer, så snitvolumenet integreres uden tilnærmelse. Overlap mellem
  kasser tælles én gang.
- **Kontrol:** netto-modellen er et lukket legeme, og dens volumen (fra
  divergenssætningen) er lig den beregnede netto-volumen. Testene sammenligner
  desuden med en uafhængig numerisk integration.

## Begrænsninger

- Rapporten er en differensmodel (eksisterende terræn minus planum). Modellens top
  er derfor vandret i den valgte terrænkote, og bunden ligger i terrænkote minus dybde.
- Koordinaterne er lokale (meter, x mod øst, y mod nord) med origo nederst til
  venstre for udgravningen. Der er ingen georeference i rapporten.
- Kun afgravning (cut) indgår. Indeholder rapporten fyld, vises en advarsel.
- PDF-importen er lavet til rapporter af typen "Volume Report, Model To Model"
  med farvekort og tabellen "Height Intervals and Areas".
- Kasser er rektangler i plan (kan drejes) mellem to dybder.

## Filer

| Fil | Indhold |
|---|---|
| `app.py` | Streamlit-brugerflade |
| `udgravning/geometri.py` | TIN, kasser, eksakte volumener og netto-mesh |
| `udgravning/pdf_import.py` | Læsning og rekonstruktion af volumenrapporten |
| `udgravning/model.py` | Projektfil (JSON) |
| `udgravning/visning.py` | Plan og 3D (Plotly) |
| `udgravning/ifc_eksport.py` | IFC4-eksport |
| `udgravning/rapport.py` | PDF-rapport (PyMuPDF) |
| `importer_pdf.py` | Opret projekt fra PDF uden brugerflade |
| `tests/test_geometri.py` | Tests (`py -m pytest tests -q`) |

Testen af et rigtigt projekt køres med miljøvariablen `UDGRAVNING_TESTPROJEKT` sat
til en projektfil.
