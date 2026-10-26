"""Application Sidebar zone rendering."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from backup_manager import get_backup_dir, run_backup, set_backup_dir


def render_app_sidebar(project_root: Path) -> None:
    """サイドバーゾーン（グローバル設定、キャッシュ管理、バックアップ）を描画する。

    Args:
        project_root: プロジェクトルートの絶対パス。
    """
    with st.sidebar:
        st.header("⚙️ 設定 & 管理")

        force_refresh = st.button(
            "🔄 基準価額データを再取得",
            icon=":material/refresh:",
            type="secondary",
            width="stretch",
            help=(
                "投信協会のWebキャッシュをクリアし、最新の基準価額を再フェッチします。"
                "（※当日の最新値は平日19:00〜21:30頃に投信協会側で更新されます）"
            ),
        )
        if force_refresh:
            st.cache_data.clear()
            st.session_state["refresh_pending"] = True
            st.rerun()

        if "refresh_feedback" in st.session_state:
            fb_status, fb_msg = st.session_state.pop("refresh_feedback")
            if fb_status == "success":
                st.success(fb_msg)
            elif fb_status == "warning":
                st.warning(fb_msg)
            else:
                st.error(fb_msg)
        elif "cache_cleared_msg" in st.session_state:
            st.success(str(st.session_state.pop("cache_cleared_msg")))

        uploaded_nav_csv = st.file_uploader(
            "最新基準価額CSVを手動登録",
            type=["csv"],
            help="最新の基準価額CSVをアップロードして ./data/cache/latest_nav.csv を更新します。",
        )
        if uploaded_nav_csv is not None:
            save_target = project_root / "data" / "cache" / "latest_nav.csv"
            save_target.parent.mkdir(parents=True, exist_ok=True)
            save_target.write_bytes(uploaded_nav_csv.getvalue())
            st.cache_data.clear()
            st.session_state["cache_cleared_msg"] = "最新基準価額CSVをキャッシュに保存しました。"
            st.rerun()

        st.divider()

        # データ保護・バックアップ設定フォーム
        with st.container(border=True):
            st.subheader("データ保護・バックアップ")
            current_dir = str(get_backup_dir())

            with st.form("backup_settings_form", clear_on_submit=False):
                new_dir = st.text_input(
                    "保存先フォルダ",
                    value=current_dir,
                    help="バックアップZipファイルの出力先ディレクトリパスを指定します。",
                )
                submit_dir_change = st.form_submit_button(
                    "保存先パスを更新",
                    icon=":material/save:",
                    type="secondary",
                    width="stretch",
                )

            if submit_dir_change and new_dir != current_dir:
                save_res = set_backup_dir(new_dir)
                if save_res["success"]:
                    st.success(str(save_res["message"]))
                    st.rerun()
                else:
                    st.error(
                        f"【エラー】保存先更新失敗: {save_res['message']}\n【対処方法】有効な書き込み権限のあるパスを指定してください。"
                    )

            if st.button(
                "今すぐバックアップを実行",
                icon=":material/backup:",
                type="secondary",
                width="stretch",
            ):
                with st.spinner("圧縮・整合性検証中..."):
                    res = run_backup(app_name="fund_manager")
                if res["success"]:
                    st.success(str(res["message"]))
                    st.caption(f"完了日時: {res.get('timestamp')}")
                    st.caption(f"保存先: {res.get('destination')}")
                else:
                    st.error(
                        f"【エラー】バックアップ失敗: {res.get('message')}\n【対処方法】保存先フォルダの空き容量および書き込み権限を確認してください。"
                    )

        st.divider()
        st.caption("🔒 Persistent Data Isolation: ./data")
