# 投資信託 ポートフォリオ評価システム (Fund Manager)

[![CI](https://github.com/example/Fund_Manager/actions/workflows/ci.yml/badge.svg)](https://github.com/example/Fund_Manager/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.14%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type Checked with mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)
[![Coverage](https://img.shields.io/badge/coverage-100%25%20(C1)-brightgreen.svg)](https://pytest.org/)

投資信託協会が毎日公開している最新基準価額CSVを自動ダウンロード・解析し、ローカルの保有資産データ（`portfolio.csv`）と突き合わせて、各口座（タンク: 法人 / NISA / 特定 / iDeCo / DC）ごとの評価額、含み損益、およびアセットアロケーションを可視化するCLIダッシュボード＆Streamlit Webアプリケーションです。

---

## 主な機能とアーキテクチャ特性

- **基準価額CSV自動取得 & キャッシュ**:
  - 投資信託協会の最新CSV（Shift-JIS）から対象ファンドコード（8桁）の基準価額を高速抽出。
  - 通信障害・オフライン時にも稼働を継続する `./data/cache/` への自動フォールバック機構を搭載。
- **DC口座の特殊仮想積立計算**:
  - 基準日（設定値: 2025-01-01等）からの経過月数に応じた仮想積立額（20,000円/月）を口数換算し、保有口数に自動加算して評価額を算出。
- **高密度CLIダッシュボード**:
  - 全角・半角文字幅（East Asian Width）を考慮したテーブル整形。
  - テキストプログレスバー（例: `[████████░░] 45.2%`）によるタンク別アロケーション表示。
  - 3桁カンマ区切り円表記（`¥12,345,678`）および符号付き損益率表示。
- **最新Streamlit Web GUI**:
  - 3ゾーン構成（Header / Sidebar / Main Workspace）、ワイドレイアウト。
  - Altairによるアセットアロケーション・ドーナツチャート。
  - `@st.cache_data` によるデータ取得最適化。
- **データ隔離 & 整合性検証バックアップ (`backup_manager.py`)**:
  - すべての動的・永続化データを `./data` 配下に完全隔離。
  - 標準ライブラリのみで構成された一時ディレクトリZIP圧縮および `testzip()` 破損検知付きバックアップ機能を装備。

---

## ディレクトリ構成

```text
e:\Python\Fund_Manager/
├── .gitattributes             # 改行コード制御 (CRLF/LF)
├── .github/
│   └── workflows/
│       └── ci.yml             # GitHub Actions CIパイプライン
├── pyproject.toml             # 依存関係・静的解析設定
├── run.bat                    # Windows用ワンクリック自動起動スクリプト (CRLF)
├── run.command                # Mac/Linux用ランチャースクリプト (LF)
├── backup_manager.py          # データ保護・整合性検証バックアップ
├── cli.py                     # CLIダッシュボード
├── app.py                     # Streamlit Web GUI
├── data/                      # 永続化データディレクトリ (データ隔離)
│   ├── portfolio.csv          # 保有資産データ (UTF-8)
│   ├── backup_config.json     # バックアップ先設定
│   └── cache/                 # 基準価額キャッシュ
├── src/                       # コアドメインロジック
│   ├── models.py              # Pydantic v2 スキーマ
│   ├── nav_fetcher.py         # 基準価額CSV取得・解析
│   ├── portfolio_loader.py    # portfolio.csv 読込・バリデーション
│   ├── calculator.py          # 評価額・DC積立計算エンジン
│   └── formatter.py           # CLIテーブル・バー描画
└── tests/                     # C1カバレッジ100%テストスイート
```

---

## クイックスタート

### 1. ワンクリック起動 (推奨)
Pythonのみがインストールされている環境で、依存関係の解決から起動までを完全自動化します。

- **Windows**: `run.bat` をダブルクリック
- **Mac / Linux**: `./run.command` を実行

### 2. 手動セットアップ (uv または pip)

```bash
# 依存関係のインストール
uv sync
# または pip install -e ".[dev]"

# CLIダッシュボードの実行
uv run python cli.py

# Streamlit Web GUIの起動
uv run streamlit run app.py
```

---

## 入力データ仕様 (`data/portfolio.csv`)

UTF-8エンコーディング、ヘッダ行必須。初回起動時に自動生成されます。

```csv
account,code,name,units,cost_basis
法人,03311181,eMAXIS Slim 全世界株式(OL),5000000.0,7500000
NISA,03314187,eMAXIS Slim 米国株式(S&P500),3000000.0,6000000
特定,03312184,eMAXIS Slim 先進国株式,2000000.0,4500000
iDeCo,03311181,eMAXIS Slim 全世界株式(OL),1500000.0,0
DC,03314187,eMAXIS Slim 米国株式(S&P500),1000000.0,
```

- **account**: 口座種別（法人 / NISA / 特定 / iDeCo / DC など）
- **code**: 投信協会の8桁ファンドコード（例: `03311181`）
- **name**: 銘柄略称
- **units**: 保有口数（正の浮動小数点数）
- **cost_basis**: 取得簿価合計金額（整数。iDeCoやDCで簿価管理不要の場合は `0` または空欄）

---

## 開発・検証コマンド

```bash
# 静的解析・フォーマット検証
uv run ruff check .
uv run ruff format --check .

# 厳格型チェック
uv run mypy src tests

# カバレッジ測定付きテスト実行 (C1 Branch Coverage 100%)
uv run pytest
```
