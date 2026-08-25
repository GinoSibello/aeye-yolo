#!/usr/bin/env python3
"""Resume un log de tegrastats para los benchmarks reproducibles de AEYE."""

import argparse
import json
import re
import statistics
from pathlib import Path


PATTERNS = {
    "ram": re.compile(
        r"RAM\s+(\d+)/(\d+)MB\s+\(lfb\s+(\d+)x(\d+)(kB|MB)\)"
    ),
    "cpu": re.compile(r"CPU\s+\[([^]]+)\]"),
    "emc": re.compile(r"EMC_FREQ\s+(\d+)%"),
    "gpu": re.compile(r"GR3D_FREQ\s+(\d+)%"),
    "nvdec": re.compile(r"NVDEC\s+(?:(\d+)%|off)"),
    "temperature": re.compile(r"([A-Za-z0-9_]+)@([0-9.]+)C"),
    "power": re.compile(r"VDD_IN\s+(\d+)mW/(\d+)mW(?:/(\d+)mW)?"),
}


def percentile(values, fraction):
    """Calcula un percentil lineal sobre valores ya recolectados."""
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stats(values):
    """Devuelve estadisticas compactas o nulos cuando no hubo muestras."""
    if not values:
        return {"samples": 0, "avg": None, "p95": None, "max": None}
    return {
        "samples": len(values),
        "avg": round(statistics.fmean(values), 3),
        "p95": round(percentile(values, 0.95), 3),
        "max": round(max(values), 3),
    }


def parse_lines(lines):
    """Extrae GPU, CPU, memoria, temperatura, potencia y decodificacion."""
    values = {
        "gpu_percent": [],
        "cpu_percent": [],
        "cpu_peak_core_percent": [],
        "emc_percent": [],
        "ram_used_mb": [],
        "temperature_c": [],
        "power_mw": [],
        "nvdec_percent": [],
    }
    lfb_observations = []
    power_reported_peaks = []
    parsed_lines = 0

    for line in lines:
        found = False

        match = PATTERNS["ram"].search(line)
        if match:
            used, _, blocks, block_value, block_unit = match.groups()
            used = int(used)
            blocks = int(blocks)
            block_mb = int(block_value)
            if block_unit == "kB":
                block_mb /= 1024.0
            values["ram_used_mb"].append(used)
            lfb_observations.append((blocks, block_mb))
            found = True

        match = PATTERNS["gpu"].search(line)
        if match:
            values["gpu_percent"].append(float(match.group(1)))
            found = True

        match = PATTERNS["emc"].search(line)
        if match:
            values["emc_percent"].append(float(match.group(1)))
            found = True

        match = PATTERNS["cpu"].search(line)
        if match:
            cores = [
                float(value)
                for value in re.findall(r"(\d+(?:\.\d+)?)%\@", match.group(1))
            ]
            if cores:
                values["cpu_percent"].append(statistics.fmean(cores))
                values["cpu_peak_core_percent"].append(max(cores))
            found = True

        match = PATTERNS["nvdec"].search(line)
        if match:
            values["nvdec_percent"].append(
                float(match.group(1)) if match.group(1) is not None else 0.0
            )
            found = True

        temperatures = [
            float(value) for _, value in PATTERNS["temperature"].findall(line)
        ]
        if temperatures:
            values["temperature_c"].append(max(temperatures))
            found = True

        match = PATTERNS["power"].search(line)
        if match:
            values["power_mw"].append(float(match.group(1)))
            found = True
            if match.group(3) is not None:
                power_reported_peaks.append(float(match.group(3)))

        if found:
            parsed_lines += 1

    minimum_block = (
        min(lfb_observations, key=lambda row: (row[1], row[0]))
        if lfb_observations else None
    )
    minimum_total = (
        min(lfb_observations, key=lambda row: row[0] * row[1])
        if lfb_observations else None
    )
    return {
        "schema_version": 1,
        "parsed_samples": parsed_lines,
        "gpu_percent": stats(values["gpu_percent"]),
        "cpu_mean_across_active_cores_percent": stats(values["cpu_percent"]),
        "cpu_peak_core_percent": stats(values["cpu_peak_core_percent"]),
        "emc_percent": stats(values["emc_percent"]),
        "ram_used_mb": stats(values["ram_used_mb"]),
        "largest_free_block": {
            "blocks_at_minimum_block_size": (
                minimum_block[0] if minimum_block else None
            ),
            "minimum_block_mb": minimum_block[1] if minimum_block else None,
            "minimum_total_mb": (
                minimum_total[0] * minimum_total[1] if minimum_total else None
            ),
        },
        "maximum_temperature_c": (
            round(max(values["temperature_c"]), 3)
            if values["temperature_c"] else None
        ),
        "power_vdd_in_mw": stats(values["power_mw"]),
        "power_vdd_in_reported_peak_mw": (
            round(max(power_reported_peaks), 3)
            if power_reported_peaks else None
        ),
        "nvdec_percent": stats(values["nvdec_percent"]),
    }


def main():
    """Lee tegrastats y escribe un resumen JSON apto para comparar corridas."""
    parser = argparse.ArgumentParser(description="Resume una captura de tegrastats")
    parser.add_argument("input", type=Path, help="Log crudo producido por tegrastats")
    parser.add_argument("--output", type=Path, help="Archivo JSON; stdout si se omite")
    args = parser.parse_args()

    summary = parse_lines(args.input.read_text(encoding="utf-8").splitlines())
    payload = json.dumps(summary, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
