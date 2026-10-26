"""Opret en projektfil fra en volumenrapport (PDF) uden brugerflade.

Brug:  py importer_pdf.py <rapport.pdf> <projektnavn> [<udfil.json>]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from udgravning.model import Projekt, filnavn  # noqa: E402
from udgravning.pdf_import import importer_pdf  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    pdf, navn = sys.argv[1], sys.argv[2]
    ud = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "projekter", filnavn(navn))
    t0 = time.time()
    with open(pdf, "rb") as f:
        imp = importer_pdf(f.read(), status=print)
    p = Projekt.fra_import(navn, imp, kildefil=os.path.basename(pdf))
    k = p.kilde
    print("Målestok 1:%d, maks. arealafvigelse pr. interval %.3f %%" % (k["maalestok"], k["maks_arealafvigelse_pct"]))
    print("Rekonstrueret volumen %.2f m3, rapport %.2f m3 (%.3f %%)" % (
        p.raa_volumen, k["reference_volumen"], (p.raa_volumen / k["reference_volumen"] - 1) * 100))
    os.makedirs(os.path.dirname(os.path.abspath(ud)), exist_ok=True)
    with open(ud, "w", encoding="utf-8") as f:
        f.write(p.til_json())
    print("Gemt: %s (%.1f s)" % (ud, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
