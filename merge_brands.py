"""
CLI 入口 - 多中心点搜索结果合并、品牌聚合、Excel 分组明细导出

用法：
    python merge_brands.py                     # 扫描 output/ 下所有商家 CSV
    python merge_brands.py <input_dir>         # 指定输入目录
    python merge_brands.py <input_dir> <output.xlsx>

说明：
    - 输入为抓取生成的商家 CSV（中文表头），自动排除 search_history.csv
    - 按 (门店名称, 地址) 联合去重（同名不同址的分店不会被误删）
    - 品牌名 = 门店名称括号前文本；「同名门店数量」为合并后全局统计
    - 输出 Excel：第1列品牌序号、第2列品牌名(合并)、第3列门店数(合并)、其后门店明细
"""

import argparse
import logging
import os
import sys

from amap_agent.merger import run_merge

logger = logging.getLogger(__name__)


def collect_csv_files(input_dir: str) -> list:
    """收集目录下所有商家 CSV（排除 search_history.csv 与合并输出）"""
    if not os.path.isdir(input_dir):
        print(f"[错误] 输入目录不存在: {input_dir}")
        return []
    paths = []
    for fname in sorted(os.listdir(input_dir)):
        if not fname.lower().endswith(".csv"):
            continue
        if fname == "search_history.csv" or fname.startswith("merged_brands"):
            continue
        paths.append(os.path.join(input_dir, fname))
    return paths


def setup_logging() -> None:
    """控制台 WARNING 及以上，便于排查"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger(__name__).setLevel(logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="多中心点搜索结果合并 + 品牌聚合 + Excel 分组明细导出"
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default="output",
        help="输入 CSV 目录（默认 output/）",
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        default=None,
        help="输出 .xlsx 路径（默认 output/merged_brands_{日期}.xlsx）",
    )
    args = parser.parse_args()

    setup_logging()

    paths = collect_csv_files(args.input_dir)
    if not paths:
        print(f"[错误] 在「{args.input_dir}」未找到任何商家 CSV 文件")
        sys.exit(1)

    print(f"[进度] 找到 {len(paths)} 个 CSV 文件，开始合并...")
    result = run_merge(paths, output_dir=args.input_dir, output_path=args.output_path)

    if not result.get("success"):
        print(f"[错误] {result.get('error', '未知错误')}")
        sys.exit(1)

    stats = result["stats"]
    print(f"[完成] {result['message']}")
    print(
        f"[统计] 文件 {stats['source_files']} 个 | "
        f"去重前 {stats['total_before_dedupe']} 条 | "
        f"去除重复 {stats['removed_duplicates']} 条 | "
        f"去重后 {stats['total_after_dedupe']} 条 | "
        f"品牌 {stats['brand_count']} 个"
    )


if __name__ == "__main__":
    main()
