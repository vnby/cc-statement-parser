import pdfplumber
import re
import csv
import os
from dataclasses import dataclass
from typing import List, Optional
from abc import ABC, abstractmethod


@dataclass
class Transaction:
    date: str
    description: str
    amount: str
    bank: str = ""

    def to_dict(self, include_bank: bool = False) -> dict:
        d = {"Date": self.date, "Description": self.description, "Amount": self.amount}
        if include_bank:
            d["Bank"] = self.bank
        return d

    def __repr__(self):
        prefix = f"[{self.bank}] " if self.bank else ""
        return f"{prefix}{self.date} | {self.description} | {self.amount}"


class BaseParser(ABC):
    """Abstract base class for bank statement parsers."""

    @abstractmethod
    def parse(self, pdf) -> List[Transaction]:
        """Parse a pdfplumber PDF object and return transactions."""
        raise NotImplementedError


def _normalize_idr_amount(raw: str, is_credit: bool = False) -> str:
    """Normalize Indonesian-format amounts (1.234.567,89) to plain decimal (1234567.89).
    Also handles standard format amounts."""
    clean = raw.strip()
    # Indonesian format: dots as thousands sep, comma as decimal
    if '.' in clean and ',' in clean:
        clean = clean.replace('.', '').replace(',', '.')
    elif ',' in clean and '.' not in clean:
        # Comma as thousands separator only (e.g., 1,188,486)
        clean = clean.replace(',', '')
    elif '.' in clean:
        # Could be thousands separator only (e.g., 1.234.567) or decimal (e.g., 1234.56)
        parts = clean.split('.')
        if len(parts) > 2:
            clean = clean.replace('.', '')
        elif len(parts) == 2 and len(parts[1]) == 3:
            # Single dot with exactly 3 digits after: thousands separator (IDR, e.g., 5.000)
            clean = clean.replace('.', '')
        # Otherwise single dot: treat as decimal (standard format, e.g., 1234.56)
    if is_credit:
        clean = f"-{clean}"
    return clean


def _normalize_standard_amount(raw: str, is_credit: bool = False) -> str:
    """Normalize standard format amounts (commas as thousands, dot as decimal).
    E.g., 1,188,486 -> 1188486 or 63,400.00 -> 63400.00"""
    clean = raw.strip().replace(',', '')
    if is_credit:
        clean = f"-{clean}"
    return clean


# ---------------------------------------------------------------------------
# Bank-specific parsers
# ---------------------------------------------------------------------------

class BRIParser(BaseParser):
    """Parser for BRI Credit Card Statements.
    Layout: DD-MM-YYYY DD-MM-YYYY DESCRIPTION IDR 0.00 0.00 AMOUNT[CR]
    """
    LINE_RE = re.compile(
        r'^(\d{2}-\d{2}-\d{4})\s+'       # transaction date
        r'\d{2}-\d{2}-\d{4}\s+'          # posting date
        r'(.+?)\s+'                       # description
        r'IDR\s+[\d.,]+\s+[\d.,]+\s+'    # IDR + two intermediate amounts
        r'([\d.,]+)(CR)?$'               # final amount + optional CR
    )

    def parse(self, pdf) -> List[Transaction]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                m = self.LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group(1)
                desc = m.group(2).strip()
                raw_amount = m.group(3)
                is_credit = m.group(4) == 'CR'
                amount = _normalize_idr_amount(raw_amount, is_credit)
                transactions.append(Transaction(date_str, desc, amount))
        return transactions


class DBSParser(BaseParser):
    """Parser for DBS Credit Card Statements.
    Layout: MM/DD MM/DD DESCRIPTION Rp. AMOUNT[CR]
    Amounts use comma as thousands separator, prefixed with 'Rp.'.
    """
    LINE_RE = re.compile(
        r'^(\d{2}/\d{2})\s+'             # transaction date (MM/DD)
        r'\d{2}/\d{2}\s+'                # posting date
        r'(.+?)\s+'                       # description
        r'Rp\.\s*([\d,]+)(CR)?$'         # Rp. + amount + optional CR
    )

    def parse(self, pdf) -> List[Transaction]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                m = self.LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group(1)
                desc = m.group(2).strip()
                raw_amount = m.group(3)
                is_credit = m.group(4) == 'CR'
                amount = _normalize_standard_amount(raw_amount, is_credit)
                transactions.append(Transaction(date_str, desc, amount))
        return transactions


