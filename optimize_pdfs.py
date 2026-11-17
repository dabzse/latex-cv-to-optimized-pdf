#!/usr/bin/env python3

"""Standalone batch PDF optimizer using Ghostscript (gs)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GS_PRESETS = ("prepress", "printer", "ebook", "screen", "default")


def format_size(num_bytes: int) -> str:
    """Return human-readable file size."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    return f"{num_bytes / 1024:.1f} KB ({num_bytes:,} B)"


def format_delta(orig_size: int, opt_size: int) -> str:
    """Format size change percentage between original and optimized PDFs."""
    if orig_size <= 0:
        return "0.0%"
    saving_pct = (orig_size - opt_size) / orig_size * 100.0
    if saving_pct >= 0:
        return f"{saving_pct:.1f}% reduction"
    return f"{abs(saving_pct):.1f}% increase"


def require_binary(name: str) -> str:
    """Resolve binary path or exit cleanly with an actionable error."""
    path = shutil.which(name)
    if not path:
        sys.exit(f"Error: '{name}' was not found on PATH.")
    return path


def resolve_target_path(args: argparse.Namespace) -> Path:
    """Resolve input file or directory; default to the script's own directory."""
    if args.target is not None and args.path is not None:
        sys.exit("Error: do not pass the path both as a positional argument and via --path.")
    chosen = args.path if args.path is not None else args.target
    if chosen is None:
        return Path(__file__).resolve().parent
    return chosen.resolve()


def _is_candidate_pdf(path: Path, out_dir: Path | None) -> bool:
    """Return True if path is a source PDF (not already suffixed or inside out_dir)."""
    if not path.is_file() or path.suffix.lower() != ".pdf":
        return False
    if path.stem.lower().endswith("_optimized"):
        return False
    return not (out_dir is not None and out_dir in path.resolve().parents)


def collect_pdfs(target: Path, recursive: bool, out_dir: Path | None) -> list[Path]:
    """Collect candidate PDF files from a file or directory target."""
    if not target.exists():
        sys.exit(f"Error: path does not exist: {target}")
    if target.is_file():
        if target.suffix.lower() != ".pdf":
            sys.exit(f"Error: not a PDF file: {target}")
        return [target]
    if not target.is_dir():
        sys.exit(f"Error: invalid path: {target}")

    entries = target.rglob("*") if recursive else target.iterdir()
    return sorted(p for p in entries if _is_candidate_pdf(p, out_dir))


def resolve_output_pdf(src: Path, target_root: Path, args: argparse.Namespace) -> Path:
    """Determine destination path for a single source PDF."""
    if args.in_place:
        return src
    if args.output_dir is not None:
        out_dir = args.output_dir.resolve()
        rel = src.relative_to(target_root) if target_root.is_dir() else Path(src.name)
        return out_dir / rel
    return src.with_name(f"{src.stem}_optimized.pdf")


def run_ghostscript(
    input_pdf: Path,
    temp_dir: Path,
    preset: str,
    compat_level: str,
    fast_web_view: bool,
) -> tuple[Path | None, str]:
    """Run Ghostscript pdfwrite into a temporary file inside temp_dir."""
    gs_bin = require_binary("gs")
    with tempfile.NamedTemporaryFile(
        dir=temp_dir,
        prefix=f".{input_pdf.stem}_",
        suffix=".pdf",
        delete=False,
    ) as tmp_file:
        tmp_out = Path(tmp_file.name)

    cmd = [
        gs_bin,
        "-sDEVICE=pdfwrite",
        f"-dCompatibilityLevel={compat_level}",
        f"-dPDFSETTINGS=/{preset}",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
        "-dAutoRotatePages=/None",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dEmbedAllFonts=true",
        "-dCompressPages=true",
    ]
    if fast_web_view:
        cmd.append("-dFastWebView=true")
    cmd.extend([f"-sOutputFile={tmp_out}", str(input_pdf)])

    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        tmp_out.unlink(missing_ok=True)
        err_msg = (proc.stderr or proc.stdout or f"exit code: {proc.returncode}").strip()
        return None, err_msg
    return tmp_out, ""


