"""Importing a contacts export is the one place JARVIS parses somebody
else's file format, so the odd shapes of real exports are covered."""
from __future__ import annotations

import pytest

from jarvis.store import memory
from jarvis.tools import contacts as ci

GOOGLE_CSV = """Name,Given Name,Family Name,Phone 1 - Type,Phone 1 - Value
Rahul Sharma,Rahul,Sharma,Mobile,+91 98765 43210
Mummy,Mummy,,Mobile,09123456789
Amit Verma,Amit,Verma,Mobile,8887776665
No Number,No,Number,,
London Friend,London,Friend,Mobile,00442079460958
"""

VCARD = """BEGIN:VCARD
FN:Priya Singh
TEL;TYPE=CELL:+91 99887 76655
END:VCARD
BEGIN:VCARD
FN:Papa
TEL;TYPE=CELL:9001234567
END:VCARD
"""


@pytest.fixture
def csv_file(workspace):
    path = workspace / "contacts.csv"
    path.write_text(GOOGLE_CSV, encoding="utf-8")
    return path


@pytest.fixture
def vcf_file(workspace):
    path = workspace / "phone.vcf"
    path.write_text(VCARD, encoding="utf-8")
    return path


class TestNumbers:
    @pytest.mark.parametrize("raw,expected", [
        ("+91 98765 43210", "+919876543210"),
        ("9876543210", "+919876543210"),        # bare Indian mobile
        ("09123456789", "+919123456789"),       # leading zero
        ("00442079460958", "+442079460958"),    # international prefix
        ("+1 (415) 555-0123", "+14155550123"),
    ])
    def test_numbers_are_normalised(self, raw, expected):
        assert ci._clean_number(raw) == expected

    @pytest.mark.parametrize("junk", ["", "Mobile", "n/a", "12"])
    def test_junk_is_rejected_rather_than_stored(self, junk):
        assert ci._clean_number(junk) is None


class TestImport:
    def test_google_csv_imports_the_value_column_not_the_type_column(self, csv_file):
        result = ci.import_contacts(str(csv_file))
        assert "Imported 4" in result
        assert memory.find_contact("rahul") == "+919876543210"

    def test_rows_without_a_number_are_skipped_and_counted(self, csv_file):
        assert "Skipped 1" in ci.import_contacts(str(csv_file))

    def test_vcard_imports(self, vcf_file):
        ci.import_contacts(str(vcf_file))
        assert memory.find_contact("priya") == "+919988776655"
        assert memory.find_contact("papa") == "+919001234567"

    def test_importing_the_same_file_twice_adds_nothing(self, csv_file):
        ci.import_contacts(str(csv_file))
        assert "already saved" in ci.import_contacts(str(csv_file))

    def test_a_missing_file_gives_a_plain_explanation(self):
        result = ci.import_contacts("no-such-file-anywhere.csv")
        assert "couldn't find" in result and "Downloads" in result

    def test_partial_names_match_a_contact(self, csv_file):
        ci.import_contacts(str(csv_file))
        assert memory.find_contact("Rahul") is not None    # case
        assert memory.find_contact("mummy") is not None
        assert memory.find_contact("nobody at all") is None
