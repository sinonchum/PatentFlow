from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import requests
from dotenv import load_dotenv

try:
    import epo_ops
    from epo_ops.models import Epodoc
except Exception as e:  # pragma: no cover
    raise RuntimeError(
        "python-epo-ops-client is required. Install it with: pip install python-epo-ops-client"
    ) from e


def _require_env(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    return val


def _sanitize_filename(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s.strip())
    return s.strip("_") or "file"


def _parse_xml(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text.encode("utf-8"))


def _extract_pdf_links_for_communications(root: ET.Element) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []

    for link in root.findall(".//{*}link"):
        href = link.attrib.get("href") or link.attrib.get("xlink:href")
        if not href:
            continue

        title = link.attrib.get("title") or link.attrib.get("{http://www.w3.org/1999/xlink}title") or ""
        rel = link.attrib.get("rel") or link.attrib.get("{http://www.w3.org/1999/xlink}rel") or ""
        type_attr = link.attrib.get("type") or link.attrib.get("{http://www.w3.org/1999/xlink}type") or ""

        hint = " ".join([title, rel, type_attr]).lower()
        if "communication" not in hint:
            continue

        if "pdf" in href.lower() or "application/pdf" in type_attr.lower():
            links.append((href, title or "communication"))

    if links:
        return links

    communication_context_paths = []
    for el in root.iter():
        text = (el.text or "").strip()
        if text and "communication" in text.lower():
            communication_context_paths.append(el)

    for ctx in communication_context_paths:
        for link in ctx.findall(".//{*}link"):
            href = link.attrib.get("href") or link.attrib.get("xlink:href")
            if not href:
                continue
            type_attr = link.attrib.get("type") or link.attrib.get("{http://www.w3.org/1999/xlink}type") or ""
            title = link.attrib.get("title") or link.attrib.get("{http://www.w3.org/1999/xlink}title") or "communication"
            if "pdf" in href.lower() or "application/pdf" in type_attr.lower():
                links.append((href, title))

    return links


def download_communications(
    application_number: str,
    *,
    out_dir: str = "data/raw",
) -> List[Path]:
    load_dotenv(override=False)

    key = _require_env("EPO_CONSUMER_KEY")
    secret = _require_env("EPO_CONSUMER_SECRET")

    if not key or not secret:
        raise RuntimeError(
            "Missing EPO credentials. Set EPO_CONSUMER_KEY and EPO_CONSUMER_SECRET in .env before downloading."
        )

    client = epo_ops.Client(key=key, secret=secret, accept_type="xml")

    app = Epodoc(re.sub(r"\D", "", application_number))
    response = client.register("application", app, constituents=["events", "procedural-steps", "biblio"])
    response.raise_for_status()

    root = _parse_xml(response.text)
    pdf_links = _extract_pdf_links_for_communications(root)

    if not pdf_links:
        raise RuntimeError(
            "No Communication PDF links were found in OPS register response. "
            "This may mean the file is not available via OPS, or the register constituents do not expose a PDF link for this case."
        )

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    saved: List[Path] = []
    for idx, (href, title) in enumerate(pdf_links, start=1):
        token = client.access_token.token
        filename = _sanitize_filename(f"{application_number}_communication_{idx}_{title}") + ".pdf"
        target = out_path / filename

        r = requests.get(
            href,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/pdf",
            },
            timeout=60,
        )
        r.raise_for_status()

        target.write_bytes(r.content)
        saved.append(target)

    return saved


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("application_number")
    parser.add_argument("--out-dir", default="data/raw")
    args = parser.parse_args()

    files = download_communications(args.application_number, out_dir=args.out_dir)
    for f in files:
        print(str(f))


if __name__ == "__main__":
    main()
