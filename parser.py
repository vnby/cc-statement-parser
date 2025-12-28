import pdfplumber
import re
import csv
from typing import List, Dict, Optional

class Transaction:
    def __init__(self, date: str, description: str, amount: str):
        self.date = date
        self.description = description
        self.amount = amount

    def to_dict(self) -> Dict[str, str]:
        return {
            "Date": self.date,
            "Description": self.description,
            "Amount": self.amount
        }
    
    def __repr__(self):
        return f"{self.date} | {self.description} | {self.amount}"

class BaseParser:
    def parse_line(self, line: str) -> Optional[Transaction]:
        raise NotImplementedError

class GenericParser(BaseParser):
    DATE_PATTERN = r'^(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}[-/.]\d{1,2})'
    AMOUNT_PATTERN = r'(-?[\d,]+\.\d{2})(-?)$' 

    def parse_line(self, line: str) -> Optional[Transaction]:
        line = line.strip()
        if not line: return None
        date_match = re.search(self.DATE_PATTERN, line)
        if not date_match: return None
        date_str = date_match.group(1)
        amount_match = re.search(self.AMOUNT_PATTERN, line)
        if not amount_match: return None
        amount_str = amount_match.group(0)
        desc_start, desc_end = date_match.end(), amount_match.start()
        if desc_start >= desc_end: return None
        description = line[desc_start:desc_end].strip()
        return Transaction(date_str, description, amount_str)

class BRIParser(BaseParser):
    """Specific parser for BRI Credit Card Statements."""
    DATE_PATTERN = r'^(\d{2}[-/.]\d{2}[-/.]\d{2,4})'
    AMOUNT_PATTERN = r'(-?[\d.,]+)(CR)?$' 

    def parse_line(self, line: str) -> Optional[Transaction]:
        line = line.strip()
        if not line: return None
        
        date_match = re.search(self.DATE_PATTERN, line)
        if not date_match: return None
        
        amount_match = re.search(self.AMOUNT_PATTERN, line)
        if not amount_match: return None
        
        # BRI Validation: Must have double date OR IDR
        has_double_date = re.match(r'^\d{2}[-/.]\d{2}[-/.]\d{2,4}\s+\d{2}[-/.]\d{2}[-/.]\d{2,4}', line)
        has_currency = 'IDR' in line
        if not (has_double_date or has_currency):
            return None

        date_str = date_match.group(1)
        raw_amount = amount_match.group(1)
        is_credit = amount_match.group(2) == 'CR'
        
        description = line[date_match.end():amount_match.start()].strip()
        description = re.sub(r'^\d{2}[-/.]\d{2}[-/.]\d{2,4}\s+', '', description)
        description = re.sub(r'\s+IDR(\s+[\d.0,]+)*$', '', description)
        
        # Normalisasi IDR Amount
        clean_amount = raw_amount.replace('.', '')
        if ',' in clean_amount: clean_amount = clean_amount.replace(',', '.')
        if is_credit: clean_amount = f"-{clean_amount}"

        return Transaction(date_str, description, clean_amount)

PARSERS = {
    "generic": GenericParser,
    "bri": BRIParser
}

def parse_pdf(pdf_path: str, password: str = None, bank_type: str = "generic") -> List[Transaction]:
    transactions = []
    parser_class = PARSERS.get(bank_type.lower(), GenericParser)
    parser = parser_class()
    
    with pdfplumber.open(pdf_path, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            for line in text.split('\n'):
                txn = parser.parse_line(line)
                if txn: transactions.append(txn)
                        
    return transactions

def export_to_csv(transactions: List[Transaction], output_path: str):
    if not transactions: return
    fieldnames = ["Date", "Description", "Amount"]
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for txn in transactions:
            writer.writerow(txn.to_dict())
    print(f"Exported {len(transactions)} transactions to {output_path}")
