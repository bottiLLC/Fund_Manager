![CI](https://img.shields.io/badge/CI-passed-green)
![Python](https://img.shields.io/badge/Python-3.13-blue.svg)
![Streamlit](https://img.shields.io/badge/Streamlit-1.42.0-FF4B4B.svg)
![License](https://img.shields.io/badge/License-Private-red.svg)

# 投資信託 ポートフォリオ評価システム (Fund Manager)

## Overview
投資信託協会が公表する最新基準価額データを自動取得・解析し、ローカル保有資産（`portfolio.csv`）と照合して口座（タンク）ごとの時価評価額・含み損益・アセットアロケーションを算出・可視化する資産管理ユーティリティです。

## Quick Start (TL;DR)
```bash
uv sync
uv run python cli.py
uv run streamlit run app.py
```

## Architecture & Features
- **基準価額CSV自動取得 & 耐障害キャッシュ**: 投資信託協会の最新公表CSV（Shift-JIS）から対象8桁ファンドコードの基準価額を自動抽出・ローカルキャッシュ（`./data/cache/`）へ隔離保存。
- **口座（タンク）別アロケーション評価**: 法人・NISA・特定・iDeCo・DC口座ごとの評価額、構成比率、含み損益をCLIプログレスバーおよびAltairドーナツチャートで即時可視化。
- **DC特殊仮想積立計算**: 基準日（デフォルト: 2025-01-01）からの経過月数に基づく月次仮想積立額（20,000円/月）を口数換算し、実質保有資産へ自動加算。
- **データ隔離 & 整合性検証バックアップ**: 永続化データをすべて `./data` 配下に厳格隔離し、`backup_manager.py` による一時ディレクトリZIP圧縮および `testzip()` 破損検知を実施。

## Environment Variables
| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `BACKUP_DIR` | `./backups` | データ保護ZIPアーカイブの退避先ディレクトリパス |

## Limits & Known Trade-offs
- **基準価額公表タイミングの制約**: 投資信託協会の公表CSVは日次更新（夜間）のため、日中のリアルタイム約定基準価額の即時反映には非対応。
- **対象銘柄の制約**: 投信協会コード体系（8桁）に準拠した投資信託のみを対象とし、個別国内株式・外国株式・ETFの直接集計は対象外。
- **将来課題 (TODO)**: 複数DCファンド按分積立対応、為替レート自動連動、および月次推移ヒストリカルグラフの追加。

---

Copyright (c) LLC Bocchi. All rights reserved.
