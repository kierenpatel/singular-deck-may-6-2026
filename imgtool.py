#!/usr/bin/env python3
"""imgtool — find, grab, and place images into singular-deck-may26/index.html.

Subcommands:
  list                              show every <img> in index.html
  find QUERY [-n N] [--safe S]      DDG image search; prints index, URL, dims, host
  grab URL [--name SLUG]            download to img/<slug>.<ext>, prints local path
  put SRC SELECTOR                  swap an <img>'s src= ; SELECTOR is line# or alt-substring or #N
  show SELECTOR                     print the full <img> tag for SELECTOR
  quick SELECTOR QUERY [-n N]       find -> grab top result -> put (no bullshit mode)
  undo                              restore index.html from latest .bak

SELECTOR forms:
  - integer (e.g. 4295)           : line number of the <img>
  - "#N"   (e.g. #3)               : 0-based index into the list of <img>s
  - any other string               : case-insensitive substring of alt= attribute
"""
from __future__ import annotations
import argparse, mimetypes, os, re, shutil, sys, time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "index.html"
IMG_DIR = ROOT / "img"
BAK_DIR = ROOT / ".bak"

IMG_TAG = re.compile(r'<img\b[^>]*>', re.IGNORECASE)
SRC_ATTR = re.compile(r'\bsrc\s*=\s*"([^"]*)"', re.IGNORECASE)
ALT_ATTR = re.compile(r'\balt\s*=\s*"([^"]*)"', re.IGNORECASE)


def _slugify(s: str, fallback: str = "img") -> str:
    s = re.sub(r'[^a-zA-Z0-9]+', '-', s).strip('-').lower()
    return s[:60] or fallback