class UOBParser(BaseParser):
    """Parser for UOB Credit Card Statements.
    Layout: DD MMM  DD MMM  DESCRIPTION  [USD xx.xx] AMOUNT[CR]
    Indonesian month abbreviations (DES, JAN, etc).
    Amounts use comma as thousands, no decimal for IDR.
    Some lines have foreign currency before the IDR amount.
    """
    LINE_RE = re.compile(
        r'^(\d{2}\s+[A-Za-z]{3})\s+'     # transaction date (DD MMM)
        r'\d{2}\s+[A-Za-z]{3}\s+'         # posting date
        r'(.+?)\s+'                        # description
        r'([\d,]+)(CR)?$'                 # amount + optional CR
    )

    def parse(self, pdf) -> List[Transaction]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                m = self.LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group(1)
                desc = m.group(2).strip()
                # Remove foreign currency amount from end of description
                # e.g., "CLAUDE.AI SUBSCRIPTION SAN FRANCISCO USD 20.00"
                desc = re.sub(r'\s+[A-Z]{3}\s+[\d.]+$', '', desc)
                raw_amount = m.group(3)
                is_credit = m.group(4) == 'CR'
                amount = _normalize_standard_amount(raw_amount, is_credit)
                transactions.append(Transaction(date_str, desc, amount))
        return transactions


class HSBCParser(BaseParser):
    """Parser for HSBC Credit Card Statements.
    Layout: DDMMM DDMMM DESCRIPTION AMOUNT[CR]
    No space between day and month (e.g., 29DEC 25DEC).
    Amounts use comma as thousands, no decimal for IDR.
    Installment info lines (e.g., "10TH OF 12 INSTALLMENTS") are appended to the
    preceding transaction's description.
    """
    LINE_RE = re.compile(
        r'^(\d{2}[A-Z]{3})\s+'           # transaction date (DDMMM, e.g., 29DEC)
        r'\d{2}[A-Z]{3}\s+'              # posting date
        r'(.+?)\s+'                       # description
        r'([\d,]+)(CR)?$'                # amount + optional CR
    )
    INSTALLMENT_RE = re.compile(
        r'\d+\s*(?:ST|ND|RD|TH)\s*(?:OF|OUT\s*OF)\s*\d+\s*INSTALLMENTS?',
        re.IGNORECASE,
    )

    def parse(self, pdf) -> List[Transaction]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Check if line contains installment info
                installment_match = self.INSTALLMENT_RE.search(line)
                if installment_match and transactions:
                    m = self.LINE_RE.match(line)
                    if not m:
                        # Standalone installment line — append to previous transaction
                        transactions[-1].description += f" ({installment_match.group().strip()})"
                        continue
                    # Matched as transaction — check if description is purely installment info
                    desc = m.group(2).strip()
                    if self.INSTALLMENT_RE.search(desc):
                        transactions[-1].description += f" ({installment_match.group().strip()})"
                        continue
                m = self.LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group(1)
                desc = m.group(2).strip()
                raw_amount = m.group(3)
                is_credit = m.group(4) == 'CR'
                amount = _normalize_standard_amount(raw_amount, is_credit)
                transactions.append(Transaction(date_str, desc, amount))
        return transactions


