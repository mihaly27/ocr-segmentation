# A delta-kalibráció V2 formális indoklása

A V1 futás technikailag és integritásában sikeres volt, de a preregisztrált
kiválasztási szabály szerint inkonkluzív eredményt adott. A 60 céltrajektóriából
45 vált informatívvá: touch 20/20, combo 20/20, broken 5/20. Nulla megfigyelt
harm mellett 45 binomiális egység egyoldali egzakt 95%-os felső korlátja
0,064404, ezért az előírt 0,05 nem volt elérhető.

A V1 emellett 45 elemű blokkokat osztott egyenlően 15 proposal, 15 gate és 15
evaluation mintára. Így a full-plate accuracy legkisebb nemzérus blokkváltozása
1/15 = 6,67 százalékpont volt, miközben az előre elfogadott gyakorlati margin 5
százalékpont. A V1 egyetlen harm eseménye pontosan egyetlen elvesztett plate
volt a combo 86082353 seednél, delta 3,0 és 8,0 között. Ez valós pilot
megfigyelés, de a felbontás nem alkalmas a margin konszolidált megítélésére.

V2 ezért nem a V1 adaptív folytatása és nem poololja a V1 eseményeit. A W
független Phase-1 újrabecslése megmarad, de hash-sel zárolt külső bemenet. A
delta-grid, a 95%-os egzakt szabály, az 5%-os harm korlát, a 20%-os coverage és
valamennyi nem-inferioritási margin változatlan.

V2 rögzített mintaterve 120 új, diszjunkt trajektória: 40 touch, 40 broken és 40
combo. Minden blokk 15 proposal, 15 gate és 60 evaluation mintából áll. A
feltételenkénti informatív arányt külön jelentjük; a negatív kontrollok nem
növelhetik a delta-kiválasztás binomiális információszámát. Confirmation adat
csak pozitív V2 delta befagyasztása után generálható.
