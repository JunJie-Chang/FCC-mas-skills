"""Regression tests for utils/unit_convert.to_chinese_amount.

These are the canonical cases that previously broke in production — chiefly
the English ``billion`` vs Chinese ``億`` 10× confusion (and the ``仟元``
1000× under-count). Keep this list in sync with the self-test block in
utils/unit_convert.py.
"""
import pytest

from utils.unit_convert import to_chinese_amount

CASES = [
    # English billion → 億 (the original #8 bug)
    ((56, "billion", "USD"), "560 億美元"),
    ((9, "billion", "USD"), "90 億美元"),
    ((9.4, "billion", "USD"), "94 億美元"),
    # Other dollar magnitudes
    ((1, "million", "USD"), "100 萬美元"),
    ((1.5, "trillion", "USD"), "1.5 兆美元"),
    ((500, "million", "USD"), "5 億美元"),
    # Taiwan dollars
    ((5.2, "trillion", "TWD"), "5.2 兆新台幣"),
    ((2.3, "billion", "TWD"), "23 億新台幣"),
    # Plain numbers (already base units)
    ((5000, "plain", "USD"), "5,000 美元"),
    ((50000, "plain", "USD"), "5 萬美元"),
    # Percent / ratio passthrough
    ((46, "percent", ""), "46%"),
    ((21.7, "percent", ""), "21.7%"),
    ((1.2, "ratio", ""), "1.2x"),
    # Chinese 億 (hundred_million) must NOT be treated as English billion
    ((140, "hundred_million", "TWD"), "140 億新台幣"),
    ((8.67, "hundred_million", "CNY"), "8.67 億人民幣"),
    ((112.96, "hundred_million", "CNY"), "112.96 億人民幣"),
    ((34.25, "hundred_million", "CNY"), "34.25 億人民幣"),
    ((6174, "hundred_million", "TWD"), "6,174 億新台幣"),  # boundary: stay 億, not 兆
    # 兆 / trillion
    ((1.43, "trillion", "CNY"), "1.43 兆人民幣"),
    ((0.6174, "trillion", "TWD"), "6,174 億新台幣"),  # same string via different scale
    # 萬
    ((1.4, "ten_thousand", ""), "1.4 萬"),
    ((934.26, "ten_thousand", ""), "934.26 萬"),
    # 財報「仟元」/ in thousands
    ((99864187, "thousand", "TWD"), "998.64 億新台幣"),
    ((110660052, "thousand", "TWD"), "1106.6 億新台幣"),
    ((237553199, "thousand", "TWD"), "2375.53 億新台幣"),
    ((1000, "thousand", "USD"), "100 萬美元"),  # boundary: 1,000 thousand = 1M
    # 億 (TWD) small values
    ((6, "hundred_million", "TWD"), "6 億新台幣"),
    ((10, "hundred_million", "TWD"), "10 億新台幣"),
]


@pytest.mark.parametrize("args,expected", CASES)
def test_to_chinese_amount(args, expected):
    value, scale, currency = args
    assert to_chinese_amount(value, scale, currency) == expected
