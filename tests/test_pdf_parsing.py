import json
from pathlib import Path


def main() -> None:
    try:
        from src.data_processor import PatentParser
    except Exception as e:
        print(f"Skipping PDF parsing run: unavailable dependency/runtime ({e})")
        return

    raw_dir = Path("data/raw")
    if not raw_dir.exists():
        print("Missing data/raw directory. Create it and put example PDFs inside.")
        return

    pdfs = sorted(list(raw_dir.glob("*.pdf")))
    if not pdfs:
        print("No PDFs found in data/raw. Add example PDFs (e.g. office actions or patent specs).")
        return

    parser = PatentParser()

    for pdf_path in pdfs:
        print(f"\n=== {pdf_path} ===")
        try:
            text = parser.extract_text(str(pdf_path))
        except RuntimeError as e:
            print(f"Failed to extract text: {e}")
            continue

        office_action = parser.parse_office_action(text)
        sections = parser.split_sections(text)

        payload = {
            "file": str(pdf_path),
            "office_action": office_action,
            "sections": sections,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
