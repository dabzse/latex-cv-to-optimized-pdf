#!/usr/bin/env python3

"""Compile LaTeX CVs to PDF and optimize them with Ghostscript (gs)."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

DEFAULT_TEX = ("cv_en.tex", "cv_hu.tex")
GS_PRESETS = ("prepress", "printer", "ebook", "screen", "default")
LATEX_ENGINES = ("pdflatex", "lualatex", "xelatex")


def format_size(num_bytes: int) -> str:
    """Return human-readable file size."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    return f"{num_bytes / 1024:.1f} KB ({num_bytes:,} B)"


def require_binary(name: str) -> str:
    """Resolve binary path or exit cleanly with an actionable error."""
    path = shutil.which(name)
    if not path:
        sys.exit(f"Error: '{name}' was not found on PATH.")
    return path


def _build_tex_env(local_fonts: Path) -> dict[str, str]:
    """Build subprocess environment with local font search paths if present."""
    env = os.environ.copy()
    if not local_fonts.is_dir():
        return env
    for var in ("TFMFONTS", "ENCFONTS"):
        existing = env.get(var, "")
        env[var] = f"{local_fonts}:{existing}"
    return env


def _report_latex_failure(
    proc: subprocess.CompletedProcess[str],
    work_dir: Path,
    tex_stem: str,
) -> None:
    """Print LaTeX failure details and exit with the subprocess return code."""
    if proc.stdout:
        sys.stderr.write(proc.stdout[-2500:])
    if proc.stderr:
        sys.stderr.write(proc.stderr[-1000:])
    log_file = work_dir / f"{tex_stem}.log"
    if log_file.exists():
        sys.stderr.write(f"\nDetailed log: {log_file}\n")
    sys.exit(proc.returncode)


def compile_tex(
    tex_path: Path,
    work_dir: Path,
    engine: str,
    passes: int,
) -> Path:
    """Compile a .tex file into work_dir using the requested LaTeX engine."""
    engine_bin = require_binary(engine)
    cmd = [
        engine_bin,
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={work_dir}",
        str(tex_path),
    ]
    env = _build_tex_env(tex_path.parent / "fonts")

    for i in range(1, passes + 1):
        print(f"[{i}/{passes}] LaTeX compile ({engine}): {tex_path.name}")
        proc = subprocess.run(
            cmd,
            check=False,
            cwd=tex_path.parent,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
        )
        if proc.returncode != 0:
            _report_latex_failure(proc, work_dir, tex_path.stem)

    pdf_path = work_dir / f"{tex_path.stem}.pdf"
    if not pdf_path.exists():
        sys.exit(f"Error: compilation did not produce a PDF: {pdf_path}")
    return pdf_path


def optimize_with_gs(
    input_pdf: Path,
    output_pdf: Path,
    preset: str,
    compat_level: str,
    fast_web_view: bool = True,
) -> None:
    """Run Ghostscript pdfwrite; fall back to the unoptimized PDF on failure."""
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    gs_bin = shutil.which("gs")
    if gs_bin is None:
        print(
            "Warning: Ghostscript ('gs') not found on PATH; "
            "keeping the unoptimized PDF.",
            file=sys.stderr,
        )
        _keep_unoptimized(input_pdf, output_pdf)
        return

    with tempfile.NamedTemporaryFile(
        dir=output_pdf.parent,
        prefix=f".{output_pdf.stem}_",
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

    mode_info = "linearized" if fast_web_view else "ObjStm"
    print(f"[gs] PDF optimization (preset=/{preset}, PDF {compat_level}, {mode_info})...")
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        tmp_out.unlink(missing_ok=True)
        sys.stderr.write(proc.stderr or proc.stdout)
        print(
            "Warning: Ghostscript optimization failed; "
            "keeping the unoptimized PDF.",
            file=sys.stderr,
        )
        _keep_unoptimized(input_pdf, output_pdf)
        return

    tmp_out.chmod(0o644)
    shutil.move(str(tmp_out), str(output_pdf))


def _keep_unoptimized(input_pdf: Path, output_pdf: Path) -> None:
    """Copy input_pdf to output_pdf unless they are already the same file."""
    if input_pdf.resolve() != output_pdf.resolve():
        shutil.copy2(input_pdf, output_pdf)


def get_page_count(pdf_path: Path) -> str | None:
    """Return page count via pdfinfo if available."""
    pdfinfo_bin = shutil.which("pdfinfo")
    if not pdfinfo_bin:
        return None
    proc = subprocess.run([pdfinfo_bin, str(pdf_path)], check=False, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("Pages:"):
            return line.split(":", 1)[1].strip()
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile LaTeX CVs to PDF and optimize them with Ghostscript (gs)."
    )
    parser.add_argument(
        "input",
        nargs="*",
        type=Path,
        default=None,
        help=(
            "Input .tex or .pdf file(s); when omitted, every file listed in "
            f"DEFAULT_TEX is processed (default: {', '.join(DEFAULT_TEX)})"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output optimized PDF path (single input only)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the original PDF for an existing .pdf input",
    )
    parser.add_argument(
        "--engine",
        choices=LATEX_ENGINES,
        default="pdflatex",
        help="LaTeX engine for .tex input (default: pdflatex)",
    )
    parser.add_argument(
        "--passes",
        type=int,
        default=2,
        help="Number of LaTeX compilation passes (default: 2)",
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
        help="Disable linearization (-dFastWebView=true); smaller file with ObjStm but Optimized: no",
    )
    parser.add_argument(
        "--keep-raw",
        action="store_true",
        help="Keep the raw PDF when compiling .tex (<name>_raw.pdf)",
    )
    parser.add_argument(
        "--keep-aux",
        action="store_true",
        help="Keep LaTeX auxiliary files in the 'build/' directory",
    )
    return parser.parse_args()


def _resolve_inputs(args: argparse.Namespace) -> list[Path]:
    """Resolve input paths; default to every file in DEFAULT_TEX."""
    if args.input:
        return [p.resolve() for p in args.input]
    base = Path(__file__).resolve().parent
    return [base / name for name in DEFAULT_TEX]


def _resolve_tex_output(input_path: Path, output_arg: Path | None) -> Path:
    """Resolve target PDF output path for a .tex input file."""
    if output_arg is not None:
        return output_arg.resolve()
    return input_path.with_suffix(".pdf")


def _resolve_pdf_output(input_path: Path, args: argparse.Namespace) -> Path:
    """Resolve target PDF output path for an existing .pdf input file."""
    if args.output is not None:
        return args.output.resolve()
    if args.in_place:
        return input_path
    return input_path.with_name(f"{input_path.stem}_optimized.pdf")


def _prepare_tex_work_dir(
    input_path: Path,
    keep_aux: bool,
    stack: ExitStack,
) -> Path:
    """Return persistent 'build/' directory or a managed temporary directory."""
    if keep_aux:
        build_dir = input_path.parent / "build"
        build_dir.mkdir(exist_ok=True)
        return build_dir
    return Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="cv_build_")))


