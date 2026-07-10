#!/usr/bin/env python3
"""README の 2 つの欄を自動生成する。

1. 「📱 リリース済みアプリ」: App Store の開発者ID（APPSTORE_ARTIST_ID）から
   リリース済みアプリを全件自動取得し、アイコン付きで表示する。
2. 「🛠 直近活動のあるプロジェクト」: 自分が owner の非fork・非archived
   リポジトリ（public / private）を push 日時の降順で取得し上位 N 件を出す。
   private はアクセスできないためリンクを張らず、🔒 付きで名前と説明を載せる。

private を読むには `repo` スコープの PAT が必要。GitHub Actions 上では
`gh` CLI が環境変数 GH_TOKEN の PAT で認証する前提（既定の GITHUB_TOKEN では
profile リポしか見えず private を列挙できない）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER = "shsw228"
MAX_ITEMS = 5

# profile リポジトリ自身 / ブログ関連 / 旧ブログの残骸 / 公開したくない private を除外する
EXCLUDE = {
    "shsw228",
    "hume.com",
    "hume-press",
    "blog",
    "blog-articles",
    "shsw.log",
    "Curriculum-Vitae",  # 職務経歴書/履歴書
}

# App Store の開発者ID（artistId）。ここから全アプリを自動取得する。
# 取得: https://itunes.apple.com/lookup?id=<appId>&country=us の artistId フィールド。
APPSTORE_ARTIST_ID = 1458012620

APPSTORE_BADGE = (
    "https://img.shields.io/badge/Download_on_the-App_Store-0D96F6"
    "?style=flat&logo=apple&logoColor=white"
)

RECENT_START = "<!-- RECENT:START -->"
RECENT_END = "<!-- RECENT:END -->"
APPS_START = "<!-- APPS:START -->"
APPS_END = "<!-- APPS:END -->"

README = Path(__file__).resolve().parent.parent / "README.md"


def fetch_repos() -> list[dict]:
    out = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            "--jq",
            ".[]",
            "/user/repos?affiliation=owner&visibility=all&sort=pushed&per_page=100",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    # --jq '.[]' は各リポジトリを 1 行 1 JSON オブジェクトで出力する
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def checked_caption() -> str:
    """セクション末尾に出す最終チェック日（JST）のバッジ。"""
    jst = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
    # shields の記法: "-" は "--"、空白は "_"、括弧は %28/%29 にエスケープ
    msg = (
        f"{jst} (JST)"
        .replace("-", "--")
        .replace(" ", "_")
        .replace("(", "%28")
        .replace(")", "%29")
    )
    url = f"https://img.shields.io/badge/Checked-{msg}-informational?style=flat"
    return f"![Checked]({url})"


def _lookup(params: str) -> list[dict]:
    api = f"https://itunes.apple.com/lookup?{params}"
    try:
        with urllib.request.urlopen(api, timeout=15) as resp:
            return json.load(resp).get("results") or []
    except Exception as e:  # noqa: BLE001 - 失敗時は空で返す
        print(f"warn: itunes lookup failed ({params}): {e}", file=sys.stderr)
        return []


def fetch_artist_apps(artist_id: int) -> list[dict]:
    """開発者ID（artistId）からリリース済みアプリを全件取得する。
    英語(us)のメタデータを優先し、us ストアに無いアプリは jp から補完する。"""
    apps: dict[int, dict] = {}
    # us を先に入れて英語メタデータを優先、次に jp で us に無いアプリを補完
    for country in ("us", "jp"):
        for r in _lookup(
            f"id={artist_id}&entity=software&country={country}&limit=200"
        ):
            if r.get("wrapperType") == "software" and r.get("trackId"):
                apps.setdefault(r["trackId"], r)
    # 新しいリリース順（バージョン更新日の降順）に並べる
    return sorted(
        apps.values(),
        key=lambda r: r.get("currentVersionReleaseDate") or r.get("releaseDate") or "",
        reverse=True,
    )


def build_apps() -> str:
    apps = fetch_artist_apps(APPSTORE_ARTIST_ID)
    if not apps:
        return f"_(coming soon)_\n\n{checked_caption()}"
    rows = []
    for r in apps:
        url = r.get("trackViewUrl") or ""
        name = r.get("trackName") or ""
        art = r.get("artworkUrl100") or ""
        support = (r.get("sellerUrl") or "").strip()  # 開発者/サポートページ
        desc = (r.get("description") or "").strip().splitlines()
        tagline = desc[0].strip() if desc else ""

        # アイコン・アプリ名はサポート/サイトへ（無ければ App Store にフォールバック）
        site = support or url
        icon = (
            f'<a href="{site}"><img src="{art}" width="60" height="60" alt="{name}"></a>'
            if art
            else ""
        )
        detail = f'<b><a href="{site}">{name}</a></b>'
        if tagline:
            detail += f"<br><sub>{tagline}</sub>"
        # ダウンロードは常に App Store バッジ
        badge = f'<a href="{url}"><img src="{APPSTORE_BADGE}" alt="Download on the App Store"></a>'

        rows.append(
            "  <tr>\n"
            f'    <td width="72" align="center">{icon}</td>\n'
            f"    <td>{detail}</td>\n"
            f'    <td align="right">{badge}</td>\n'
            "  </tr>"
        )
    return "<table>\n" + "\n".join(rows) + "\n</table>\n\n" + checked_caption()


def format_row(repo: dict) -> str:
    """直近活動プロジェクト 1 件を表の 1 行（<tr>）にする。"""
    name = repo["name"]
    desc = (repo.get("description") or "").strip()
    lang = repo.get("language")
    pushed = (repo.get("pushed_at") or "")[:7]  # YYYY-MM
    meta = " · ".join(p for p in (lang, pushed) if p)

    # 名前セル: private はリンクなし🔒、public はリポジトリへリンク。下に言語/更新月
    if repo.get("private"):
        title = f"🔒 <b>{name}</b>"
    else:
        title = f'<a href="{repo["html_url"]}"><b>{name}</b></a>'
    if meta:
        title += f"<br><sub>{meta}</sub>"

    # リンクセル: homepage（About の Website）があれば公開ページへ
    home = (repo.get("homepage") or "").strip()
    link = f'<a href="{home}">🌐 Website</a>' if home else ""

    return (
        "  <tr>\n"
        f"    <td>{title}</td>\n"
        f"    <td>{desc}</td>\n"
        f"    <td>{link}</td>\n"
        "  </tr>"
    )


def build_recent(repos: list[dict]) -> str:
    picks = [
        r
        for r in repos
        if not r.get("fork")
        and not r.get("archived")
        and r["name"] not in EXCLUDE
        # App Store 掲載アプリのリポジトリも活動があれば普通に出す（固定枠とは別物）
        # 説明も言語もないリポジトリは実質空の置き場なので除外する
        and ((r.get("description") or "").strip() or r.get("language"))
    ][:MAX_ITEMS]
    if not picks:
        return f"_(no recent activity)_\n\n{checked_caption()}"
    header = (
        "  <tr>\n"
        '    <th align="left">Project</th>\n'
        '    <th align="left">Description</th>\n'
        '    <th align="left">Links</th>\n'
        "  </tr>"
    )
    rows = [header] + [format_row(r) for r in picks]
    return "<table>\n" + "\n".join(rows) + "\n</table>\n\n" + checked_caption()


def splice(text: str, start: str, end: str, block: str) -> str:
    if start not in text or end not in text:
        sys.exit(f"markers {start} / {end} not found in README")
    before = text.split(start)[0]
    after = text.split(end)[1]
    return f"{before}{start}\n{block}\n{end}{after}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=("apps", "recent"),
        help="指定したセクションだけ再生成する（省略時は両方）",
    )
    only = parser.parse_args().only

    text = README.read_text(encoding="utf-8")
    updated = text
    if only in (None, "apps"):
        # アプリ欄は iTunes API のみで完結（GitHub アクセス不要）
        updated = splice(updated, APPS_START, APPS_END, build_apps())
    if only in (None, "recent"):
        # 直近活動はリポジトリ一覧が必要（private を含むため PAT が要る）
        updated = splice(updated, RECENT_START, RECENT_END, build_recent(fetch_repos()))

    if updated != text:
        README.write_text(updated, encoding="utf-8")
        print("README.md updated")
    else:
        print("no change")


if __name__ == "__main__":
    main()
