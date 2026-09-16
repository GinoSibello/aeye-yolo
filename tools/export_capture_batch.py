#!/usr/bin/env python3
"""Exporta lotes incrementales del dataset AEYE con manifiesto y checksums."""

import argparse
import hashlib
import json
import os
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path


def _read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"JSONL invalido en {path}, linea {line_number}"
                ) from error
    return rows


def _safe_source(root, relative):
    candidate = (root / str(relative)).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Ruta fuera del dataset: {relative}")
    if not candidate.is_file():
        raise FileNotFoundError(f"Falta archivo indexado: {relative}")
    return candidate


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_exported(state_path):
    if not state_path.exists():
        return set()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return {str(value) for value in payload.get("exported_capture_ids", [])}


def _write_state(state_path, exported):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(
        f".{state_path.name}.{uuid.uuid4().hex}.tmp"
    )
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now().astimezone().isoformat(),
        "exported_capture_ids": sorted(exported),
    }
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state_path)
    finally:
        temporary.unlink(missing_ok=True)


def build_incremental_archive(root, output=None, state_path=None):
    """Crea un ZIP con capturas aun no exportadas y avanza estado al finalizar."""
    root = Path(root).resolve()
    index_path = root / "capture_index.jsonl"
    rows = _read_jsonl(index_path)
    state_path = (
        Path(state_path).resolve()
        if state_path is not None
        else root / "export_state.json"
    )
    exported = _load_exported(state_path)
    selected = [
        row for row in rows
        if str(row.get("capture_id", "")) not in exported
    ]
    if not selected:
        return None

    if output is None:
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        output = root / "exports" / f"aeye_capture_{stamp}.zip"
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"El ZIP ya existe: {output}")

    manifest_lines = []
    checksum_lines = []
    files = []
    for row in selected:
        capture_id = str(row["capture_id"])
        if not capture_id:
            raise ValueError("capture_id vacio en indice")
        image_relative = str(row["image"])
        metadata_relative = str(row["metadata"])
        image_path = _safe_source(root, image_relative)
        metadata_path = _safe_source(root, metadata_relative)
        expected_image_hash = str(row["sha256"])
        actual_image_hash = _file_sha256(image_path)
        if actual_image_hash != expected_image_hash:
            raise ValueError(f"Checksum de imagen invalido: {image_relative}")
        metadata_hash = _file_sha256(metadata_path)
        files.extend([
            (image_path, image_relative),
            (metadata_path, metadata_relative),
        ])
        checksum_lines.extend([
            f"{actual_image_hash}  {image_relative}",
            f"{metadata_hash}  {metadata_relative}",
        ])
        manifest_lines.append(json.dumps(row, ensure_ascii=False))

    manifest = ("\n".join(manifest_lines) + "\n").encode("utf-8")
    checksum_lines.append(
        f"{hashlib.sha256(manifest).hexdigest()}  manifest.jsonl"
    )
    checksums = ("\n".join(checksum_lines) + "\n").encode("utf-8")

    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    sidecar = output.with_suffix(output.suffix + ".sha256")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for source, relative in files:
                archive.write(source, relative)
            archive.writestr("manifest.jsonl", manifest)
            archive.writestr("SHA256SUMS", checksums)
        os.replace(temporary, output)
        archive_hash = _file_sha256(output)
        sidecar.write_text(
            f"{archive_hash}  {output.name}\n",
            encoding="utf-8",
        )
        _write_state(
            state_path,
            exported | {str(row["capture_id"]) for row in selected},
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        sidecar.unlink(missing_ok=True)
        raise

    return {
        "archive": output,
        "checksum": sidecar,
        "captures": len(selected),
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Genera un ZIP incremental de datasets/aeye_capture."
    )
    parser.add_argument(
        "--root",
        default="datasets/aeye_capture",
        help="Raiz del dataset (default: datasets/aeye_capture)",
    )
    parser.add_argument(
        "--output",
        help="Ruta del ZIP; por defecto se crea bajo ROOT/exports.",
    )
    parser.add_argument(
        "--state",
        help="Estado incremental; por defecto ROOT/export_state.json.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        result = build_incremental_archive(
            args.root,
            output=args.output,
            state_path=args.state,
        )
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if result is None:
        print("No hay imagenes nuevas para exportar.")
        return 0
    print(
        f"ZIP={result['archive']} capturas={result['captures']} "
        f"checksum={result['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
