import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OUTPUT = Path("data/raw/uniprot.tsv")
TARGET_ROWS = 5000
PAGE_SIZE = 500

params = {
    "query": "reviewed:true",
    "fields": "accession,sequence,length,go_f",
    "format": "tsv",
    "size": PAGE_SIZE,
}

url = (
    "https://rest.uniprot.org/uniprotkb/search?"
    + urlencode(params)
)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)

rows_written = 0
header_written = False
page_number = 0

with OUTPUT.open("w", encoding="utf-8", newline="") as output_file:

    while url and rows_written < TARGET_ROWS:

        page_number += 1

        request = Request(
            url,
            headers={
                "User-Agent": "protein-function-predictor/0.1"
            },
        )

        with urlopen(request, timeout=60) as response:

            text = response.read().decode("utf-8")
            lines = text.rstrip("\n").split("\n")

            if not header_written:
                output_file.write(lines[0] + "\n")
                header_written = True

            for line in lines[1:]:

                if rows_written >= TARGET_ROWS:
                    break

                output_file.write(line + "\n")
                rows_written += 1

            link_header = response.headers.get("Link", "")

            match = re.search(
                r'<([^>]+)>;\s*rel="next"',
                link_header,
            )

            url = match.group(1) if match else None

        print(
            f"Page {page_number}: "
            f"{rows_written}/{TARGET_ROWS} proteins"
        )

print()
print(f"Saved {rows_written} proteins to {OUTPUT}")