"""Link Vault Enterprise Command-Line Interface.

Provides CLI access to link ingestion, batch downloading, multimodal video intelligence,
and local dashboard serving.
"""

import argparse
import http.server
import json
import logging
from pathlib import Path
import socketserver
import urllib.parse
import sys
from typing import List

from .analyzer import VideoAnalyzer
from .config import LinkVaultConfig
from .downloader import MediaDownloader
from .ledger import build_ledger
from .parser import LinkParser, ParsedLink


def setup_logging(verbose: bool = False) -> None:
    """Configure structured console logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def handle_ingest(args: argparse.Namespace) -> int:
    """Execute link ingestion from CSV, raw text, or single URL."""
    input_path = Path(args.input)
    parser = LinkParser()
    links: List[ParsedLink] = []

    if input_path.exists():
        if input_path.suffix.lower() == ".csv":
            links = parser.parse_csv(input_path)
        else:
            with open(input_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            links = parser.parse_text(content)
    else:
        # Treat input as direct text or URL
        if input_path.as_posix().startswith("http"):
            single = parser.parse_single_url(str(args.input))
            if single:
                links = [single]
        else:
            links = parser.parse_text(str(args.input))

    print(f"\n==================================================")
    print(f" Link Vault — Ingestion Pipeline Results")
    print(f"==================================================")
    print(f" Total Unique Links Ingested: {len(links)}")

    platform_counts: dict = {}
    for link in links:
        platform_counts[link.platform] = platform_counts.get(link.platform, 0) + 1

    for plat, count in sorted(platform_counts.items()):
        print(f"  • {plat.capitalize():<12}: {count}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump([l.to_dict() for l in links], f, indent=2)
        print(f"\n Saved structured links to: {out_path.resolve()}")
    else:
        print("\n Ingested Links Preview:")
        for l in links[:10]:
            auth_flag = "[AUTH]" if l.auth_required else "[PUB]"
            print(f"  {auth_flag} {l.platform:<10} | {l.media_type:<8} | {l.canonical_url}")
        if len(links) > 10:
            print(f"  ... and {len(links) - 10} more links.")

    return 0


def handle_download(args: argparse.Namespace) -> int:
    """Execute batch downloading across parsed links."""
    links_file = Path(args.links_file)
    if not links_file.exists():
        print(f"Error: links file not found: {links_file}", file=sys.stderr)
        return 1

    with open(links_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    links: List[ParsedLink] = []
    parser = LinkParser()
    for item in data:
        if isinstance(item, dict) and "canonical_url" in item:
            links.append(
                ParsedLink(
                    id=item.get("id", parser.compute_link_id(item["canonical_url"])),
                    raw_url=item.get("raw_url", item["canonical_url"]),
                    canonical_url=item["canonical_url"],
                    platform=item.get("platform", "generic"),
                    media_type=item.get("media_type", "video"),
                    auth_required=item.get("auth_required", False),
                    metadata=item.get("metadata", {}),
                )
            )

    cookies_path = Path(args.cookies) if args.cookies else None
    downloader = MediaDownloader(
        download_dir=Path(args.out_dir) if args.out_dir else None,
        cookies_path=cookies_path,
        max_workers=args.workers,
    )

    print(f"\n==================================================")
    print(f" Link Vault — Batch Media Downloader")
    print(f"==================================================")
    print(f" Total Queue: {len(links)} links | Concurrency: {args.workers} workers")
    if cookies_path:
        print(f" Session Cookies: {cookies_path.resolve()} (Protected)")

    def progress(done: int, total: int, res):
        status = "OK" if res.success else "FAIL"
        print(f" [{done}/{total}] [{status}] {res.platform} -> {res.file_path or res.error}")

    results = downloader.download_batch(links, progress_callback=progress)
    success_count = sum(1 for r in results if r.success)

    print(f"\n Download Complete: {success_count}/{len(results)} successful.")
    return 0 if success_count > 0 else 1


def handle_analyze(args: argparse.Namespace) -> int:
    """Run multimodal video intelligence on downloaded videos."""
    target_path = Path(args.target)
    if not target_path.exists():
        print(f"Error: Target path not found: {target_path}", file=sys.stderr)
        return 1

    analyzer = VideoAnalyzer(
        output_dir=Path(args.out_dir) if args.out_dir else None,
    )

    files_to_analyze: List[Path] = []
    if target_path.is_file():
        files_to_analyze = [target_path]
    else:
        for ext in ["*.mp4", "*.webm", "*.mkv", "*.mov"]:
            files_to_analyze.extend(target_path.glob(ext))

    print(f"\n==================================================")
    print(f" Link Vault — Video Intelligence Engine")
    print(f"==================================================")
    print(f" Found {len(files_to_analyze)} media files to analyze.")

    for idx, f in enumerate(files_to_analyze):
        print(f"\n[{idx + 1}/{len(files_to_analyze)}] Analyzing: {f.name}...")
        try:
            res = analyzer.analyze_video(f)
            print(f"  • Resolution  : {res.resolution} ({res.aspect_ratio})")
            print(f"  • Duration    : {res.duration_seconds:.2f}s | Codec: {res.video_codec}")
            print(f"  • Audio Track : {'Yes (' + str(res.audio_codec) + ')' if res.has_audio else 'None (Silent)'}")
            print(f"  • Keyframes   : {len(res.keyframes)} extracted")
            if res.full_transcript:
                snippet = (res.full_transcript[:80] + "...") if len(res.full_transcript) > 80 else res.full_transcript
                print(f"  • Transcript  : \"{snippet}\"")
        except Exception as e:
            print(f"  x Failed: {e}", file=sys.stderr)

    return 0


def handle_serve(args: argparse.Namespace) -> int:
    """Serve the local Link Vault dashboard and interface."""
    repo_root = Path(__file__).resolve().parent.parent
    dashboard_dir = repo_root / "dashboard"
    port = args.port
    host = args.host

    if not dashboard_dir.exists():
        print(f"Error: Dashboard directory not found at {dashboard_dir}", file=sys.stderr)
        return 1

    links_file = Path(args.links) if args.links else None
    analysis_dir = Path(args.analysis_dir).resolve()
    keyframes_dir = analysis_dir / "keyframes"

    class DashboardHTTPHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *handler_args, **kwargs):
            super().__init__(*handler_args, directory=str(dashboard_dir), **kwargs)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/ledger":
                body = json.dumps(build_ledger(links_file, analysis_dir)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/keyframes/"):
                # Serve only plain file names from the keyframes folder (no traversal).
                name = Path(urllib.parse.unquote(path[len("/keyframes/"):])).name
                target = keyframes_dir / name
                if name and target.is_file():
                    data = target.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_error(404)
                return
            super().do_GET()

    print(f"\n==================================================")
    print(f" Link Vault — Local Dashboard Server")
    print(f"==================================================")
    print(f" Serving UI at: http://{host}:{port}/")
    print(f" Press Ctrl+C to terminate.")

    with socketserver.TCPServer((host, port), DashboardHTTPHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down dashboard server.")
    return 0


def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="linkvault",
        description="Link Vault — Enterprise Omni-Channel Media Ingestion & Video Intelligence Pipeline",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Ingest subcommand
    ingest_parser = subparsers.add_parser("ingest", help="Ingest and sanitize links from CSV, text, or URL")
    ingest_parser.add_argument("input", help="Path to CSV file, text file, or raw URL/string")
    ingest_parser.add_argument("--out", "-o", help="Output path for sanitized JSON links")

    # Download subcommand
    dl_parser = subparsers.add_parser("download", help="Download ingested media links")
    dl_parser.add_argument("links_file", help="JSON file containing parsed links")
    dl_parser.add_argument("--cookies", "-c", help="Path to Netscape format cookies.txt")
    dl_parser.add_argument("--out-dir", "-o", help="Target directory for downloaded files")
    dl_parser.add_argument("--workers", "-w", type=int, default=4, help="Number of worker threads")

    # Analyze subcommand
    ana_parser = subparsers.add_parser("analyze", help="Run multimodal intelligence pipeline on video")
    ana_parser.add_argument("target", help="Path to video file or directory of videos")
    ana_parser.add_argument("--out-dir", "-o", help="Output directory for intelligence JSON and keyframes")

    # Serve subcommand
    serve_parser = subparsers.add_parser("serve", help="Launch local dashboard web server")
    serve_parser.add_argument("--port", "-p", type=int, default=8080, help="Server port (default: 8080)")
    serve_parser.add_argument("--links", help="Ingested links JSON to show (from `ingest --out`)")
    serve_parser.add_argument("--analysis-dir", default="analysis_output", help="Folder written by `analyze` (default: analysis_output)")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "ingest":
        sys.exit(handle_ingest(args))
    elif args.command == "download":
        sys.exit(handle_download(args))
    elif args.command == "analyze":
        sys.exit(handle_analyze(args))
    elif args.command == "serve":
        sys.exit(handle_serve(args))


if __name__ == "__main__":
    main()
