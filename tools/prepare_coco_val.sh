#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DATASETS_DIR="${AEYE_DATASETS_DIR:-$PROJECT_DIR/datasets}"
COCO_DIR="$DATASETS_DIR/coco"
LABELS_URL="https://github.com/ultralytics/assets/releases/download/v0.0.0/coco2017labels.zip"
IMAGES_URL="http://images.cocodataset.org/zips/val2017.zip"
IMAGES_MD5="442b8da7639aecaf257c1dceb8ba8c80"
EXPECTED_IMAGES=5000
EXPECTED_LABEL_FILES=4952
TEMP_DIR="$(mktemp -d /tmp/aeye-coco-val.XXXXXX)"

cleanup() {
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT INT TERM

image_count="0"
if [[ -d "$COCO_DIR/images/val2017" ]]; then
  image_count="$(find "$COCO_DIR/images/val2017" -maxdepth 1 -type f | wc -l)"
fi
if [[ "$image_count" == "5000" && -f "$COCO_DIR/val2017.txt" ]]; then
  printf 'COCO val ya esta preparado: %s\n' "$COCO_DIR"
  exit 0
fi

mkdir -p "$DATASETS_DIR" "$COCO_DIR/images"
if [[ ! -f "$COCO_DIR/val2017.txt" || ! -d "$COCO_DIR/labels/val2017" ]]; then
  printf 'Descargando etiquetas oficiales COCO...\n'
  curl --fail --location --retry 5 --retry-all-errors \
    "$LABELS_URL" --output "$TEMP_DIR/coco2017labels.zip"
  unzip -q -o "$TEMP_DIR/coco2017labels.zip" -d "$DATASETS_DIR"
else
  printf 'Etiquetas COCO existentes, se conservan.\n'
fi

printf 'Descargando 5000 imagenes COCO val2017...\n'
curl --fail --location --retry 5 --retry-all-errors \
  "$IMAGES_URL" --output "$TEMP_DIR/val2017.zip"
unzip -q -o "$TEMP_DIR/val2017.zip" -d "$COCO_DIR/images"

image_count="$(find "$COCO_DIR/images/val2017" -maxdepth 1 -type f | wc -l)"
if [[ "$image_count" != "5000" ]]; then
  printf 'Se esperaban 5000 imagenes y se encontraron %s.\n' "$image_count" >&2
  exit 2
fi
if [[ ! -f "$COCO_DIR/val2017.txt" || ! -d "$COCO_DIR/labels/val2017" ]]; then
  printf 'Las etiquetas COCO no quedaron en la estructura esperada.\n' >&2
  exit 2
fi
printf 'COCO val preparado: %s (imagenes=%s)\n' "$COCO_DIR" "$image_count"