def process_one_pdf(
    src: Path,
    dst: Path,
    args: argparse.Namespace,
) -> tuple[bool, int, int]:
    """Optimize one PDF file; return (ok, orig_bytes, final_bytes)."""
    orig_size = src.stat().st_size
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_out, err = run_ghostscript(
        src, dst.parent, args.preset, args.compat, not args.no_fast_web_view
    )
    if tmp_out is None:
        print(f"[ERROR] {src.name}: {err}", file=sys.stderr)
        return False, orig_size, orig_size

    opt_size = tmp_out.stat().st_size
    if args.only_smaller and opt_size >= orig_size:
        tmp_out.unlink(missing_ok=True)
        print(
            f"[SKIPPED] {src.name}: not smaller "
            f"({format_size(orig_size)} -> {format_size(opt_size)})"
        )
        return True, orig_size, orig_size

    tmp_out.chmod(0o644)
    shutil.move(str(tmp_out), str(dst))
    delta = format_delta(orig_size, opt_size)
    print(
        f"[OK] {src.name} -> {dst.name}: "
        f"{format_size(orig_size)} -> {format_size(opt_size)} ({delta})"
    )
    return True, orig_size, opt_size


def _run_batch(
    pdfs: list[Path],
    target: Path,
    args: argparse.Namespace,
) -> tuple[int, int, int]:
    """Optimize all collected PDFs and return (total_orig, total_final, failures)."""
    total_orig = 0
    total_final = 0
    failures = 0
    for src in pdfs:
        dst = resolve_output_pdf(src, target, args)
        ok, orig_size, final_size = process_one_pdf(src, dst, args)
        total_orig += orig_size
        total_final += final_size
        if not ok:
            failures += 1
    return total_orig, total_final, failures


def _print_dry_run(pdfs: list[Path], target: Path, args: argparse.Namespace) -> None:
    """Print planned input -> output mappings without running Ghostscript."""
    print(f"Dry run ({len(pdfs)} PDF(s)):")
    for src in pdfs:
        dst = resolve_output_pdf(src, target, args)
        print(f"  {src} -> {dst}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Standalone batch PDF optimizer using Ghostscript (gs). "
            "Without a path, it optimizes the PDFs in the script's own directory."
        )
    )
    parser.add_argument(
        "target",
        nargs="?",
        type=Path,
        default=None,
        help="Path to a directory or a single PDF file (optional)",
    )
    parser.add_argument(
        "-p",
        "--path",
        type=Path,
        default=None,
        help="Path to a directory or a single PDF file via flag",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Separate output directory (keeps original file names)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the original PDF files",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Also process PDFs in subdirectories",
    )
    parser.add_argument(
        "--only-smaller",
        action="store_true",
        help="Only keep the new file if it is smaller than the original",
    )
    parser.add_argument(
        "--preset",
        choices=GS_PRESETS,
        default="prepress",
        help="Ghostscript -dPDFSETTINGS profile (default: prepress)",
    )
    parser.add_argument(
        "--compat",
        default="1.5",
        help="PDF compatibility level (default: 1.5)",
    )
    parser.add_argument(
        "--no-fast-web-view",
        action="store_true",
        help="Disable linearization (-dFastWebView=true)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list the PDFs to be processed without making changes",
    )
    args = parser.parse_args()
    if args.in_place and args.output_dir is not None:
        parser.error("--in-place and --output-dir cannot be used together.")
    return args


def main() -> None:
    args = parse_args()
    target = resolve_target_path(args)
    out_dir = args.output_dir.resolve() if args.output_dir else None
    pdfs = collect_pdfs(target, args.recursive, out_dir)
    if not pdfs:
        print(f"No optimizable PDFs found at: {target}")
        return

    if args.dry_run:
        _print_dry_run(pdfs, target, args)
        return

    if shutil.which("gs") is None:
        print(
            "Warning: Ghostscript ('gs') was not found on PATH; "
            "no PDFs were optimized.",
            file=sys.stderr,
        )
        return

    total_orig, total_final, failures = _run_batch(pdfs, target, args)
    delta = format_delta(total_orig, total_final)
    print(
        f"\nTotal ({len(pdfs) - failures}/{len(pdfs)} succeeded): "
        f"{format_size(total_orig)} -> {format_size(total_final)} ({delta})"
    )
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
