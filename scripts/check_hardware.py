"""Hardware audit and local-Glimmer feasibility assessment (Phase 1).

Collects local RAM/GPU/disk/runtime facts without assuming a GPU exists.
Makes no network requests, installs nothing, downloads nothing.

Glimmer planning estimates (project dossier, unverified against official
artifacts): ~16.8 GB quantized 30B weights + ~1.4 GB vision projector,
~24 GiB VRAM working threshold. These are estimates, not requirements.

Decision states:
  LOCAL_GLIMMER_FEASIBLE            hardware + runtime can attempt a load
  LOCAL_GLIMMER_REQUIRES_EXPERIMENT inconclusive; needs a load/latency test
  LOCAL_GLIMMER_UNAVAILABLE         no viable local path on this machine

Exit codes: 0 unless the audit itself fails to run.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (  # noqa: E402
    atomic_write_json, default_audit_root,
    find_project_root as _common_find_root, provenance_envelope,
)

COMMAND_TIMEOUT_S = 15

# Dossier planning estimates (GiB, approximate, unverified).
DOSSIER_WEIGHTS_GIB = 16.8
DOSSIER_PROJECTOR_GIB = 1.4
DOSSIER_VRAM_THRESHOLD_GIB = 24.0
# Minimum free disk to even consider staging weights (weights + margin).
MIN_FREE_DISK_GIB = 30.0

WEIGHT_SUFFIXES = (".gguf", ".safetensors", ".bin", ".pt", ".pth", ".onnx")
RUNTIME_MODULES = ("torch", "transformers", "llama_cpp", "ctransformers",
                   "onnxruntime", "accelerate")


def run_command(argv: list[str], timeout: int = COMMAND_TIMEOUT_S) -> tuple[bool, str]:
    try:
        completed = subprocess.run(argv, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        # Windows console shims (.cmd/.bat) need shell execution.
        if os.name == "nt" and argv:
            resolved = shutil.which(argv[0])
            if resolved and resolved.lower().endswith((".cmd", ".bat")):
                try:
                    completed = subprocess.run(
                        subprocess.list2cmdline(argv), capture_output=True,
                        text=True, encoding="utf-8", errors="replace",
                        timeout=timeout, shell=True)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    return False, f"shell fallback failed: {exc}"
                output = (completed.stdout + completed.stderr).strip()
                if completed.returncode != 0:
                    return False, output or f"exit code {completed.returncode}"
                return True, output
        return False, "executable not found"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except OSError as exc:
        return False, f"OS error: {exc}"
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        return False, output or f"exit code {completed.returncode}"
    return True, output


def find_project_root() -> Optional[Path]:
    return _common_find_root()


def get_system_ram_gib() -> dict:
    """Best-effort total physical RAM. Never crashes; reports unknown."""
    # Windows: GlobalMemoryStatusEx via ctypes.
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return {"total_gib": round(status.ullTotalPhys / (1024 ** 3), 2),
                        "available_gib": round(status.ullAvailPhys / (1024 ** 3), 2),
                        "source": "GlobalMemoryStatusEx"}
        except Exception as exc:  # noqa: BLE001 - fall through to unknown
            return {"total_gib": None, "available_gib": None,
                    "source": f"GlobalMemoryStatusEx failed: {exc}"}
        return {"total_gib": None, "available_gib": None,
                "source": "GlobalMemoryStatusEx returned failure"}
    # POSIX: sysconf.
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return {"total_gib": round(pages * page_size / (1024 ** 3), 2),
                "available_gib": None, "source": "sysconf"}
    except (ValueError, OSError) as exc:
        return {"total_gib": None, "available_gib": None, "source": f"sysconf failed: {exc}"}


def get_nvidia_info() -> dict:
    """Query nvidia-smi. Missing tool is NOT proof of no GPU."""
    ok, output = run_command(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                              "--format=csv,noheader,nounits"])
    if not ok:
        return {"available": False, "detail": output[:300], "gpus": []}
    gpus = []
    for line in output.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                gpus.append({"name": parts[0], "vram_total_mib": float(parts[1]),
                             "vram_free_mib": float(parts[2])})
            except ValueError:
                gpus.append({"name": parts[0], "vram_total_mib": None, "vram_free_mib": None})
    return {"available": True, "detail": f"{len(gpus)} GPU(s) via nvidia-smi", "gpus": gpus}


def get_video_controllers() -> dict:
    """OS-reported graphics devices. AdapterRAM of 0/missing means UNKNOWN, not 0."""
    system = platform.system()
    if system == "Windows":
        ps = ("Get-CimInstance Win32_VideoController | "
              "Select-Object Name, AdapterRAM | ConvertTo-Json")
        ok, output = run_command(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            timeout=COMMAND_TIMEOUT_S)
        if not ok:
            return {"available": False, "detail": output[:300], "devices": []}
        try:
            data = json.loads(output) if output else []
        except json.JSONDecodeError:
            return {"available": False, "detail": "CIM query output was not JSON", "devices": []}
        if isinstance(data, dict):
            data = [data]
        devices = []
        for entry in data:
            ram = entry.get("AdapterRAM")
            # AdapterRAM is uint32 and wraps above 4 GiB; 0/missing/"4294967296"
            # style values are unreliable — record as unknown.
            vram_gib = None
            if isinstance(ram, (int, float)) and 0 < ram < 2 ** 32:
                vram_gib = round(ram / (1024 ** 3), 2)
            devices.append({"name": entry.get("Name") or "unknown",
                            "adapter_ram_raw": ram, "vram_gib_estimate": vram_gib,
                            "vram_note": "AdapterRAM is unreliable above 4 GiB; treat as unknown"})
        return {"available": True, "detail": f"{len(devices)} device(s) via CIM",
                "devices": devices}
    if system == "Linux":
        ok, output = run_command(["lspci"])
        if not ok:
            return {"available": False, "detail": output[:300], "devices": []}
        devices = [{"name": line.strip()[:160]} for line in output.splitlines()
                   if "vga" in line.lower() or "3d" in line.lower() or "nvidia" in line.lower()]
        return {"available": True, "detail": f"{len(devices)} device(s) via lspci",
                "devices": devices}
    if system == "Darwin":
        ok, output = run_command(["system_profiler", "SPDisplaysDataType"])
        if not ok:
            return {"available": False, "detail": output[:300], "devices": []}
        names = [line.strip()[:160] for line in output.splitlines()
                 if "Chipset Model" in line]
        return {"available": True, "detail": "macOS display profiler",
                "devices": [{"name": n} for n in names]}
    return {"available": False, "detail": f"unsupported platform: {system}", "devices": []}


def get_disk_info(root: Optional[Path]) -> dict:
    target = str(root) if root else os.getcwd()
    try:
        usage = shutil.disk_usage(target)
    except OSError as exc:
        return {"target": target, "error": str(exc)}
    return {"target": target,
            "total_gib": round(usage.total / (1024 ** 3), 2),
            "free_gib": round(usage.free / (1024 ** 3), 2)}


def get_runtime_info() -> dict:
    runtimes: dict[str, dict] = {}
    for module in RUNTIME_MODULES:
        spec = importlib.util.find_spec(module)
        if spec is None:
            runtimes[module] = {"installed": False}
            continue
        try:
            mod = importlib.import_module(module)
            version = str(getattr(mod, "__version__", "unknown"))
        except Exception as exc:  # noqa: BLE001 - record, don't crash
            runtimes[module] = {"installed": True, "version": None, "import_error": str(exc)[:200]}
            continue
        info: dict = {"installed": True, "version": version}
        if module == "torch":
            try:
                info["cuda_available"] = bool(mod.cuda.is_available())
                if info["cuda_available"]:
                    info["cuda_device_count"] = int(mod.cuda.device_count())
                    info["cuda_device_name"] = str(mod.cuda.get_device_name(0))
            except Exception as exc:  # noqa: BLE001
                info["cuda_probe_error"] = str(exc)[:200]
        runtimes[module] = info
    return runtimes


def find_weight_files(root: Optional[Path]) -> list[dict]:
    if root is None:
        return []
    skip_dirs = {".git", ".hg", ".sl", ".eden", ".agents", ".muse", ".venv",
                 "venv", "__pycache__", "node_modules"}
    hits: list[dict] = []
    for path in root.rglob("*"):
        if len(hits) >= 20 or path.is_dir():
            continue
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in skip_dirs for part in parts):
            continue
        if any(part.startswith("pytest-of-") for part in parts):
            continue
        if path.suffix.lower() in WEIGHT_SUFFIXES or "glimmer" in path.name.lower():
            try:
                size = path.stat().st_size
                rel = str(path.relative_to(root))
            except (OSError, ValueError):
                continue
            hits.append({"path": rel, "size_bytes": size})
    return hits


def decide_feasibility(nvidia: dict, controllers: dict, disk: dict,
                       runtimes: dict, weights: list[dict]) -> tuple[str, str]:
    """Multi-factor decision. Never a single numeric threshold."""
    known_vram_gib: Optional[float] = None
    gpu_names: list[str] = []
    for gpu in nvidia.get("gpus", []):
        gpu_names.append(gpu.get("name", "unknown"))
        total_mib = gpu.get("vram_total_mib")
        if isinstance(total_mib, (int, float)):
            gib = total_mib / 1024
            known_vram_gib = gib if known_vram_gib is None else max(known_vram_gib, gib)

    has_nvidia = nvidia.get("available", False) and bool(nvidia.get("gpus"))
    has_any_gpu_mention = has_nvidia or any(
        (d.get("name") or "").lower() not in ("", "unknown")
        for d in controllers.get("devices", []))
    cuda_ok = bool((runtimes.get("torch") or {}).get("cuda_available"))
    any_runtime = any((runtimes.get(m) or {}).get("installed") for m in RUNTIME_MODULES)
    free_gib = disk.get("free_gib")
    disk_ok = isinstance(free_gib, (int, float)) and free_gib >= MIN_FREE_DISK_GIB

    # Case 1: clearly capable — known-sufficient VRAM plus a load path.
    if (known_vram_gib is not None and known_vram_gib >= DOSSIER_VRAM_THRESHOLD_GIB
            and (cuda_ok or any_runtime) and disk_ok):
        return ("LOCAL_GLIMMER_FEASIBLE",
                f"GPU with {known_vram_gib:.1f} GiB known VRAM, inference runtime present, "
                f"{free_gib:.1f} GiB free disk: a supervised load/latency experiment is justified. "
                "Feasibility is confirmed only by that experiment, not by this audit.")

    # Case 3: no viable path — no GPU evidence at all, or known-insufficient VRAM.
    if known_vram_gib is not None and known_vram_gib < DOSSIER_VRAM_THRESHOLD_GIB and has_nvidia:
        return ("LOCAL_GLIMMER_UNAVAILABLE",
                f"Known VRAM is {known_vram_gib:.1f} GiB, below the ~24 GiB planning threshold, "
                "with no evidence of additional devices. Use the hosted-reader fallback or a "
                "mock reader; revisit only with verified smaller artifacts or new hardware.")
    if not has_any_gpu_mention and not cuda_ok:
        detail = ("No GPU detected by any available probe (nvidia-smi unavailable, no CUDA, "
                  "no named graphics device). ")
        if not nvidia.get("available"):
            detail += ("Note: nvidia-smi absence alone does not prove no GPU exists, but no "
                       "other probe found one either. ")
        detail += "Local Glimmer is UNAVAILABLE on this machine as observed."
        return ("LOCAL_GLIMMER_UNAVAILABLE", detail)

    # Case 2: inconclusive — some GPU signal but insufficient evidence.
    reasons = []
    if gpu_names:
        reasons.append("GPU(s): " + ", ".join(gpu_names))
    else:
        names = [d.get("name", "unknown") for d in controllers.get("devices", [])]
        reasons.append("graphics device(s): " + (", ".join(names) if names else "unresolved"))
    if known_vram_gib is None:
        reasons.append("VRAM unknown (OS values unreliable or unreported)")
    if not any_runtime:
        reasons.append("no inference runtime installed")
    elif not cuda_ok:
        reasons.append("runtime present but CUDA not confirmed")
    if not disk_ok:
        reasons.append(f"free disk {free_gib} GiB below {MIN_FREE_DISK_GIB} GiB staging margin")
    if not weights:
        reasons.append("no weight files staged locally")
    return ("LOCAL_GLIMMER_REQUIRES_EXPERIMENT",
            "Inconclusive hardware picture — " + "; ".join(reasons) + ". "
            "Resolve VRAM via vendor tools, install a runtime, verify the official artifact "
            "names/licence, then run a supervised load/latency experiment before any go decision.")


def run_hardware_audit() -> dict:
    root = default_audit_root()
    ram = get_system_ram_gib()
    nvidia = get_nvidia_info()
    controllers = get_video_controllers()
    disk = get_disk_info(root)
    runtimes = get_runtime_info()
    weights = find_weight_files(root)
    decision, rationale = decide_feasibility(nvidia, controllers, disk, runtimes, weights)
    return {
        "platform": {"system": platform.system(), "release": platform.release(),
                     "version": platform.version(), "machine": platform.machine()},
        "system_ram": ram,
        "nvidia_smi": nvidia,
        "video_controllers": controllers,
        "disk": disk,
        "runtimes": runtimes,
        "weight_files": weights,
        "dossier_estimates_gib": {
            "weights": DOSSIER_WEIGHTS_GIB,
            "vision_projector": DOSSIER_PROJECTOR_GIB,
            "vram_working_threshold_gib": DOSSIER_VRAM_THRESHOLD_GIB,
            "verified_against_official_artifacts": False,
        },
        "decision": decision,
        "rationale": rationale,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit hardware and assess local-Glimmer feasibility.")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Write the structured report as JSON to this path.")
    args = parser.parse_args(argv)

    try:
        report = run_hardware_audit()
    except Exception as exc:  # noqa: BLE001 - audit must not crash the shell
        print(f"ERROR: hardware audit failed: {exc}", file=sys.stderr)
        return 1

    print("Airlock hardware audit")
    print(f"  platform: {report['platform']['system']} {report['platform']['release']} "
          f"({report['platform']['machine']})")
    ram = report["system_ram"]
    print(f"  system RAM: {ram.get('total_gib')} GiB total "
          f"(source: {ram.get('source')})")
    print(f"  nvidia-smi: {report['nvidia_smi']['detail']}")
    for gpu in report["nvidia_smi"].get("gpus", []):
        print(f"    - {gpu.get('name')}: {gpu.get('vram_total_mib')} MiB total")
    print(f"  graphics devices: {report['video_controllers']['detail']}")
    for dev in report["video_controllers"].get("devices", [])[:4]:
        print(f"    - {dev.get('name')} (VRAM: {dev.get('vram_gib_estimate')})")
    print(f"  disk: {report['disk'].get('free_gib')} GiB free of "
          f"{report['disk'].get('total_gib')} GiB ({report['disk'].get('target')})")
    installed = [m for m, r in report["runtimes"].items() if r.get("installed")]
    print(f"  inference runtimes installed: {', '.join(installed) if installed else 'none'}")
    print(f"  weight files in project: {len(report['weight_files'])}")
    print(f"  decision: {report['decision']}")
    print(f"  rationale: {report['rationale']}")

    if args.json_path:
        report["provenance"] = provenance_envelope(
            "check_hardware", argv=argv, root=find_project_root(),
            extra={"exit_code": 0})
        try:
            atomic_write_json(args.json_path, report)
            print(f"  JSON report written to {args.json_path}")
        except OSError as exc:
            print(f"ERROR: cannot write JSON report: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
