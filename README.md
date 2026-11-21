# 声乐试唱的词格、合唱与分谱交接

声乐研修的模拟唱词、谱面拍位和分声部排练笔记。材料中的人、机构及经营记录是合成的。

每份资料为 UTF-8 JSON 数组。id 在同一份资料内唯一，原始文字按收到的形式保留。

- `data/score.json`。排练总谱的结构交换记录。bar 为小节号，slots 明列拍位和能否承载新音节。shared 是需要使用同一拍位的合唱标记。
- `data/words.json`。试歌曲词与地区读音简表。stress 为从一计的重音音节序号。words 内按 voice、bar 定位，同一曲词可以重复。
- `data/notes.json`。分排笔记，at 的顺序是提交时间。带 approval 的是分排确认回执，不代表合唱总排已确认。

使用 Python 3.11 标准库，无需安装软件包或连接外部服务。

以下命令分别读取一份原始资料、检查资料中的字段与关联。

```sh
python3 -m json.tool data/score.json
python3 -m unittest discover -s tests -v
```
