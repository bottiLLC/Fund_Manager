![CI](https://img.shields.io/badge/CI-passed-green)
![Python](https://img.shields.io/badge/Python-3.14%20%7C%203.13-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.66.0-FF4B4B.svg)
![License](https://img.shields.io/badge/License-MIT-blue.svg)

# 投資信託 ポートフォリオ評価システム (Fund Manager)

## Overview
投資信託協会の「投信総合検索ライブラリー」直結エンドポイントから最新基準価額データを自動取得・解析し、ローカル保有資産（`portfolio.csv`）と照合して口座（タンク）ごとの時価評価額・含み損益・アセットアロケーションを算出・可視化する資産管理ユーティリティです。

## Quick Start (TL;DR)
```bash
uv sync
uv run python cli.py
uv run streamlit run app.py
```

## Architecture & Features
- **投信総合検索ライブラリー直結CSV自動取得 & 耐障害キャッシュ**: 投資信託協会の全銘柄共通直結エンドポイント（Shift-JIS）より対象銘柄の最新基準価額を並列取得。個別CSV/JSONメタキャッシュ（`./data/cache/`）および内蔵フォールバック辞書によりオフライン時も安定動作。
- **SBI証券ポートフォリオCSV直接インポート & 名寄せ学習**: SBI証券からダウンロードしたCSV（Shift-JIS/CP932/UTF-8）の階層構造を自動パース。銘柄名から投信協会コード（8桁）・ISINを逆引き補完し、未特定コードの手動学習（`./data/custom_fund_aliases.json`）および事前バックアップ連動マージ（UPSERT/置換/新規追加）を提供（CLI `--import-sbi` にも対応）。
- **保有資産マスター管理 & 透過的データ正規化**: Streamlit（v1.66.0対応）のタブUI（評価 / マスター管理）および `st.data_editor` による対話的資産追加・編集・即時再計算、原子的ファイル置換（`save_portfolio_csv`）を提供。日英カラム名の透過的バリデーションを保証。
- **口座（タンク）別アロケーション評価**: 法人・NISA・特定・iDeCo・DC口座ごとの時価評価額、構成比率、含み損益をCLIプログレスバーおよびAltairドーナツチャートで即時可視化。登録口数に基づく直接評価により高い簡明性を担保。
- **時系列履歴データベース永続化 (SQLite) & 増減可視化**: `./data/fund_history.db` への日次スナップショット自動記録、ダッシュボードでの全ファンド積み上げ式総資産変化棒グラフ、および「法人/個人」「格納口座」「協会コード」「ISIN」完全一致によるファンド別推移分析タブ（取得簿価・口数・現在値のAltair時系列推移チャートおよび明細ダウンロード）を提供。
- **データ隔離 & 整合性検証バックアップ**: 永続化データをすべて `./data` 配下に厳格隔離し、`backup_manager.py` による一時ディレクトリZIP圧縮および `testzip()` 破損検知を実施。

## Environment Variables
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `BACKUP_DIR` | `./backups` | データ保護ZIPアーカイブの退避先ディレクトリパス |

## Limits & Known Trade-offs
- **基準価額公表タイミングの制約**: 投資信託協会の公表CSVは日次更新（夜間）のため、日中のリアルタイム約定基準価額の即時反映には非対応。
- **対象銘柄の制約**: 投信協会コード体系（8桁）およびISINコード（12桁）に準拠した投資信託のみを対象とし、個別国内株式・外国株式・ETFの直接集計は対象外。


---

Licensed under the [MIT License](LICENSE).  
Copyright (c) 2026 LLC Bocchi. All rights reserved.
