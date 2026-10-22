"""SBI証券ポートフォリオCSV解析・名寄せモジュールの網羅的単体テスト。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.models import PortfolioItem
from src.sbi_importer import (
    ImportCandidate,
    MergeMode,
    SbiRawRecord,
    decode_csv_bytes,
    extract_account_name,
    load_custom_aliases,
    merge_candidates_into_portfolio,
    normalize_string_key,
    parse_numeric_cell,
    parse_sbi_portfolio_csv,
    resolve_candidates,
    save_custom_aliases,
)

# ユーザー提供の実データ（解読されたUTF-8文字列）
REAL_SBI_CSV_UTF8 = """\
"ポートフォリオ一覧",
"一括表示",
"PTS夜間取引非表示",
"保有件数：9件",
"選択範囲：1-9件",
"ページ：1",
"投資信託（金額/NISA口座（成長投資枠））",
"ファンド名","買付日","数量","取得単価","現在値","前日比","前日比（％）","損益","損益（％）","評価額",
"ｅＭＡＸＩＳ Ｓｌｉｍ 米国株式（Ｓ＆Ｐ５００）","----/--/--",1942,28420,44943,+369,+0.83,+3208.76,+58.14,8727.93,
"ｅＭＡＸＩＳ Ｓｌｉｍ 先進国株式（含む日本）＜オール先進国＞","----/--/--",3934730,11810,14137,+65,+0.46,+915611.67,+19.70,5562527.8,
"投資信託(金額/NISA口座(成長投資枠))合計",
"評価額","含み損益","含み損益（％）","前日比","前日比（％）",
5571255.73,+918820.43,+19.75,+25647.4,+0.46,
"投資信託（金額/NISA口座（つみたて投資枠））",
"ファンド名","買付日","数量","取得単価","現在値","前日比","前日比（％）","損益","損益（％）","評価額",
"ｅＭＡＸＩＳ Ｓｌｉｍ 先進国株式（含む日本）＜オール先進国＞","----/--/--",1732929,11542,14137,+65,+0.46,+449695.07,+22.48,2449841.72,
"ｅＭＡＸＩＳ Ｓｌｉｍ 米国株式（Ｓ＆Ｐ５００）","----/--/--",308619,29163,44943,+369,+0.83,+487000.78,+54.11,1387026.37,
"投資信託(金額/NISA口座(つみたて投資枠))合計",
"評価額","含み損益","含み損益（％）","前日比","前日比（％）",
3836868.09,+936695.85,+32.30,+22652.08,+0.59,
"投資信託（金額/旧つみたてNISA口座）",
"ファンド名","買付日","数量","取得単価","現在値","前日比","前日比（％）","損益","損益（％）","評価額",
"ニッセイ外国株式インデックスファンド＜購入・換金手数料なし＞","----/--/--",897,18050,59920,+347,+0.58,+3755.73,+231.97,5374.82,
"ｅＭＡＸＩＳ Ｓｌｉｍ 全世界株式（オール・カントリー）","----/--/--",34376,19394,37859,+176,+0.47,+63475.28,+95.21,130144.09,
"ＳＢＩ・Ｖ・全世界株式インデックス・ファンド","----/--/--",359885,11115,22683,+135,+0.60,+416314.96,+104.08,816327.14,
"ＳＢＩ・Ｖ・Ｓ＆Ｐ５００インデックス・ファンド","----/--/--",272067,17006,41070,+344,+0.84,+654702.02,+141.50,1117379.16,
"ｅＭＡＸＩＳ Ｓｌｉｍ 先進国株式インデックス（除く日本）","----/--/--",342199,14817,45368,+262,+0.58,+1045452.16,+206.19,1552488.42,
"投資信託(金額/旧つみたてNISA口座)合計",
"評価額","含み損益","含み損益（％）","前日比","前日比（％）",
3621713.66,+2183700.18,+151.86,+23819.31,+0.66,
"総合計",
"評価額","含み損益","含み損益（％）","前日比","前日比（％）",
13029837.49,+4039216.47,+44.93,+72118.79,+0.56
"""


def test_normalize_string_key() -> None:
    k1 = normalize_string_key("ｅＭＡＸＩＳ Ｓｌｉｍ 米国株式（Ｓ＆Ｐ５００）")
    k2 = normalize_string_key("eMAXIS Slim 米国株式(S&P500)")
    k3 = normalize_string_key("eMAXISSlim米国株式(S&P500)")
    assert k1 == "emaxisslim米国株式s&p500"
    assert k1 == k2 == k3


def test_decode_csv_bytes_encodings() -> None:
    text = "投資信託,テスト"
    assert decode_csv_bytes(text.encode("cp932")) == text
    assert decode_csv_bytes(text.encode("shift_jis")) == text
    assert decode_csv_bytes(text.encode("utf-8-sig")) == text
    assert decode_csv_bytes(text.encode("utf-8")) == text


def test_decode_csv_bytes_invalid_raises_value_error() -> None:
    invalid_bytes = b"\x81\x00"
    with pytest.raises(ValueError, match="CSVファイルの文字コードを判別できませんでした"):
        decode_csv_bytes(invalid_bytes)


def test_parse_numeric_cell() -> None:
    assert parse_numeric_cell("+1,234.56") == 1234.56
    assert parse_numeric_cell("-500.0") == -500.0
    assert parse_numeric_cell("----/--/--") == 0.0
    assert parse_numeric_cell("--") == 0.0
    assert parse_numeric_cell("") == 0.0
    assert parse_numeric_cell("invalid_num") == 0.0


def test_extract_account_name() -> None:
    assert (
        extract_account_name("投資信託（金額/NISA口座（成長投資枠））") == "NISA預り（成長投資枠）"
    )
    assert (
        extract_account_name("投資信託(金額/NISA口座(つみたて投資枠))")
        == "NISA預り（つみたて投資枠）"
    )
    assert (
        extract_account_name("投資信託（金額/旧つみたてNISA口座）")
        == "NISA預り（旧つみたてNISA預り）"
    )
    assert extract_account_name("投資信託（金額/特定口座）") == "特定預り"
    assert extract_account_name("投資信託（金額/一般口座）") == "一般預り"
    assert (
        extract_account_name("投資信託（金額/NISA預り（つみたて投資枠））")
        == "NISA預り（つみたて投資枠）"
    )
    assert (
        extract_account_name("投資信託（金額/NISA預り（成長投資枠））") == "NISA預り（成長投資枠）"
    )
    assert extract_account_name("投資信託（金額/一般預り）") == "一般預り"
    assert extract_account_name("投資信託（金額/未知の口座）") == "未知の口座"
    assert extract_account_name('"特定口座"') == "特定預り"


def test_parse_sbi_portfolio_csv_real_data() -> None:
    records = parse_sbi_portfolio_csv(REAL_SBI_CSV_UTF8)
    assert len(records) == 9
    first = records[0]
    assert first.fund_name == "ｅＭＡＸＩＳ Ｓｌｉｍ 米国株式（Ｓ＆Ｐ５００）"
    assert first.quantity == 1942.0
    assert first.acquisition_price == 28420.0
    assert first.current_price == 44943.0
    assert first.calculated_cost_basis == int(round(1942.0 * 28420.0 / 10000.0))

    last = records[-1]
    assert last.fund_name == "ｅＭＡＸＩＳ Ｓｌｉｍ 先進国株式インデックス（除く日本）"
    assert last.quantity == 342199.0
    assert last.acquisition_price == 14817.0


def test_parse_sbi_portfolio_csv_edge_cases() -> None:
    csv_content = """\
