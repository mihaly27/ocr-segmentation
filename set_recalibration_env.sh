#!/usr/bin/env bash

# Ezt a fájlt source-olni kell:
# source ./set_recalibration_env.sh

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "HIBA: ne futtasd közvetlenül; használd így:"
    echo "source ./set_recalibration_env.sh"
    exit 1
fi

export R="${HOME}/ocr-segmentation"
export Q="${R}/mathematical_framework/recalibration_2026"
export P="${Q}/protocol.yaml"
export S="${Q}/scripts"
export C="${Q}/corpora"
export O="${Q}/outputs"

if [[ ! -d "${R}" ]]; then
    echo "HIBA: a repository nem található: ${R}"
    return 1
fi

if [[ ! -f "${P}" ]]; then
    echo "HIBA: a protokoll nem található: ${P}"
    return 1
fi

if [[ ! -f "${R}/ips_single_image/.venv/bin/activate" ]]; then
    echo "HIBA: a Python virtualenv nem található."
    return 1
fi

mkdir -p "${C}" "${O}"

source "${R}/ips_single_image/.venv/bin/activate"

echo "Recalibration környezet beállítva:"
echo "  R=${R}"
echo "  Q=${Q}"
echo "  P=${P}"
echo "  S=${S}"
echo "  C=${C}"
echo "  O=${O}"
echo "  Python: $(command -v python)"
python --version
