"""Run the supplied EGFR fragment directly and tee all diagnostics to try_one.log."""
import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
SMILES = "C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1"
SEQUENCE = (
    "MRPSGTAGAALLALLAALCPASRALEEKKVCQGTSNKLTQLGTFEDHFLSLQRMFNNCEVVLGNLEITYVQRNYDLSFL"
    "KTIQEVAGYVLIALNTVERIPLENLQIIRGNMYYENSYALAVLSNYDANKTGLKELPMRNLQEILHGAVRFSNNPALCNVESIQWRDIVSS"
    "DFLSNMSMDFQNHLGSCQKCDPSCPNGSCWGAGEENCQKLTKIICAQQCSGRCRGKSPSDCCHNQCAAGCTGPRESDCLVCRKFRDEATCK"
    "DTCPPLMLYNPTTYQMDVNPEGKYSFGATCVKKCPRNYVVTDHGSCVRACGADSYEMEEDGVRKCKKCEGPCRKVCNGIGIGEFKDSLSIN"
    "ATNIKHFKNCTSISGDLHILPVAFRGDSFTHTPPLDPQELDILKTVKEITGFLLIQAWPENRTDLHAFENLEIIRGRTKQHGQFSLAVVSL"
    "NITSLGLRSLKEISDGDVIISGNKNLCYANTINWKKLFGTSGQKTKIISNRGENSCKATGQVCHALCSPEGCWGPEPRDCVSCRNVSRGRE"
    "CVDKCNLLEGEPREFVENSECIQCHPECLPQAMNITCTGRGPDNCIQCAHYIDGPHCVKTCPAGVMGENNTLVWKYADAGHVCHLCHPNCT"
    "YGCTGPGLEGCPTNGPKIPS"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smiles", default=SMILES)
    parser.add_argument("--full-egfr", action="store_true", help="Use the full receptor from the app demo")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--log", type=Path, default=ROOT / "try_one.log")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.worker:
        with args.log.open("w", encoding="utf-8") as log, subprocess.Popen(
            [sys.executable, "-u", __file__, "--worker", *sys.argv[1:]],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        ) as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
                log.flush()
            return process.wait()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    os.environ["CPI_DIRECT_DIAGNOSTIC"] = "1"
    config = ROOT / ".runtime/local_servers.json"
    if config.exists():
        os.environ.setdefault("PERCEIVER_APP_URL", json.loads(config.read_text())["app_url"])
    sys.path.insert(0, str(ROOT / "docking/scripts"))
    from cpi_sequence_docking import predict_and_dock
    from cpi_contacts import analyze
    from docking_stages import start_trace
    timings = start_trace()
    sequence = json.loads((ROOT / ".runtime/check_pair.json").read_text())["sequence"] if args.full_egfr else SEQUENCE
    folder = Path(tempfile.mkdtemp(prefix="try-one-", dir=ROOT / ".runtime"))
    print(f"Output folder {folder}; {len(sequence)} residues", flush=True)
    result = predict_and_dock(args.smiles, sequence, folder, force_rebuild=args.no_cache)
    contacts = analyze(folder)["contacts"]
    print(json.dumps(dict(source=result["protein_source"], cache_hit=result["receptor_cache_hit"],
                          vina=result["selected_vina_score_kcal_mol"], contacts=len(contacts), timings=timings), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