"ポートフォリオ一覧",
"合　計",
"合計",
"投資信託（金額/NISA口座（成長投資枠））",
"ファンド名","買付日","数量","取得単価","現在値","損益","評価額",
"売却済み銘柄","----/--/--",0,10000,12000,0,0,
"マイナス口数","----/--/--",-10,10000,12000,0,0,
"",
"有効銘柄A","----/--/--",1000,10000,12000,200,1200,
"投資信託小計",
"小計行",
"ファンド名なし",1000,
"投資信託（金額/特定口座）",
"銘柄名列のみ","数量列なし",
100,200,
"投資信託（金額/一般口座）",
"ファンド名","数量",
"一般銘柄",500,
"""
    records = parse_sbi_portfolio_csv(csv_content)
    assert len(records) == 2
    assert records[0].fund_name == "有効銘柄A"
    assert records[0].quantity == 1000.0
    assert records[1].fund_name == "一般銘柄"
    assert records[1].quantity == 500.0
    assert records[1].acquisition_price == 0.0


def test_sbi_raw_record_calculated_cost_basis() -> None:
    # 1. 取得単価が正値の場合: 数量 × 取得単価 ÷ 10,000
    rec_normal = SbiRawRecord(
        raw_account_section="投資信託（金額/特定口座）",
        fund_name="通常ファンド",
        quantity=1942.0,
        acquisition_price=28420.0,
        valuation=8728.0,
        profit_loss=3209.0,
    )
    assert rec_normal.calculated_cost_basis == 5519

    # 2. 取得単価が0で評価額と損益が存在する場合: 評価額 - 損益 (フォールバック)
    rec_fallback = SbiRawRecord(
        raw_account_section="投資信託（金額/特定口座）",
        fund_name="移管ファンド",
        quantity=1000.0,
        acquisition_price=0.0,
        valuation=15000.0,
        profit_loss=3000.0,
    )
    assert rec_fallback.calculated_cost_basis == 12000

    # 3. 取得単価0かつ評価額0の場合: 0
    rec_zero = SbiRawRecord(
        raw_account_section="投資信託（金額/特定口座）",
        fund_name="残高ゼロファンド",
        quantity=100.0,
        acquisition_price=0.0,
        valuation=0.0,
        profit_loss=0.0,
    )
    assert rec_zero.calculated_cost_basis == 0


def test_load_and_save_custom_aliases(tmp_path: Path) -> None:
    alias_file = tmp_path / "custom_aliases.json"
    assert load_custom_aliases(alias_file) == {}

    data = {
        "テストファンド": ("03311187", "JP90C000GKC6"),
        "別名ファンド": ("0331418A", "JP90C000H1T1"),
    }

    save_custom_aliases(alias_file, data)
    loaded = load_custom_aliases(alias_file)
    assert loaded == data

    # 不正データ（リスト要素不足、dict外、JSON構文エラー）
    alias_file.write_text(
        json.dumps({"invalid_entry": ["123"], "not_a_list": "str"}),
        encoding="utf-8",
    )
    assert load_custom_aliases(alias_file) == {}

    alias_file.write_text("corrupted json", encoding="utf-8")
    assert load_custom_aliases(alias_file) == {}

    alias_file.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_custom_aliases(alias_file) == {}

    # OSError シミュレーション
    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        assert load_custom_aliases(alias_file) == {}


def test_resolve_candidates_cascade() -> None:
    records = parse_sbi_portfolio_csv(REAL_SBI_CSV_UTF8)
    existing_items = [
        PortfolioItem(
            account="旧つみたてNISA",
            code="2931113C",
            isin="JP90C0009VE0",
            name="ニッセイ外国株式インデックスファンド＜購入・換金手数料なし＞",
            units=897.0,
            cost_basis=1619,
        ),
        PortfolioItem(
            account="特定",
            code="03311187",
            isin="JP90C000GKC6",
            name="",  # name が空のケース
            units=100.0,
            cost_basis=1000,
        ),
    ]
    custom_aliases = {normalize_string_key("未知のカスタムファンド"): ("99999999", "JP9999999999")}

    candidates = resolve_candidates(
        records=records,
        existing_items=existing_items,
        custom_aliases=custom_aliases,
        account_override_map={"NISA預り（成長投資枠）": "NISA"},
        default_holder="個人",
        holder_override_map={"NISA預り（成長投資枠）": "法人"},
    )

    assert len(candidates) == 9
    for c in candidates:
        assert c.is_resolved is True
        assert len(c.resolved_code) == 8
        assert len(c.resolved_isin) == 12

    assert candidates[0].target_account == "NISA"
    assert candidates[0].holder == "法人"
    assert candidates[2].target_account == "NISA預り（つみたて投資枠）"
    assert candidates[2].holder == "個人"


def test_resolve_candidates_partial_match_and_unresolved() -> None:
    # 1. 部分一致（例: 「ニッセイ外国株式」短縮形）
    partial_record = SbiRawRecord(
        raw_account_section="投資信託（金額/特定口座）",
        fund_name="ニッセイ外国株式",
        quantity=100.0,
        acquisition_price=20000.0,
    )
    # 2. カスタム辞書直接マッチ
    custom_record = SbiRawRecord(
        raw_account_section="投資信託（金額/特定口座）",
        fund_name="独自登録ファンドXYZ",
        quantity=200.0,
        acquisition_price=10000.0,
    )
    # 3. 完全未解決
    unknown_record = SbiRawRecord(
        raw_account_section="投資信託（金額/特定口座）",
        fund_name="完全未登録の架空ファンド999",
        quantity=500.0,
        acquisition_price=10000.0,
    )

    custom_aliases = {normalize_string_key("独自登録ファンドXYZ"): ("88888888", "JP8888888888")}

    candidates = resolve_candidates(
        records=[partial_record, custom_record, unknown_record],
        existing_items=[],
        custom_aliases=custom_aliases,
    )

    assert len(candidates) == 3
    # 1: 部分一致で解決
    assert candidates[0].is_resolved is True
    assert candidates[0].resolved_code == "2931113C"
    assert candidates[0].resolved_isin == "JP90C0009VE0"

    # 2: カスタム辞書で解決
    assert candidates[1].is_resolved is True
    assert candidates[1].resolved_code == "88888888"
    assert candidates[1].resolved_isin == "JP8888888888"

    # 3: 未解決
    assert candidates[2].is_resolved is False
    assert candidates[2].resolved_code == ""
    assert candidates[2].validation_error == "投信協会コードが未解決です"


def test_merge_candidates_into_portfolio_append() -> None:
    # 既存: 個人口座で 03311187 (S&P500) を保有
    existing = [
        PortfolioItem(
            holder="個人",
            account="NISA預り（成長投資枠）",
            code="03311187",
            isin="JP90C000GKC6",
            name="S&P500個人",
            units=100.0,
            cost_basis=2000,
        )
    ]
    # 追加候補: 法人口座で同一の 03311187 (S&P500) を保有
    candidate_corp = ImportCandidate(
        source_record=SbiRawRecord(
            raw_account_section="法人",
            fund_name="S&P500法人",
            quantity=500.0,
            acquisition_price=30000.0,
        ),
        target_account="一般預り",
        holder="法人",
        resolved_code="03311187",
        resolved_isin="JP90C000GKC6",
        is_resolved=True,
    )
    # 追加候補: 同一口座で別枠・別行として購入された分
    candidate_nisa_add = ImportCandidate(
        source_record=SbiRawRecord(
            raw_account_section="NISA",
            fund_name="S&P500個人追加分",
            quantity=50.0,
            acquisition_price=31000.0,
        ),
        target_account="NISA預り（成長投資枠）",
        holder="個人",
        resolved_code="03311187",
        resolved_isin="JP90C000GKC6",
        is_resolved=True,
    )

    merged = merge_candidates_into_portfolio(
        existing, [candidate_corp, candidate_nisa_add], merge_mode=MergeMode.APPEND
    )

    # 同一銘柄であってもまとめず、3行すべてが独立して保持される
    assert len(merged) == 3
    assert (
        merged[0].holder == "個人"
        and merged[0].account == "NISA預り（成長投資枠）"
        and merged[0].units == 100.0
    )
    assert merged[0].cost_basis == 2000
    assert (
        merged[1].holder == "法人" and merged[1].account == "一般預り" and merged[1].units == 500.0
    )
    assert merged[1].cost_basis == 1500  # 500 * 30000 / 10000
    assert (
        merged[2].holder == "個人"
        and merged[2].account == "NISA預り（成長投資枠）"
        and merged[2].units == 50.0
    )
    assert merged[2].cost_basis == 155  # 50 * 31000 / 10000


def test_merge_candidates_into_portfolio_replace_all() -> None:
    existing = [
        PortfolioItem(
            holder="個人",
            account="NISA預り（成長投資枠）",
            code="03311187",
            isin="JP90C000GKC6",
            name="旧S&P500",
            units=100.0,
            cost_basis=2000,
        )
    ]
    candidate = ImportCandidate(
        source_record=SbiRawRecord(
            raw_account_section="法人",
            fund_name="新規先進国",
            quantity=300.0,
            acquisition_price=15000.0,
        ),
        target_account="一般預り",
        holder="法人",
        resolved_code="0331124A",
        resolved_isin="JP90C000R9Z9",
        is_resolved=True,
    )

    merged = merge_candidates_into_portfolio(
        existing, [candidate], merge_mode=MergeMode.REPLACE_ALL
    )

    assert len(merged) == 1
    assert merged[0].holder == "法人"
    assert merged[0].account == "一般預り"
    assert merged[0].code == "0331124A"
    assert merged[0].cost_basis == 450  # 300 * 15000 / 10000


def test_merge_candidates_unresolved_raises_value_error() -> None:
    candidate_unresolved = ImportCandidate(
        source_record=SbiRawRecord(
            raw_account_section="NISA",
            fund_name="未解決ファンド",
            quantity=100.0,
            acquisition_price=10000.0,
        ),
        target_account="NISA",
        resolved_code="",
        is_resolved=False,
    )

    with pytest.raises(ValueError, match="未解決の銘柄が含まれています"):
        merge_candidates_into_portfolio([], [candidate_unresolved])


def test_parse_sbi_portfolio_csv_missing_indices_and_cleanup(tmp_path: Path) -> None:
    # 1. 空行、列不足行、合計名ファンド、ヘッダインデックス欠落行
    csv_text = """
