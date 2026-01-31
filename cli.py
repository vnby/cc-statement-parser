import argparse
import glob
import os
import sys
import getpass
from datetime import datetime
import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException
from pdfminer.pdfdocument import PDFPasswordIncorrect
from parser import parse_pdf, export_to_csv, detect_bank, PARSERS, PASSWORD_HINTS

STATEMENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cc-statement")


def _ask_dob() -> datetime:
    """Prompt user for date of birth and return as datetime."""
    while True:
        raw = input("Enter your date of birth (DD-MM-YYYY): ").strip()
        try:
            return datetime.strptime(raw, "%d-%m-%Y")
        except ValueError:
            print("Invalid format. Please use DD-MM-YYYY (e.g. 01-01-1990)")


def _dob_to_password(dob: datetime, bank: str, dbs_last4: str = "") -> str:
    """Convert a DOB datetime to the bank-specific password string."""
    # BRI:        DDMmmYYYY    -> 01Jan1990
    # DBS:        DDMmmYYYY    -> 01Jan1990XXXX (+ last 4 digits)
    # HSBC:       ddMmmyyyy    -> 01Jan1990
    # UOB:        ddmmyyyy     -> 01011990
    # BNI:        DDMMYYYY     -> 01011990
    # BCA:        ddmmyyyy     -> 01011990
    # Mandiri:    DDMMYYYY     -> 01011990
    # CIMB Niaga: ddmmyy       -> 010190
    fmt_map = {
        "bri":        lambda d: d.strftime("%d%b%Y").replace(d.strftime("%b"), d.strftime("%b").capitalize()),
        "dbs":        lambda d: d.strftime("%d%b%Y").replace(d.strftime("%b"), d.strftime("%b").capitalize()) + dbs_last4,
        "hsbc":       lambda d: d.strftime("%d%b%Y").replace(d.strftime("%b"), d.strftime("%b").capitalize()),
        "uob":        lambda d: d.strftime("%d%m%Y"),
        "bni":        lambda d: d.strftime("%d%m%Y"),
        "bca":        lambda d: d.strftime("%d%m%Y"),
        "mandiri":    lambda d: d.strftime("%d%m%Y"),
        "cimb_niaga": lambda d: d.strftime("%d%m%y"),
    }
    formatter = fmt_map.get(bank)
    if formatter:
        return formatter(dob)
    return None


def _password_prompt(bank: str, pdf_path: str) -> str:
    """Build a password prompt string with bank-specific format hint (fallback)."""
    bank_upper = bank.upper().replace('_', ' ')
    hint_info = PASSWORD_HINTS.get(bank)
    if hint_info:
        fmt, example = hint_info
        return f"[{bank_upper}] Password (DOB format: {fmt}, e.g. {example}): "
    return f"[{bank_upper}] Password: "


def _parse_single_pdf(pdf_path: str, bank: str, password: str = None):
    """Parse a single PDF with interactive password retry. Returns transactions list."""
    current_password = password
    while True:
        try:
            transactions = parse_pdf(pdf_path, current_password, bank)
            return transactions
        except (PDFPasswordIncorrect, PdfminerException) as e:
            error_msg = str(e).lower()
            if isinstance(e, PDFPasswordIncorrect) or "password" in error_msg or current_password is None:
                if current_password is not None:
                    print("  Error: Incorrect password.")
                prompt = _password_prompt(bank, pdf_path)
                current_password = getpass.getpass(f"  {prompt}")
            else:
                raise


def cmd_run(args):
    """Scan cc-statement folder, parse all PDFs, and export to CSV."""
    input_dir = args.input_dir

    if not os.path.isdir(input_dir):
        print(f"Error: Directory not found: {input_dir}")
        sys.exit(1)

    pdf_files = sorted(glob.glob(os.path.join(input_dir, "*.pdf")))
    if not pdf_files:
        print(f"No PDF files found in {input_dir}")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF file(s) in {input_dir}\n")

    # Detect banks for all files upfront
    file_banks = []
    for pdf_path in pdf_files:
        bank = detect_bank(pdf_path) or "generic"
        file_banks.append((pdf_path, bank))

    # Ask DOB once
    dob = _ask_dob()

    # If any file is DBS, ask for last 4 digits
    dbs_last4 = ""
    has_dbs = any(bank == "dbs" for _, bank in file_banks)
    if has_dbs:
        dbs_last4 = input("DBS detected — enter last 4 digits of your DBS card: ").strip()

    # Pre-compute passwords per bank
    bank_passwords = {}
    for _, bank in file_banks:
        if bank not in bank_passwords:
            bank_passwords[bank] = _dob_to_password(dob, bank, dbs_last4)

    print()

    all_transactions = []
    bank_transactions = {}  # bank_key -> [transactions]

    for i, (pdf_path, bank) in enumerate(file_banks, 1):
        filename = os.path.basename(pdf_path)
        if bank == "generic":
            print(f"[{i}/{len(pdf_files)}] {filename} (bank: UNKNOWN)")
        else:
            print(f"[{i}/{len(pdf_files)}] {filename} (bank: {bank.upper().replace('_', ' ')})")

        password = bank_passwords.get(bank)
        try:
            transactions = _parse_single_pdf(pdf_path, bank, password)
        except Exception as e:
            print(f"  Error parsing: {e}")
            continue

        if transactions:
            print(f"  -> {len(transactions)} transactions extracted")
            all_transactions.extend(transactions)
            bank_transactions.setdefault(bank, []).extend(transactions)
        else:
            print("  -> No transactions found (try 'debug' command to inspect)")

        print()

    if not all_transactions:
        print("No transactions found across all files.")
        sys.exit(0)

    print(f"Total: {len(all_transactions)} transactions from {len(bank_transactions)} bank(s)\n")

    if args.per_bank:
        # Export separate CSV per bank
        output_dir = args.output_dir or "."
        os.makedirs(output_dir, exist_ok=True)
        for bank_key, txns in sorted(bank_transactions.items()):
            bank_label = bank_key.upper().replace('_', ' ')
            csv_name = f"{bank_key}_transactions.csv"
            csv_path = os.path.join(output_dir, csv_name)
            export_to_csv(txns, csv_path, include_bank=False)
    else:
        # Export single combined CSV with Bank column
        output_path = args.output
        export_to_csv(all_transactions, output_path, include_bank=True)


