#!/usr/bin/env python3
"""
個人別チケット売上画像生成プログラム (3-Slice 縦可変長対応)

bg-top.png, bg-loop.png, bg-bottom.png を使用し、
売上件数(行数)に応じて画像を縦方向にシームレスに拡張して個人別チケット売上画像を生成します。
"""

import os
import sys
import re
import math
import shutil
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, List, Tuple, Callable

from PIL import Image, ImageDraw, ImageFont

# スプレッドシート取得関数を利用
from fetch_processed_sheets import fetch_all_processed_data

# =========================================================
# 設定定数
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output_images")

WIDTH = 640
DEFAULT_SLICE_HEIGHT = 320

TEXT_COLOR = "#000000"
STROKE_COLOR = "#FFFFFF"

TITLE_FONT_SIZE = 34
TEXT_FONT_SIZE = 22
TOTAL_FONT_SIZE = 30

LINE_HEIGHT = 37        # 1行あたりの高さ (フォントを縮小せず固定)
LIST_START_Y = 190      # 明細リスト描画の開始Y座標
MIN_BOTTOM_MARGIN = 100 # 明細と「合計」フッターとの間の最小マージン(px)


# =========================================================
# 背景画像パス探索
# =========================================================

def find_bg_image_path(filename: str) -> Optional[str]:
    """背景画像ファイルを複数の候補ディレクトリから探索"""
    candidates = [
        os.path.join(BASE_DIR, "media", "image", filename),
        os.path.join(BASE_DIR, "media", "images", filename),
        os.path.join(BASE_DIR, "media", filename),
        os.path.join(BASE_DIR, filename),
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.isfile(p):
            return p
    return None


def get_available_fonts() -> List[Dict[str, str]]:
    """利用可能なフォント一覧を取得"""
    fonts_dir = os.path.join(BASE_DIR, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    
    fonts = []
    # 1. プロジェクト内 fonts ディレクトリ
    for f in sorted(os.listdir(fonts_dir)):
        if f.lower().endswith((".ttf", ".otf", ".ttc")):
            full_path = os.path.join(fonts_dir, f)
            fonts.append({
                "name": f,
                "path": full_path,
                "is_custom": True
            })

    # 2. システムフォント候補
    sys_candidates = [
        ("IPAexゴシック (Linux)", "/usr/share/fonts/ipa/ipaexg.ttf"),
        ("Noto Sans CJK (Linux)", "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"),
        ("Meiryo (Windows)", "C:/Windows/Fonts/meiryo.ttc"),
        ("MS Gothic (Windows)", "C:/Windows/Fonts/msgothic.ttc"),
        ("Hiragino Sans (macOS)", "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"),
    ]
    for name, p in sys_candidates:
        if os.path.exists(p) and os.access(p, os.R_OK):
            fonts.append({
                "name": name,
                "path": p,
                "is_custom": False
            })

    return fonts


def resolve_font_path(custom_font_path: Optional[str] = None) -> str:
    """環境または指定に応じて利用可能なフォントパスを解決"""
    if custom_font_path and os.path.exists(custom_font_path) and os.access(custom_font_path, os.R_OK):
        return custom_font_path

    # 環境変数からの取得
    env_font = os.getenv("SELECTED_FONT_PATH")
    if env_font and os.path.exists(env_font) and os.access(env_font, os.R_OK):
        return env_font

    fonts = get_available_fonts()
    if fonts:
        return fonts[0]["path"]

    return ""


def load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    """指定サイズのフォントオブジェクトを生成"""
    if font_path and os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except Exception as e:
            print(f"[WARN] フォント読み込み失敗 ({font_path}): {e}")
    return ImageFont.load_default()


# =========================================================
# 背景スライス画像の読み込み
# =========================================================

def load_bg_slices() -> Tuple[Image.Image, Image.Image, Image.Image]:
    """bg-top, bg-loop, bg-bottom を読み込み（未検出時は白画像）"""
    top_path = find_bg_image_path("bg-top.png")
    loop_path = find_bg_image_path("bg-loop.png")
    bottom_path = find_bg_image_path("bg-bottom.png")

    # Top
    if top_path:
        top_img = Image.open(top_path).convert("RGBA").resize((WIDTH, DEFAULT_SLICE_HEIGHT), Image.Resampling.LANCZOS)
    else:
        top_img = Image.new("RGBA", (WIDTH, DEFAULT_SLICE_HEIGHT), color=(255, 255, 255, 255))

    # Loop
    if loop_path:
        loop_img = Image.open(loop_path).convert("RGBA").resize((WIDTH, DEFAULT_SLICE_HEIGHT), Image.Resampling.LANCZOS)
    else:
        loop_img = Image.new("RGBA", (WIDTH, DEFAULT_SLICE_HEIGHT), color=(255, 255, 255, 255))

    # Bottom
    if bottom_path:
        bottom_img = Image.open(bottom_path).convert("RGBA").resize((WIDTH, DEFAULT_SLICE_HEIGHT), Image.Resampling.LANCZOS)
    else:
        bottom_img = Image.new("RGBA", (WIDTH, DEFAULT_SLICE_HEIGHT), color=(255, 255, 255, 255))

    return top_img, loop_img, bottom_img


# =========================================================
# ユーティリティ
# =========================================================

def format_number(value: Any) -> str:
    """数値をきれいにフォーマット (例: 1.0 -> '1')"""
    try:
        val = float(value)
        if val.is_integer():
            return str(int(val))
        return f"{val:.2f}".rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return str(value)


def safe_filename(name: str) -> str:
    """ファイル名として使用できない文字を置換"""
    invalid_chars = r'\/:*?"<>|'
    for ch in invalid_chars:
        name = name.replace(ch, "_")
    return name.strip()


def build_dynamic_background(
    top_img: Image.Image,
    loop_img: Image.Image,
    bottom_img: Image.Image,
    num_rows: int
) -> Tuple[Image.Image, int]:
    """
    明細行数に応じて Top + (Loop × N) + Bottom を縦に連結した背景画像を生成
    :return: (生成された合成画像, 全体の高さ)
    """
    top_w, top_h = top_img.size
    loop_w, loop_h = loop_img.size
    bottom_w, bottom_h = bottom_img.size

    # 明細リストの最終Y座標
    last_item_bottom_y = LIST_START_Y + max(num_rows, 1) * LINE_HEIGHT
    needed_height = last_item_bottom_y + MIN_BOTTOM_MARGIN

    base_height = top_h + bottom_h
    extra_height = needed_height - base_height

    if extra_height <= 0:
        num_loops = 0
    else:
        num_loops = math.ceil(extra_height / loop_h)

    total_height = top_h + (num_loops * loop_h) + bottom_h

    bg_canvas = Image.new("RGBA", (WIDTH, total_height), color=(255, 255, 255, 255))

    # 1. Top を貼り付け
    bg_canvas.paste(top_img, (0, 0), mask=top_img if top_img.mode == 'RGBA' else None)

    # 2. Loop を num_loops 回貼り付け
    current_y = top_h
    for _ in range(num_loops):
        bg_canvas.paste(loop_img, (0, current_y), mask=loop_img if loop_img.mode == 'RGBA' else None)
        current_y += loop_h

    # 3. Bottom を末尾に貼り付け
    bg_canvas.paste(bottom_img, (0, current_y), mask=bottom_img if bottom_img.mode == 'RGBA' else None)

    return bg_canvas.convert("RGB"), total_height


# =========================================================
# 個人別画像生成ロジック
# =========================================================

def generate_person_image(
    member_name: str,
    display_name: str,
    person_tickets: List[Dict[str, Any]],
    bg_slices: Tuple[Image.Image, Image.Image, Image.Image],
    output_dir: str,
    fonts: Dict[str, ImageFont.FreeTypeFont]
) -> Optional[str]:
    """1人分のチケット売上画像を可変長で生成して保存"""
    if not display_name:
        display_name = member_name

    if not display_name:
        return None

    # 種別 × 購入者 で集計
    grouped_counts = defaultdict(float)
    for t in person_tickets:
        kind = str(t.get("種別", "")).strip()
        buyer = str(t.get("購入者", "")).strip()
        try:
            count = float(t.get("数", 0))
        except (ValueError, TypeError):
            count = 0.0
        grouped_counts[(kind, buyer)] += count

    total_count = sum(grouped_counts.values())
    grouped_list = [
        {"種別": k[0], "購入者": k[1], "数": v}
        for k, v in grouped_counts.items()
    ]

    top_img, loop_img, bottom_img = bg_slices
    img, total_height = build_dynamic_background(top_img, loop_img, bottom_img, len(grouped_list))
    draw = ImageDraw.Draw(img)

    title_font = fonts.get("title", load_font("", TITLE_FONT_SIZE))
    text_font = fonts.get("text", load_font("", TEXT_FONT_SIZE))
    total_font = fonts.get("total", load_font("", TOTAL_FONT_SIZE))

    # 1. メンバー名（タイトル）: Top部分 (90, 130)
    draw.text(
        (90, 130),
        display_name,
        font=title_font,
        fill=TEXT_COLOR,
        stroke_width=4,
        stroke_fill=STROKE_COLOR
    )

    # 2. 内訳リスト: 固定フォントサイズで全件をゆったり描画
    y = LIST_START_Y
    for row in grouped_list:
        line = f"{row['種別']}  {row['購入者']} 様  {format_number(row['数'])}枚"
        draw.text(
            (100, y),
            line,
            font=text_font,
            fill=TEXT_COLOR,
            stroke_width=3,
            stroke_fill=STROKE_COLOR
        )
        y += LINE_HEIGHT

    # 3. 右下の合計枚数: 一番下の Bottom 部分
    total_text = f"合計 {format_number(total_count)}枚"
    bbox = draw.textbbox((0, 0), total_text, font=total_font, stroke_width=4)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    total_x = WIDTH - text_width - 25
    total_y = total_height - text_height - 20

    draw.text(
        (total_x, total_y),
        total_text,
        font=total_font,
        fill=TEXT_COLOR,
        stroke_width=4,
        stroke_fill=STROKE_COLOR
    )

    # 4. 画像保存
    save_filename = safe_filename(f"{display_name}.png")
    save_path = os.path.join(output_dir, save_filename)
    img.save(save_path, format="PNG")
    return save_path


# =========================================================
# 一括画像生成処理
# =========================================================

def generate_all_personal_images(
    ticket_data: List[Dict[str, Any]],
    member_data: List[Dict[str, Any]],
    output_dir: str = OUTPUT_DIR,
    font_path: Optional[str] = None,
    max_workers: int = 4,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> List[str]:
    """全メンバーの売上画像を一括生成"""
    os.makedirs(output_dir, exist_ok=True)
    bg_slices = load_bg_slices()

    resolved_font = resolve_font_path(font_path)
    fonts = {
        "title": load_font(resolved_font, TITLE_FONT_SIZE),
        "text": load_font(resolved_font, TEXT_FONT_SIZE),
        "total": load_font(resolved_font, TOTAL_FONT_SIZE),
    }

    # 「名前」でチケットをグループ化（カンマ区切り複数人名の場合は人数で均等分割）
    grouped_people = defaultdict(list)
    for row in ticket_data:
        raw_name = str(row.get("名前", "")).strip()
        if not raw_name:
            continue

        names = [n.strip() for n in re.split(r'[,，]', raw_name) if n.strip()]
        if not names:
            continue

        try:
            total_count = float(row.get("数", 0))
        except (ValueError, TypeError):
            total_count = 0.0

        split_count = total_count / len(names)

        for n in names:
            person_row = dict(row)
            person_row["名前"] = n
            person_row["数"] = split_count
            grouped_people[n].append(person_row)

    generated_files = []
    total_members = len(member_data)
    print(f"[INFO] メンバー数: {total_members} 名の可変長画像生成を開始します (並列数={max_workers}, フォント={resolved_font})...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for m in member_data:
            orig_name = str(m.get("NAME", "")).strip()
            if not orig_name:
                continue
            
            disp_name = str(m.get("SN", "")).strip() or orig_name
            person_tickets = grouped_people.get(orig_name, [])

            futures.append(
                executor.submit(
                    generate_person_image,
                    orig_name,
                    disp_name,
                    person_tickets,
                    bg_slices,
                    output_dir,
                    fonts
                )
            )

        for idx, future in enumerate(futures, 1):
            result = future.result()
            if result:
                generated_files.append(result)
            if progress_callback:
                progress_callback(idx, total_members, os.path.basename(result) if result else "")

    print(f"[SUCCESS] 合計 {len(generated_files)} 件の個人別画像を '{output_dir}' に生成しました。")
    return generated_files


def create_zip_archive(source_dir: str, zip_filepath: str) -> str:
    """生成した画像ディレクトリをZIPアーカイブ化"""
    with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_name in sorted(os.listdir(source_dir)):
            if file_name.lower().endswith(".png"):
                file_path = os.path.join(source_dir, file_name)
                zipf.write(file_path, arcname=file_name)
    print(f"[SUCCESS] ZIPファイルを作成しました: '{zip_filepath}'")
    return zip_filepath


import json
import argparse

def write_progress_file(progress_file: Optional[str], data: Dict[str, Any]):
    """進捗状態をJSONファイルに安全に書き出し"""
    if not progress_file:
        return
    try:
        os.makedirs(os.path.dirname(os.path.abspath(progress_file)), exist_ok=True)
        tmp_file = f"{progress_file}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, progress_file)
    except Exception:
        pass


def run_full_generation_process(
    font_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    progress_file: Optional[str] = None
) -> Dict[str, Any]:
    """スプレッドシート取得から画像生成、ZIP化までを一括実行して結果辞書を返す"""
    write_progress_file(progress_file, {
        "is_generating": True,
        "status": "running",
        "message": "スプレッドシート(Ticket / Members)からデータを読み込んでいます...",
        "progress_current": 0,
        "progress_total": 0,
        "progress_percent": 0,
        "error_message": None,
        "last_result": None
    })

    try:
        raw_data = fetch_all_processed_data(as_records=True)
        ticket_records = raw_data.get("Ticket", [])
        member_records = raw_data.get("Members", [])

        if not ticket_records:
            raise ValueError("Ticket シートからデータを取得できませんでした。")
        if not member_records:
            raise ValueError("Members シートからデータを取得できませんでした。")

        member_data_clean = [m for m in member_records if m.get("NAME")]
        total_m = len(member_data_clean)

        def _combined_callback(curr: int, tot: int, filename: str):
            pct = int((curr / tot) * 100) if tot > 0 else 0
            if progress_callback:
                progress_callback(curr, tot, filename)
            write_progress_file(progress_file, {
                "is_generating": True,
                "status": "running",
                "message": f"画像を生成中 ({curr}/{tot}): {filename}",
                "progress_current": curr,
                "progress_total": tot,
                "progress_percent": pct,
                "error_message": None,
                "last_result": None
            })

        generated = generate_all_personal_images(
            ticket_data=ticket_records,
            member_data=member_data_clean,
            output_dir=OUTPUT_DIR,
            font_path=font_path,
            progress_callback=_combined_callback
        )

        zip_path = os.path.join(BASE_DIR, "personal_images.zip")
        create_zip_archive(OUTPUT_DIR, zip_path)

        result = {
            "success": True,
            "count": len(generated),
            "ticket_count": len(ticket_records),
            "member_count": len(member_data_clean),
            "zip_path": zip_path,
            "zip_size": os.path.getsize(zip_path) if os.path.exists(zip_path) else 0
        }

        write_progress_file(progress_file, {
            "is_generating": False,
            "status": "success",
            "message": f"完了！ {len(generated)} 名分の画像を正常に生成しZIPを作成しました。",
            "progress_current": total_m,
            "progress_total": total_m,
            "progress_percent": 100,
            "error_message": None,
            "last_result": result
        })

        return result

    except Exception as e:
        write_progress_file(progress_file, {
            "is_generating": False,
            "status": "error",
            "message": f"エラーが発生しました: {e}",
            "progress_current": 0,
            "progress_total": 0,
            "progress_percent": 0,
            "error_message": str(e),
            "last_result": None
        })
        raise e


# =========================================================
# メイン実行
# =========================================================

def main():
    parser = argparse.ArgumentParser(description="個人別チケット売上画像生成")
    parser.add_argument("--font", type=str, default="", help="使用するフォントパス")
    parser.add_argument("--progress-file", type=str, default="", help="進捗出力先JSONパス")
    args = parser.parse_args()

    print("=" * 60)
    print(" 個人別チケット売上画像生成プログラム (3-Slice 縦可変長)")
    print("=" * 60)
    try:
        res = run_full_generation_process(
            font_path=args.font if args.font else None,
            progress_file=args.progress_file if args.progress_file else None
        )
        print("\n" + "=" * 60)
        print(f"完了! 生成件数: {res['count']} 件")
        print(f"ZIPアーカイブ: {res['zip_path']} ({res['zip_size']} bytes)")
        print("=" * 60)
    except Exception as e:
        print(f"\n[ERROR] 実行失敗: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
