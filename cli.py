import argparse
import sys
import getpass
import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException
from pdfminer.pdfdocument import PDFPasswordIncorrect
from parser import parse_pdf, export_to_csv, PARSERS

def secure_open_pdf(pdf_path, password=None):
    current_password = password
    while True:
        try:
            return pdfplumber.open(pdf_path, password=current_password)
        except (PDFPasswordIncorrect, PdfminerException) as e:
            error_msg = str(e).lower()
            if isinstance(e, PDFPasswordIncorrect) or "password" in error_msg or current_password is None:
                if current_password is not None: print("Error: Incorrect password.")
                current_password = getpass.getpass(f"Enter Password for {pdf_path}: ")
            else:
                raise e

def debug_layout(pdf_path, password=None):
    print(f"--- DEBUG: Extracting text from {pdf_path} ---")
    try:
        with secure_open_pdf(pdf_path, password) as pdf:
            for i, page in enumerate(pdf.pages):
                print(f"--- PAGE {i+1} ---"); text = page.extract_text()
                print(text if text else "[No text extracted]"); print("\n")
    except Exception as e: print(f"Error: {e}")

def main():
    parser = argparse.ArgumentParser(description="Offline Credit Card Statement Parser")
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    parse_parser = subparsers.add_parser('parse', help='Parse a PDF')
    parse_parser.add_argument('input_file', help='Path to PDF')
    parse_parser.add_argument('--bank', '-b', choices=PARSERS.keys(), default='generic', help='Bank format (e.g., bri)')
    parse_parser.add_argument('--output', '-o', default='output.csv', help='Output CSV')
    parse_parser.add_argument('--password', '-p', help='PDF password')

    debug_parser = subparsers.add_parser('debug', help='Debug PDF text')
    debug_parser.add_argument('input_file', help='Path to PDF')
    debug_parser.add_argument('--password', '-p', help='PDF password')

    args = parser.parse_args()

    if args.command == 'parse':
        print(f"Parsing {args.input_file} using '{args.bank}' format...")
        current_password = args.password
        while True:
            try:
                transactions = parse_pdf(args.input_file, current_password, args.bank)
                if transactions:
                    export_to_csv(transactions, args.output)
                else:
                    print("\n[!] No transactions found. Try 'debug' command.")
                break
            except (PDFPasswordIncorrect, PdfminerException) as e:
                error_msg = str(e).lower()
                if isinstance(e, PDFPasswordIncorrect) or "password" in error_msg or current_password is None:
                    if current_password is not None: print("Error: Incorrect password.")
                    current_password = getpass.getpass("Enter PDF Password: ")
                else: raise e
            except Exception as e:
                import traceback; traceback.print_exc(); sys.exit(1)
    elif args.command == 'debug': debug_layout(args.input_file, args.password)
    else: parser.print_help()

if __name__ == "__main__": main()