class BNIParser(BaseParser):
    """Parser for BNI Credit Card Statements.
    Layout: DD-MM-YYYY DD-MM-YYYY DESCRIPTION AMOUNT[CR] [right-side-column-text]
    IDR format amounts (dots as thousands).
    Right side of page has summary info that gets merged into transaction lines.
    """
    # Known right-column keywords that appear after the transaction amount
    _RIGHT_COL_RE = re.compile(
        r'\s+(?:BATAS KREDIT|BATAS PENARIKAN|SISA KREDIT|SISA PENARIKAN|'
        r'TAGIHAN BULAN|PEMBELANJAAN|PENARIKAN TUNAI|'
        r'BIAYA ADM|KOLEKTIBILITAS|PEMBAYARAN MINIMUM|TANGGAL JATUH|'
        r'JUMLAH POIN|POIN KADALUARSA|TOTAL TAGIHAN|'
        r'PEMBAYARAN\s+\d).*$',
        re.IGNORECASE
    )

    LINE_RE = re.compile(
        r'^(\d{2}-\d{2}-\d{4})\s+'       # transaction date
        r'\d{2}-\d{2}-\d{4}\s+'          # posting date
        r'(.+?)\s+'                       # description
        r'(\d{1,3}(?:\.\d{3})+)(CR)?'    # amount (IDR dot format, must have dot) + optional CR
    )

    def parse(self, pdf) -> List[Transaction]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                # Strip right-column text before parsing
                line = self._RIGHT_COL_RE.sub('', line)
                m = self.LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group(1)
                desc = m.group(2).strip()
                raw_amount = m.group(3)
                is_credit = m.group(4) == 'CR'
                amount = _normalize_idr_amount(raw_amount, is_credit)
                transactions.append(Transaction(date_str, desc, amount))
        return transactions


class BCAParser(BaseParser):
    """Parser for BCA Credit Card Statements.
    Layout: DD-MMM DD-MMM DESCRIPTION AMOUNT [CR]
    Indonesian month abbreviations (DES, JAN, etc).
    IDR format amounts (dots as thousands).
    """
    LINE_RE = re.compile(
        r'^(\d{2}-[A-Za-z]{3})\s+'       # transaction date (DD-MMM)
        r'\d{2}-[A-Za-z]{3}\s+'          # posting date
        r'(.+?)\s+'                       # description
        r'([\d.]+)\s*(CR)?$'             # amount (IDR dot format) + optional CR
    )

    def parse(self, pdf) -> List[Transaction]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                m = self.LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group(1)
                desc = m.group(2).strip()
                raw_amount = m.group(3)
                is_credit = m.group(4) == 'CR'
                amount = _normalize_idr_amount(raw_amount, is_credit)
                transactions.append(Transaction(date_str, desc, amount))
        return transactions


class MandiriParser(BaseParser):
    """Parser for Mandiri Credit Card Statements.
    Layout: DD-Mmm-YY  DD-Mmm-YY  DESCRIPTION  AMOUNT [CR]
    Amounts use standard format: 687,528.00 (comma thousands, dot decimal).
    """
    LINE_RE = re.compile(
        r'^(\d{2}-[A-Za-z]{3}-\d{2,4})\s+'   # transaction date (DD-Mmm-YY)
        r'\d{2}-[A-Za-z]{3}-\d{2,4}\s+'       # posting date
        r'(.+?)\s+'                             # description
        r'([\d,]+\.\d{2})\s*(CR)?$'            # amount + optional CR
    )

    def parse(self, pdf) -> List[Transaction]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                m = self.LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group(1)
                desc = m.group(2).strip()
                raw_amount = m.group(3)
                is_credit = m.group(4) == 'CR'
                amount = _normalize_standard_amount(raw_amount, is_credit)
                transactions.append(Transaction(date_str, desc, amount))
        return transactions


class CIMBNiagaParser(BaseParser):
    """Parser for CIMB Niaga Credit Card Statements.
    Layout: DD/MM DD/MM DESCRIPTION AMOUNT [CR]
    Amounts use standard format: 63,400.00 (comma thousands, dot decimal).
    """
    LINE_RE = re.compile(
        r'^(\d{2}/\d{2})\s+'             # transaction date (DD/MM)
        r'\d{2}/\d{2}\s+'                # posting date
        r'(.+?)\s+'                       # description
        r'([\d,]+\.\d{2})\s*(CR)?$'      # amount + optional CR
    )

    def parse(self, pdf) -> List[Transaction]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                m = self.LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group(1)
                desc = m.group(2).strip()
                raw_amount = m.group(3)
                is_credit = m.group(4) == 'CR'
                amount = _normalize_standard_amount(raw_amount, is_credit)
                transactions.append(Transaction(date_str, desc, amount))
        return transactions


class GenericParser(BaseParser):
    """Fallback parser using common transaction patterns."""
    LINE_RE = re.compile(
        r'^(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}[-/.]\d{1,2})\s+'
        r'(.+?)\s+'
        r'(-?[\d.,]+)\s*(CR)?$'
    )

    def parse(self, pdf) -> List[Transaction]:
        transactions = []
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split('\n'):
                line = line.strip()
                m = self.LINE_RE.match(line)
                if not m:
                    continue
                date_str = m.group(1)
                desc = m.group(2).strip()
                raw_amount = m.group(3)
                is_credit = m.group(4) == 'CR'
                amount = _normalize_idr_amount(raw_amount, is_credit)
                transactions.append(Transaction(date_str, desc, amount))
        return transactions


