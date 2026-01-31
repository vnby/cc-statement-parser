# CC Statement Parser

An offline CLI tool that extracts transactions from Indonesian bank credit card statement PDFs and exports them to CSV.

## Supported Banks

| Bank | Date Format | Password Format (DOB) |
|------|-------------|----------------------|
| BRI | DD-MM-YYYY | DDMmmYYYY (e.g. 01Jan1990) |
| DBS | MM/DD | DDMmmYYYY + last 4 card digits |
| UOB | DD MMM | ddmmyyyy (e.g. 01011990) |
| HSBC | DDMMM | ddMmmyyyy (e.g. 01Jan1990) |
| BNI | DD-MM-YYYY | DDMMYYYY (e.g. 01011990) |
| BCA | DD-MMM | ddmmyyyy (e.g. 01011990) |
| Mandiri | DD-Mmm-YY | DDMMYYYY (e.g. 01011990) |
| CIMB Niaga | DD/MM | ddmmyy (e.g. 010190) |

A generic fallback parser is used when the bank cannot be detected.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Or use the included helper script which handles venv setup automatically:

```bash
chmod +x run.sh
./run.sh <command> [options]
```

## Usage

### Batch mode (primary workflow)

Place your PDF statements in the `cc-statement/` folder, then run:

```bash
python3 cli.py run
```

This will:
1. Scan the `cc-statement/` directory for all PDFs
2. Auto-detect each bank from the filename
3. Prompt for your date of birth (used to derive PDF passwords)
4. Parse all statements and export to a single `output.csv`

Options:

```
--input-dir, -d   Directory containing PDFs (default: cc-statement/)
--output, -o      Output CSV path (default: output.csv)
--per-bank        Export separate CSV files per bank
--output-dir      Output directory for per-bank CSVs (default: current dir)
```

### Single file mode

```bash
python3 cli.py parse statement.pdf
```

Options:

```
--bank, -b        Bank type (auto-detected from filename if omitted)
--output, -o      Output CSV path (default: output.csv)
--password, -p    PDF password
```

### Debug mode

Dump raw extracted text from a PDF for troubleshooting or developing new parsers:

```bash
python3 cli.py debug statement.pdf
```

## CSV Output

Each row contains:

| Column | Description |
|--------|-------------|
| Bank | Bank name (only in combined mode) |
| Date | Transaction date |
| Description | Transaction description |
| Amount | Normalized amount (negative = credit/payment) |

## How Bank Detection Works

Banks are detected from the PDF filename using pattern matching. Examples:

- `038732_Billing_Statement_8303.pdf` → BRI
- `CC_eBilling_Jan_2026_xxxx6835.pdf` → Mandiri
- `ebillingbw012026.pdf` → BNI
- `CSTEPC270126000000934.pdf` → UOB
- `20260121.pdf` → HSBC
- `18519906_10012026_1768094449538.pdf` → BCA
- `202601240000733869.pdf` → DBS
- `sharia card billing statement_19-01-2026_546593608.pdf` → CIMB Niaga

## Dependencies

- [pdfplumber](https://github.com/jsvine/pdfplumber) - PDF text extraction