"投資信託（金額/特定口座）"
"ファンド名","取得単価"
"銘柄X",10000

"投資信託（金額/特定口座）"
"ファンド名","数量"
"小計",100
,300
"短行"
"正常銘柄",1000
"合計",200
"""
    records = parse_sbi_portfolio_csv(csv_text)
    assert len(records) == 1
    assert records[0].fund_name == "正常銘柄"

    # 2. save_custom_aliases の例外時クリーンアップ (finally unlink)
    alias_file = tmp_path / "sub" / "aliases.json"
    with (
        patch("tempfile.mkstemp", return_value=(99999, str(tmp_path / "dummy_tmp"))),
        patch("builtins.open", side_effect=OSError("Write failure")),
        pytest.raises(OSError, match="Write failure"),
    ):
        (tmp_path / "dummy_tmp").write_text("dummy", encoding="utf-8")
        save_custom_aliases(alias_file, {"A": ("03311187", "JP90C000GKC6")})
    assert not (tmp_path / "dummy_tmp").exists()

    # 3. resolve_candidates で PRESET_FUNDS の name が空の場合
    with patch.dict(
        "src.sbi_importer.PRESET_FUNDS",
        {"99999999": {"name": "", "isin": "JP9999999999"}},
        clear=False,
    ):
        cand = resolve_candidates(
            records=[
                SbiRawRecord(
                    raw_account_section="特定",
                    fund_name="無関係ファンド",
                    quantity=100.0,
                    acquisition_price=10000.0,
                )
            ],
            existing_items=[],
            custom_aliases={},
        )
        assert not cand[0].is_resolved
