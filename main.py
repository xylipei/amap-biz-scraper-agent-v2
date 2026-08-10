"""
CLI入口 - 高德地图区域商家信息抓取Agent

用法：
    python main.py <你的输入>
    或
    python main.py （交互模式）

示例：
    python main.py 北京海淀区 星巴克

防跑偏要求（PRD 5.3）：
- 配置日志模块，记录关键节点
- 控制台有进度提示
- 全局异常捕获，不抛堆栈报错
"""

import logging
import sys
from typing import NoReturn

from amap_agent.agent import run


def setup_logging() -> None:
    """
    配置日志系统。

    日志输出到文件 + 控制台（仅WARNING及以上显示）。
    文件记录详细信息，控制台显示进度和结果。
    """
    import os
    from datetime import datetime

    # 创建日志目录
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    # 日志文件名包含时间戳
    log_file = os.path.join(
        log_dir,
        f"amap_agent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
    )

    # 根日志记录器配置
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 文件处理器：记录所有级别
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # 控制台处理器：仅WARNING及以上
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    logging.getLogger(__name__).info("日志系统初始化完成: %s", log_file)


def main() -> NoReturn:
    """主入口"""
    setup_logging()
    logger = logging.getLogger(__name__)

    # 解析用户输入
    if len(sys.argv) > 1:
        # 从命令行参数读取
        user_input = " ".join(sys.argv[1:])
    else:
        # 交互模式
        print("=" * 50)
        print("高德地图区域商家信息抓取Agent")
        print("=" * 50)
        print("请输入您的需求（例如：北京海淀区 星巴克）")
        print("输入 q 或 quit 退出")
        print("-" * 50)
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            sys.exit(0)

        if user_input.lower() in ("q", "quit", "exit", ""):
            print("再见！")
            sys.exit(0)

    logger.info("用户输入: %s", user_input)

    # 执行Agent
    try:
        result = run(user_input)

        if result.get("success"):
            if result.get("statistics") and result["statistics"].get("total", 0) == 0:
                print(f"\n{result.get('result', '未找到相关商家')}")
            elif result.get("file_path"):
                print(f"\n[OK] 任务完成！文件已保存至: {result['file_path']}")
            else:
                print(f"\n{result.get('result', '任务完成')}")
        else:
            if result.get("ask_for_input"):
                print(f"\n[INFO] {result['ask_for_input']}")
                print("请重新运行程序并补充完整信息。")
            else:
                error_msg = result.get("error", "未知错误")
                print(f"\n[ERROR] 任务失败: {error_msg}")

    except Exception as e:
        # 全局兜底：确保不抛堆栈给用户
        logger.exception("未捕获的全局异常")
        print(f"\n[ERROR] 程序发生意外错误: {e}")
        print("详情请查看日志文件。")
        sys.exit(1)


if __name__ == "__main__":
    main()
