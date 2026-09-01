# Node01 snapshot elemzés és továbblépési döntés

Elemzett csomag: `node01_recalibration_snapshot_20260822T125914Z.zip`

## Integritás

- A ZIP szerkezeti ellenőrzése hibátlan.
- A belső `MANIFEST.sha256` mind a 221 felsorolt payload-fájlra egyezik.
- A teljes archívum SHA-256 értéke:
  `465b2090827eae5ccdb38bfb56ecb60e178df852e0c206971d840bbfb5ecb89e`.
- A forrásfa és a dataset-image hashlista bájtszinten azonos a 12:50:46-kor
  készült első snapshottal. A második futás kizárólag a helyes Python-környezet
  rögzítését javította.

## Git és forrásállapot

- HEAD: `5641bb3dce90696072bf54f7afb62aa29e492190`.
- Commit: `main experiment executed, commands and logs tracked`.
- A tracked working tree és az index tiszta; nincs dirty diff.
- A snapshot nem tartalmaz Git remote URL-t, `.env`-et, credentialt vagy
  képtartalmat.
- Erről a commitról biztonságosan indítható külön kutatási branch.

## Futási környezet

- Python executable:
  `/home/mszabo/ocr-segmentation/ips_single_image/.venv/bin/python3`.
- Python: 3.12.3.
- OpenCV: 4.13.0.
- NumPy: 2.4.4.
- PyYAML: 6.0.3.
- Pillow: 12.2.0.
- pytesseract: 0.3.13.
- Tesseract: 5.3.4, `eng` és `osd` language data.

Az előző snapshot egyetlen hiánya ezzel megszűnt: az új kísérletet nem kell
ismeretlen vagy újonnan konstruált környezethez kötni. A ténylegesen használt
virtuális környezet explicit módon befagyasztható.

## Módszertani döntés

Az új branch nem módosítja a történeti Phase-1 és main runner forrását. Egy
külön `recalibration_2026` réteg:

1. új, diszjunkt korpuszon újrabecsüli a három előre fagyasztott aktív
   koordináta súlyait;
2. konfigurációból injektálja az új `W`-t és grid szerinti `delta_W`-t a
   történeti futtatómotorba;
3. minden radiusnál valóban stateful replayt végez;
4. delayed-ground-truth alapon, az elfogadott nem-inferioritási margókkal
   számítja a káros átmeneti eseményt;
5. egzakt egyoldali Clopper–Pearson korláttal választ radiuszt;
6. csak a radius befagyasztása után engedi a confirmation korpusz generálását.

## Fontos kísérlettervezési korrekció

Az eredeti 17 blokkos pályán a nyolc nem-clean blokk közül történetileg csak
három adott egyszerre triggert és nemtriviális raw proposal-t. Nyolc ismétlés
ezért nem tudná teljesíteni a legalább 60 informatív eseményes előírást.

Az új protokoll 60 külön, egyetlen célzott driftblokkot tartalmazó, független
generator-seedű trajektóriát használ:

- 20 touch;
- 20 broken;
- 20 combo.

Ehhez öt külön negatív kontroll tartozik: blur, glare, threshold, compression és
perspective. Egy seed legfeljebb egy informatív binomiális egységet adhat. Így
az egzakt binomiális korlát függetlenségi értelmezése lényegesen tisztább, mint
több egymást követő, közös állapotelőzményű blokk esetén.

## Döntés

**Snapshot státusz: PASS. Branch-nyitás és újrakalibrálás engedhető.**

A következő tényleges Node01-lépés a branch létrehozása, az overlay commitja,
majd a `RUNBOOK.md` szerinti preflight és új W-korpusz generálása.