def cmd_parse(args):
    """Parse a single credit card statement PDF and export to CSV."""
    bank = args.bank
    if not bank:
        bank = detect_bank(args.input_file)
        if bank:
            print(f"Auto-detected bank: {bank.upper().replace('_', ' ')}")
        else:
            bank = "generic"
            print("Could not detect bank from filename. Using generic parser.")

    print(f"Parsing {args.input_file} using '{bank}' parser...")

    try:
        transactions = _parse_single_pdf(args.input_file, bank, args.password)
        if transactions:
            export_to_csv(transactions, args.output)
        else:
            print("\n[!] No transactions found. Try 'debug' command to inspect raw text.")
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_debug(args):
    """Extract and dump raw text from a PDF for parser development."""
    bank = detect_bank(args.input_file)
    bank_label = bank.upper().replace('_', ' ') if bank else "UNKNOWN"
    print(f"--- DEBUG: {args.input_file} (detected: {bank_label}) ---\n")

    current_password = args.password
    while True:
        try:
            pdf = pdfplumber.open(args.input_file, password=current_password)
            break
        except (PDFPasswordIncorrect, PdfminerException) as e:
            error_msg = str(e).lower()
            if isinstance(e, PDFPasswordIncorrect) or "password" in error_msg or current_password is None:
                if current_password is not None:
                    print("Error: Incorrect password.")
                prompt = _password_prompt(bank or "generic", args.input_file)
                current_password = getpass.getpass(prompt)
            else:
                print(f"Error: {e}")
                sys.exit(1)

    with pdf:
        for i, page in enumerate(pdf.pages):
            print(f"--- PAGE {i + 1} ---")
            text = page.extract_text()
            print(text if text else "[No text extracted]")
            print()


def main():
    ap = argparse.ArgumentParser(description="Credit Card Statement Parser (multi-bank)")
    sub = ap.add_subparsers(dest='command', help='Command to run')

    # run command (primary batch workflow)
    p_run = sub.add_parser('run', help='Parse all PDFs in cc-statement folder and export to CSV')
    p_run.add_argument('--input-dir', '-d', default=STATEMENT_DIR,
                       help=f'Directory containing PDF statements (default: {STATEMENT_DIR})')
    p_run.add_argument('--output', '-o', default='output.csv',
                       help='Output CSV path (default: output.csv)')
    p_run.add_argument('--per-bank', action='store_true',
                       help='Export separate CSV per bank instead of a single combined file')
    p_run.add_argument('--output-dir', default='.',
                       help='Output directory for per-bank CSVs (default: current dir)')

    # parse command (single file)
    p_parse = sub.add_parser('parse', help='Parse a single PDF statement and export to CSV')
    p_parse.add_argument('input_file', help='Path to PDF statement')
    p_parse.add_argument('--bank', '-b', choices=list(PARSERS.keys()), default=None,
                         help='Bank type (auto-detected from filename if omitted)')
    p_parse.add_argument('--output', '-o', default='output.csv', help='Output CSV path')
    p_parse.add_argument('--password', '-p', help='PDF password')

    # debug command
    p_debug = sub.add_parser('debug', help='Dump raw text from PDF for parser development')
    p_debug.add_argument('input_file', help='Path to PDF statement')
    p_debug.add_argument('--password', '-p', help='PDF password')

    args = ap.parse_args()

    if args.command == 'run':
        cmd_run(args)
    elif args.command == 'parse':
        cmd_parse(args)
    elif args.command == 'debug':
        cmd_debug(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
