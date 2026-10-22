"""Application Header zone rendering."""

from __future__ import annotations

import streamlit as st


def render_app_header(version: str = "v0.3.0", python_ver: str = "3.14+") -> None:
    """アプリ上部のヘッダーゾーンを描画する。

    タイトル、1行の利用目的、およびバージョン・実行環境メタデータを表示する。

    Args:
        version: アプリケーションバージョン文字列。
        python_ver: 推奨Pythonランタイムバージョン。
    """
    st.title("📈 投資信託 ポートフォリオ評価ダッシュボード")
    st.caption(
        "投資信託協会の最新基準価額とローカル資産を突き合わせ、"
        "口座（タンク）ごとの資産評価とアロケーションを可視化します。"
    )
    st.caption(f"🔖 Fund Manager {version} | 🐍 Python {python_ver} | 🛡️ MIT License")
