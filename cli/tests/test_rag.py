"""rag 模块纯函数测试（不联网、不依赖 Chroma）。"""
from pathlib import Path

from novel_agent.rag import chunk_text, classify_type, load_documents


def test_chunk_text_overlap():
    """相邻块重叠 overlap 字。"""
    out = chunk_text("abcdef", size=3, overlap=1)
    assert out == ["abc", "cde", "ef"]


def test_chunk_text_no_overlap():
    out = chunk_text("abcdef", size=2, overlap=0)
    assert out == ["ab", "cd", "ef"]


def test_chunk_text_short_text():
    """短文本返回一块。"""
    assert chunk_text("ab", size=10, overlap=2) == ["ab"]


def test_classify_type():
    # 人物 -> character
    assert classify_type("docs/.../人物.md") == "character"
    # 核心设定 -> setting
    assert classify_type("docs/.../总纲.md") == "setting"
    assert classify_type("docs/.../伏笔地图.md") == "setting"
    assert classify_type("docs/.../时间线地图.md") == "setting"
    assert classify_type("docs/.../写作指令.md") == "setting"
    assert classify_type("docs/.../每章.md") == "setting"
    assert classify_type("docs/.../全书进度表.md") == "setting"
    assert classify_type("docs/.../日常素材.md") == "setting"
    assert classify_type("docs/.../防崩.md") == "setting"
    # 文风基准 -> exemplar
    assert classify_type("docs/.../文风基准/1.txt") == "exemplar"
    # 正文/其它 -> other（正文建索引时已被 NOVEL_INDEX_EXCLUDE 跳过）
    assert classify_type("docs/.../正文/第一卷/x.md") == "other"
    assert classify_type("docs/.../分卷提示词/x.md") == "other"


def test_load_documents(tmp_path):
    """读出目录下 .md/.txt，递归，忽略其它扩展名。"""
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / "b.txt").write_text("world", encoding="utf-8")
    (tmp_path / "c.json").write_text("{}", encoding="utf-8")  # 应被忽略
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.md").write_text("deep", encoding="utf-8")
    docs = load_documents(tmp_path)
    assert dict((Path(p).name, t) for p, t in docs) == {
        "a.md": "hello", "b.txt": "world", "d.md": "deep"
    }


def test_load_documents_exclude(tmp_path):
    """exclude 命中的目录整目录跳过，其余正常读出。"""
    (tmp_path / "总纲.md").write_text("设定", encoding="utf-8")
    zhengwen = tmp_path / "正文" / "第一卷"
    zhengwen.mkdir(parents=True)
    (zhengwen / "001.md").write_text("章节正文", encoding="utf-8")
    docs = load_documents(tmp_path, exclude=["正文"])
    names = [Path(p).name for p, _ in docs]
    assert "总纲.md" in names
    assert "001.md" not in names  # 正文整目录被排除