# ---------------------------------------------------------------------------
# Registry & bank detection
# ---------------------------------------------------------------------------

PARSERS = {
    "bri": BRIParser,
    "dbs": DBSParser,
    "uob": UOBParser,
    "hsbc": HSBCParser,
    "bni": BNIParser,
    "bca": BCAParser,
    "mandiri": MandiriParser,
    "cimb_niaga": CIMBNiagaParser,
    "generic": GenericParser,
}

# Password format hints shown to user during prompting
PASSWORD_HINTS = {
    "bri":        ("DDMmmYYYY", "01Jan1990"),
    "dbs":        ("DDMmmYYYY + last 4 digits of card", "01Jan1990XXXX"),
    "uob":        ("ddmmyyyy", "01011990"),
    "hsbc":       ("ddMmmyyyy", "01Jan1990"),
    "bni":        ("DDMMYYYY", "01011990"),
    "bca":        ("ddmmyyyy", "01011990"),
    "mandiri":    ("DDMMYYYY", "01011990"),
    "cimb_niaga": ("ddmmyy", "010190"),
}

# Detection rules: list of (regex_pattern, bank_key) tested against the filename (not path)
_DETECTION_RULES = [
    # BRI: 038732_Billing_Statement_8303.pdf
    (r'^\d+_Billing_Statement_\d+\.pdf$', 'bri'),
    # Mandiri: CC_eBilling_Jan_2026_xxxx6835.pdf
    (r'^CC_eBilling_.+\.pdf$', 'mandiri'),
    # CIMB Niaga: sharia card billing statement_19-01-2026_546593608.pdf
    (r'^sharia\s*card\s*billing\s*statement_.+\.pdf$', 'cimb_niaga'),
    # BNI: ebillingbw012026.pdf
    (r'^ebillingbw\d+\.pdf$', 'bni'),
    # UOB: CSTEPC270126000000934.pdf
    (r'^CSTEPC\d+\.pdf$', 'uob'),
    # DBS: 202601240000733869.pdf (16+ digit filename)
    (r'^\d{16,}\.pdf$', 'dbs'),
    # HSBC: 20260121.pdf or 20260121 (2).pdf (8-digit date, optional suffix)
    (r'^20\d{6}(\s*\(\d+\))?\.pdf$', 'hsbc'),
    # BCA: 18519906_10012026_1768094449538.pdf (3 underscore-separated segments)
    (r'^\d+_\d+_\d+\.pdf$', 'bca'),
]


def detect_bank(filepath: str) -> Optional[str]:
    """Detect bank from PDF filename. Returns bank key or None."""
    filename = os.path.basename(filepath)
    for pattern, bank_key in _DETECTION_RULES:
        if re.match(pattern, filename, re.IGNORECASE):
            return bank_key
    return None


# ---------------------------------------------------------------------------
# Main parse / export functions
# ---------------------------------------------------------------------------

def parse_pdf(pdf_path: str, password: str = None, bank_type: str = "generic") -> List[Transaction]:
    """Open a PDF and parse transactions using the specified bank parser."""
    parser_class = PARSERS.get(bank_type.lower(), GenericParser)
    parser = parser_class()

    with pdfplumber.open(pdf_path, password=password) as pdf:
        transactions = parser.parse(pdf)

    # Tag each transaction with the bank name
    bank_label = bank_type.upper().replace('_', ' ')
    for txn in transactions:
        txn.bank = bank_label

    return transactions


def export_to_csv(transactions: List[Transaction], output_path: str,
                   include_bank: bool = False):
    """Export transactions to a CSV file."""
    if not transactions:
        return
    fieldnames = ["Date", "Description", "Amount"]
    if include_bank:
        fieldnames.insert(0, "Bank")
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for txn in transactions:
            writer.writerow(txn.to_dict(include_bank=include_bank))
    print(f"Exported {len(transactions)} transactions to {output_path}")