def _process_tex_input(
    input_path: Path,
    output_pdf: Path,
    args: argparse.Namespace,
) -> int:
    """Compile a .tex file, optimize the PDF, and return raw PDF size in bytes."""
    with ExitStack() as stack:
        work_dir = _prepare_tex_work_dir(input_path, args.keep_aux, stack)
        raw_pdf = compile_tex(input_path, work_dir, args.engine, args.passes)
        raw_size = raw_pdf.stat().st_size
        if args.keep_raw:
            shutil.copy2(raw_pdf, input_path.with_name(f"{input_path.stem}_raw.pdf"))
        optimize_with_gs(
            raw_pdf, output_pdf, args.preset, args.compat, not args.no_fast_web_view
        )
    return raw_size


def _format_delta(raw_size: int, opt_size: int) -> str:
    """Format size change percentage between raw and optimized PDFs."""
    if raw_size <= 0:
        return "0.0%"
    saving_pct = (raw_size - opt_size) / raw_size * 100.0
    if saving_pct >= 0:
        return f"{saving_pct:.1f}% reduction"
    return f"{abs(saving_pct):.1f}% increase"


def _process_one_input(input_path: Path, args: argparse.Namespace) -> None:
    """Process a single .tex or .pdf input and print the result summary."""
    suffix = input_path.suffix.lower()
    if suffix == ".tex":
        output_pdf = _resolve_tex_output(input_path, args.output)
        raw_size = _process_tex_input(input_path, output_pdf, args)
    elif suffix == ".pdf":
        output_pdf = _resolve_pdf_output(input_path, args)
        raw_size = input_path.stat().st_size
        optimize_with_gs(
            input_path, output_pdf, args.preset, args.compat, not args.no_fast_web_view
        )
    else:
        sys.exit(f"Error: only .tex or .pdf input files are supported: {input_path}")

    opt_size = output_pdf.stat().st_size
    delta_str = _format_delta(raw_size, opt_size)
    pages = get_page_count(output_pdf)
    page_info = f", pages: {pages}" if pages else ""

    print(f"Done: {output_pdf}")
    print(
        f"Size: {format_size(raw_size)} -> {format_size(opt_size)} "
        f"({delta_str}{page_info})"
    )


def main() -> None:
    args = parse_args()
    if args.passes < 1:
        sys.exit("Error: --passes must be at least 1.")

    inputs = _resolve_inputs(args)
    if not inputs:
        sys.exit("Error: no input files to process.")
    if len(inputs) > 1 and args.output is not None:
        sys.exit("Error: --output can only be used with a single input file.")

    for name in DEFAULT_TEX:
        if not name.lower().endswith(".tex"):
            sys.exit(f"Error: DEFAULT_TEX entries must be .tex files: {name}")

    for input_path in inputs:
        if not input_path.exists():
            sys.exit(f"Error: input file does not exist: {input_path}")
        _process_one_input(input_path, args)


if __name__ == "__main__":
    main()