def _scan_imgs() -> list[dict]:
    text = HTML.read_text(encoding="utf-8")
    line_starts = [0]
    for i, ch in enumerate(text):
        if ch == '\n':
            line_starts.append(i + 1)

    def line_of(pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if line_starts[mid] <= pos:
                lo = mid + 1
            else:
                hi = mid - 1
        return hi + 1

    out = []
    for idx, m in enumerate(IMG_TAG.finditer(text)):
        tag = m.group(0)
        src_m = SRC_ATTR.search(tag)
        alt_m = ALT_ATTR.search(tag)
        out.append({
            "idx": idx,
            "line": line_of(m.start()),
            "start": m.start(),
            "end": m.end(),
            "tag": tag,
            "src": src_m.group(1) if src_m else "",
            "alt": alt_m.group(1) if alt_m else "",
        })
    return out


def _resolve_selector(sel: str) -> dict:
    imgs = _scan_imgs()
    if not imgs:
        sys.exit("no <img> tags found in index.html")
    s = sel.strip()
    if s.startswith("#") and s[1:].isdigit():
        i = int(s[1:])
        if not 0 <= i < len(imgs):
            sys.exit(f"#{i} out of range (have {len(imgs)} imgs)")
        return imgs[i]
    if s.isdigit():
        ln = int(s)
        for img in imgs:
            if img["line"] == ln:
                return img
        sys.exit(f"no <img> on line {ln}")
    needle = s.lower()
    matches = [im for im in imgs if needle in (im["alt"] or "").lower()]
    if not matches:
        sys.exit(f"no <img> with alt containing {s!r}")
    if len(matches) > 1:
        print(f"ambiguous selector {s!r} — {len(matches)} matches:", file=sys.stderr)
        for m in matches:
            print(f"  #{m['idx']} L{m['line']}: alt={m['alt']!r}", file=sys.stderr)
        sys.exit("be more specific (use #N or line number)")
    return matches[0]


def _backup() -> Path:
    BAK_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = BAK_DIR / f"index.html.{stamp}.bak"
    shutil.copy2(HTML, dst)
    baks = sorted(BAK_DIR.glob("index.html.*.bak"))
    for old in baks[:-10]:
        old.unlink()
    return dst


def _ext_for(url: str, content_type: str | None) -> str:
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        ext = mimetypes.guess_extension(ct)
        if ext == ".jpe":
            ext = ".jpg"
        if ext:
            return ext
    e = os.path.splitext(urlparse(url).path)[1].lower()
    return e if e in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg") else ".png"


def cmd_list(_args):
    imgs = _scan_imgs()
    for im in imgs:
        host = urlparse(im["src"]).netloc or ("(local)" if im["src"] else "(no src)")
        print(f"#{im['idx']:>2}  L{im['line']:<5}  {host:<22}  alt={im['alt']!r}")
        print(f"       src={im['src']}")
    print(f"\n{len(imgs)} image(s)")


def cmd_find(args):
    from ddgs import DDGS
    with DDGS() as ddg:
        results = list(ddg.images(args.query, max_results=args.n, safesearch=args.safe))
    if not results:
        sys.exit("no results")
    for i, r in enumerate(results):
        url = r.get("image") or r.get("url") or ""
        w, h = r.get("width", "?"), r.get("height", "?")
        host = urlparse(url).netloc
        title = (r.get("title") or "")[:70]
        print(f"[{i:>2}] {w}x{h}  {host:<28}  {title}")
        print(f"     {url}")
        if args.verbose:
            print(f"     source: {r.get('source','')}  page: {r.get('url','')}")


def cmd_grab(args):
    import requests
    IMG_DIR.mkdir(exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (imgtool)"}
    r = requests.get(args.url, headers=headers, timeout=30, stream=True)
    r.raise_for_status()
    ext = _ext_for(args.url, r.headers.get("Content-Type"))
    name = args.name or _slugify(os.path.splitext(os.path.basename(urlparse(args.url).path))[0]) or "img"
    dst = IMG_DIR / f"{name}{ext}"
    n = 1
    while dst.exists() and not args.overwrite:
        dst = IMG_DIR / f"{name}-{n}{ext}"
        n += 1
    with dst.open("wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    rel = dst.relative_to(ROOT).as_posix()
    print(rel)
    return rel


def _put(src: str, sel: str) -> dict:
    img = _resolve_selector(sel)
    text = HTML.read_text(encoding="utf-8")
    old_tag = img["tag"]
    if SRC_ATTR.search(old_tag):
        new_tag = SRC_ATTR.sub(f'src="{src}"', old_tag, count=1)
    else:
        new_tag = re.sub(r'<img\b', f'<img src="{src}"', old_tag, count=1, flags=re.IGNORECASE)
    if new_tag == old_tag:
        sys.exit("no change made (src already matches?)")
    bak = _backup()
    HTML.write_text(text[:img["start"]] + new_tag + text[img["end"]:], encoding="utf-8")
    return {"old": old_tag, "new": new_tag, "bak": bak, "img": img}


def cmd_put(args):
    res = _put(args.src, args.selector)
    old_src_m = SRC_ATTR.search(res["old"])
    print(f"replaced #{res['img']['idx']} on L{res['img']['line']}")
    print(f"  old src: {old_src_m.group(1) if old_src_m else '(none)'}")
    print(f"  new src: {args.src}")
    print(f"  backup:  {res['bak'].relative_to(ROOT)}")


def cmd_show(args):
    img = _resolve_selector(args.selector)
    print(f"#{img['idx']}  L{img['line']}")
    print(f"alt: {img['alt']!r}")
    print(f"src: {img['src']}")
    print(f"tag: {img['tag']}")


def cmd_quick(args):
    from ddgs import DDGS
    import requests
    img = _resolve_selector(args.selector)
    print(f"target: #{img['idx']} L{img['line']} alt={img['alt']!r}")
    print(f"searching: {args.query!r}")
    with DDGS() as ddg:
        results = list(ddg.images(args.query, max_results=args.n, safesearch="moderate"))
    if not results:
        sys.exit("no results")
    IMG_DIR.mkdir(exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (imgtool)"}
    name = args.name or _slugify(img["alt"] or args.query)
    last_err = None
    for i, r in enumerate(results[:args.n]):
        url = r.get("image") or r.get("url") or ""
        if not url:
            continue
        try:
            print(f"  [{i}] trying {urlparse(url).netloc} ({r.get('width','?')}x{r.get('height','?')}) ...", end=" ", flush=True)
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "")
            if "image" not in ct.lower():
                print(f"skip (ct={ct})")
                continue
            data = resp.content
            if len(data) < 2000:
                print(f"skip (tiny: {len(data)}B)")
                continue
            ext = _ext_for(url, ct)
            dst = IMG_DIR / f"{name}{ext}"
            n_ = 1
            while dst.exists():
                dst = IMG_DIR / f"{name}-{n_}{ext}"
                n_ += 1
            dst.write_bytes(data)
            rel = dst.relative_to(ROOT).as_posix()
            print(f"ok -> {rel}")
            res = _put(rel, args.selector)
            print(f"\nreplaced #{res['img']['idx']} on L{res['img']['line']}")
            print(f"  src: {rel}")
            print(f"  backup: {res['bak'].relative_to(ROOT)}")
            return
        except Exception as e:
            last_err = e
            print(f"fail ({type(e).__name__}: {e})")
    sys.exit(f"all {args.n} candidates failed; last error: {last_err}")


def cmd_undo(_args):
    if not BAK_DIR.exists():
        sys.exit("no backups")
    baks = sorted(BAK_DIR.glob("index.html.*.bak"))
    if not baks:
        sys.exit("no backups")
    latest = baks[-1]
    shutil.copy2(latest, HTML)
    print(f"restored from {latest.relative_to(ROOT)}")


def main():
    p = argparse.ArgumentParser(prog="imgtool", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(fn=cmd_list)

    f = sub.add_parser("find")
    f.add_argument("query")
    f.add_argument("-n", type=int, default=8)
    f.add_argument("--safe", default="moderate", choices=["on", "moderate", "off"])
    f.add_argument("-v", "--verbose", action="store_true")
    f.set_defaults(fn=cmd_find)

    g = sub.add_parser("grab")
    g.add_argument("url")
    g.add_argument("--name")
    g.add_argument("--overwrite", action="store_true")
    g.set_defaults(fn=cmd_grab)

    pu = sub.add_parser("put")
    pu.add_argument("src", help="image URL or local path (e.g. img/foo.png)")
    pu.add_argument("selector", help="line# | #N | alt substring")
    pu.set_defaults(fn=cmd_put)

    sh = sub.add_parser("show")
    sh.add_argument("selector")
    sh.set_defaults(fn=cmd_show)

    q = sub.add_parser("quick")
    q.add_argument("selector", help="line# | #N | alt substring")
    q.add_argument("query")
    q.add_argument("-n", type=int, default=6, help="how many candidates to try")
    q.add_argument("--name", help="filename slug under img/")
    q.set_defaults(fn=cmd_quick)

    sub.add_parser("undo").set_defaults(fn=cmd_undo)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
