"""命令行入口。

子命令：
  check     校验原始材料并打印解析出的意见与冲突预检
  plan      生成一份联合试唱方案（总报告、分谱、总览、JSON 清单）
  scores    只输出各声部分谱
  trace     针对某条更正笔记输出重练定位
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .corpus import Corpus
from .planner import Planner
from .render import (
    render_conductor_report,
    render_manifest,
    render_part_score,
    render_piano_overview,
    render_repractice_note,
)


def _load(data_dir: Path) -> Corpus:
    if not data_dir.exists():
        raise SystemExit(f"资料目录不存在：{data_dir}")
    return Corpus.load(data_dir)


def cmd_check(args) -> int:
    corpus = _load(Path(args.data_dir))
    planner = Planner(corpus)
    opinions = planner.parser.parse_all(corpus.notes)
    print(f"资料加载完成：{len(corpus.bars)} 行谱面、{len(corpus.lyrics)} 条曲词、"
          f"{len(corpus.readings)} 条读音、{len(corpus.notes)} 条笔记")
    print("解析出的结构化意见：")
    for opinion in opinions:
        scope = f"{opinion.voice}/{opinion.section or '段未指明'}"
        extra = " ".join(x for x in (opinion.surface, opinion.region) if x)
        print(f"  [{opinion.note_id}] at={opinion.at} {opinion.teacher} "
              f"{scope} {opinion.action.value} {extra}")
    plan = planner.make_plan()
    errors = [i for i in plan.issues if i.level.value == "error"]
    warnings_ = [i for i in plan.issues if i.level.value == "warning"]
    print(f"\n预检：{len(errors)} 个阻断问题，{len(warnings_)} 个语义提示")
    for issue in plan.issues:
        print(f"  {issue.level.value.upper()} {issue.code}：{issue.message}")
    return 0


def cmd_plan(args) -> int:
    corpus = _load(Path(args.data_dir))
    planner = Planner(corpus)
    plan = planner.make_plan(selection_seq=args.selection)
    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    report = render_conductor_report(plan, corpus)
    overview = render_piano_overview(plan, corpus)
    manifest = render_manifest(plan, corpus)

    if out_dir:
        (out_dir / "conductor_report.txt").write_text(report, encoding="utf-8")
        (out_dir / "piano_overview.txt").write_text(overview, encoding="utf-8")
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for voice in corpus.voices:
            score_text = render_part_score(plan, corpus, voice)
            (out_dir / f"part_{voice}.txt").write_text(score_text, encoding="utf-8")
        print(f"方案 {plan.selection_id} 已写入 {out_dir}/（总报告、总览、分谱、manifest.json）")
        if not plan.usable:
            print("注意：本次无法组成可用新版，已认可的其他段仍可发给学员。")
    else:
        print(report)
        print()
        print(overview)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if plan.usable else 2


def cmd_scores(args) -> int:
    corpus = _load(Path(args.data_dir))
    plan = Planner(corpus).make_plan(selection_seq=args.selection)
    for voice in corpus.voices:
        print(render_part_score(plan, corpus, voice))
        print()
    return 0


def cmd_trace(args) -> int:
    corpus = _load(Path(args.data_dir))
    planner = Planner(corpus)
    plan = planner.make_plan(selection_seq=args.selection)
    trace = planner.trace_correction(plan, args.note)
    if args.json:
        print(json.dumps(trace, ensure_ascii=False, indent=2))
    else:
        print(render_repractice_note(trace))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hechang",
        description="声乐试唱的词格、合唱对齐与分谱交接工具",
    )
    parser.add_argument("--version", action="version", version=f"hechang {__version__}")
    parser.add_argument("-d", "--data-dir", default="data", help="交换资料目录（默认 data）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="校验资料并预览意见解析与冲突").set_defaults(func=cmd_check)

    p_plan = sub.add_parser("plan", help="生成联合试唱方案")
    p_plan.add_argument("-o", "--out", help="输出目录；不填则打印到标准输出")
    p_plan.add_argument("--selection", type=int, default=2, help="方案选择序号（默认 SEL-2）")
    p_plan.set_defaults(func=cmd_plan)

    p_scores = sub.add_parser("scores", help="输出各声部分谱")
    p_scores.add_argument("--selection", type=int, default=2)
    p_scores.set_defaults(func=cmd_scores)

    p_trace = sub.add_parser("trace", help="定位更正笔记要求重练的位置")
    p_trace.add_argument("note", help="笔记 id，如 N5")
    p_trace.add_argument("--json", action="store_true", help="输出 JSON")
    p_trace.add_argument("--selection", type=int, default=2)
    p_trace.set_defaults(func=cmd_trace)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
