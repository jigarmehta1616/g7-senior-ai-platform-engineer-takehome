from datetime import date

import pytest

from support_platform.domain.models import CaseStatus, SupportTier
from support_platform.upstreams.translators import (
    TranslationError,
    accounts_from_csv,
    apply_xml_feed,
    case_from_upstream,
    usage_from_sql_result,
)

APPENDIX_CASE = {
    "id": "CS-10231", "accountId": "ACC-007", "priority": "P1", "Status": "open",
    "openedAt": "2026-10-24T08:12:00Z", "subject": "Backup failing on node 3",
    "Comments": [{"author": "jdoe", "body": "Investigating", "at": "2026-10-24T09:00:00Z"}],
}


def test_appendix_case_shape_with_inconsistent_casing_is_normalised():
    case = case_from_upstream(APPENDIX_CASE)
    assert case.status is CaseStatus.OPEN
    assert case.comments and case.comments[0].author == "jdoe"
    assert case.version == 1 and case.escalation.level == 0


def test_unknown_status_is_rejected_not_guessed():
    with pytest.raises(TranslationError):
        case_from_upstream({**APPENDIX_CASE, "Status": "frobnicated"})


def test_csv_and_xml_feed_merge_xml_wins_for_tier_and_renewal():
    csv_text = ("account_id,name,support_tier,contract_end,arr_usd\n"
                "ACC-77,Acme Corp,Platinum,2027-01-15,480000\n"
                "ACC-104,Wayne,Silver,2027-02-01,45000\n")
    xml = ('<accounts><account id="ACC-104"><tier>Gold</tier><renewal>2027-03-01</renewal></account>'
           '<account id="ACC-999"><tier>Gold</tier></account></accounts>')
    accounts = apply_xml_feed(accounts_from_csv(csv_text), xml)
    assert accounts["ACC-77"].arr_usd == 480000
    assert accounts["ACC-104"].support_tier is SupportTier.GOLD
    assert accounts["ACC-104"].contract_end == date(2027, 3, 1)
    assert "ACC-999" not in accounts           # feed entries for unknown accounts are ignored


def test_account_ids_are_opaque_not_normalised():
    csv_text = ("account_id,name,support_tier,contract_end,arr_usd\n"
                "ACC-77,Acme,Platinum,2027-01-15,1\nACC-007,Globex,Platinum,2027-01-15,2\n")
    assert set(accounts_from_csv(csv_text)) == {"ACC-77", "ACC-007"}


def test_snowflake_string_typed_rows_are_coerced():
    result = {"resultSetMetaData": {"rowType": [{"name": n} for n in
                                                ("ACCOUNT_ID", "MONTH", "PROTECTED_TB", "API_CALLS", "ACTIVE_USERS")]},
              "data": [["ACC-007", "2026-09", "412.5", "1203331", "87"]]}
    [row] = usage_from_sql_result(result)
    assert row.protected_tb == 412.5 and row.api_calls == 1203331 and row.active_users == 87
