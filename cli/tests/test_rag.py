"""rag 模块纯函数测试（不联网、不依赖 Chroma）。"""
import json
from pathlib import Path

from novel_agent.rag import chunk_text, classify_type, load_documents


class FakeCollection:
    """假 Chroma collection：内存存取，支持 upsert/get/delete/count。"""

    def __init__(self):
        self.data = {}  # id -> {"document": str, "metadata": dict}

    def upsert(self, ids, documents, metadatas):
        for i, d, m in zip(ids, documents, metadatas):
            self.data[i] = {"document": d, "metadata": dict(m)}

    def get(self, where=None, **kw):
        ids, metas, docs = [], [], []
        for i, v in self.data.items():
            if not where or all(v["metadata"].get(k) == val for k, val in where.items()):
                ids.append(i)
                metas.append(v["metadata"])
                docs.append(v["document"])
        return {"ids": ids, "metadatas": metas, "documents": docs}

    def delete(self, where=None, ids=None, **kw):
        to_del = set()
        if where:
            for i, v in self.data.items():
                if all(v["metadata"].get(k) == val for k, val in where.items()):
                    to_del.add(i)
        if ids:
            to_del.update(ids)
        for i in to_del:
            self.data.pop(i, None)

    def count(self):
        return len(self.data)


class FakeClient:
    """假 Chroma client。"""

    def __init__(self):
        self.collection = FakeCollection()

    def get_or_create_collection(self, name, embedding_function=None, **kw):
        return self.collection


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
    # 正文/章节 -> chapter（前文参考；rebuild 不索引正文，仅手动 add 的正文走此类型）
    assert classify_type("docs/.../正文/第一卷/x.md") == "chapter"
    # 其它 -> other
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


# ---------- add_document / remove_document ----------
def _store(tmp_path):
    """造一个临时小说目录 + 用 FakeClient 的 RAGStore。"""
    from novel_agent.config import Settings
    from novel_agent.rag import RAGStore
    novel = tmp_path / "novel"
    novel.mkdir()
    settings = Settings(ark_api_key="k", repo_root=tmp_path, novel_dir=str(novel))
    return novel, RAGStore(settings=settings, client=FakeClient())


def test_add_remove_document(tmp_path):
    """add 分块入库（id=文件名_序号，source=绝对路径），remove 按 source 清空。"""
    novel, store = _store(tmp_path)
    (novel / "人物.md").write_text("林晚是女主。" * 200, encoding="utf-8")  # 多块
    n = store.add_document("人物.md", progress=None)
    assert n > 1
    coll = store._collection_obj()
    assert coll.count() == n
    # id 格式：{文件名}_{序号}
    assert all(i.startswith("人物.md_") for i in coll.data)
    # metadata：source 绝对路径，type=character
    src = str(novel / "人物.md")
    assert all(v["metadata"]["source"] == src for v in coll.data.values())
    assert all(v["metadata"]["type"] == "character" for v in coll.data.values())
    # remove：按 source 清空，返回删除数
    assert store.remove_document("人物.md") == n
    assert coll.count() == 0


def test_add_document_replaces_old_blocks(tmp_path):
    """精修后重跑 add：先删旧块再 upsert，块数变化不留孤儿。"""
    novel, store = _store(tmp_path)
    f = novel / "每章.md"
    f.write_text("x" * 1000, encoding="utf-8")  # 多块
    n1 = store.add_document("每章.md", progress=None)
    f.write_text("短", encoding="utf-8")  # 缩成 1 块
    n2 = store.add_document("每章.md", progress=None)
    assert n2 < n1
    assert store._collection_obj().count() == n2  # 无孤儿块


def test_add_document_ignores_exclude(tmp_path):
    """add 不受 NOVEL_INDEX_EXCLUDE 限制：能加正文，且 type=chapter 供前文检索。"""
    novel, store = _store(tmp_path)
    zh = novel / "正文"
    zh.mkdir()
    (zh / "001.md").write_text("正文章节内容。", encoding="utf-8")
    assert store.add_document("正文/001.md", progress=None) >= 1
    coll = store._collection_obj()
    assert all(v["metadata"]["type"] == "chapter" for v in coll.data.values())


def test_add_document_missing_file(tmp_path):
    """加不存在的文件抛 FileNotFoundError。"""
    novel, store = _store(tmp_path)
    try:
        store.add_document("不存在.md", progress=None)
        assert False, "应抛错"
    except FileNotFoundError:
        pass


# ---------- build_index manifest（0.6 rebuild 陈块精确清理）----------
def test_rebuild_first_time_writes_manifest(tmp_path):
    """首建（无 manifest）：不清理直接写块，结束时落 manifest 供下次精确清理。"""
    novel, store = _store(tmp_path)
    (novel / "人物.md").write_text("林晚是女主。" * 100, encoding="utf-8")
    total = store.build_index(progress=None)
    coll = store._collection_obj()
    assert coll.count() == total
    assert all(i.startswith("c") for i in coll.data)  # rebuild 块 id 为 c*
    manifest = novel / ".agent" / "chroma_db" / "rebuild_manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["count"] == total and len(data["ids"]) == total


def test_rebuild_removes_stale_blocks_after_file_deleted(tmp_path):
    """删设定文件后 rebuild：该文件的所有陈块清零，不留孤儿。"""
    novel, store = _store(tmp_path)
    (novel / "人物.md").write_text("甲" * 1000, encoding="utf-8")
    (novel / "总纲.md").write_text("乙" * 500, encoding="utf-8")
    store.build_index(progress=None)
    coll = store._collection_obj()
    assert coll.count() > 0
    src = str(novel / "人物.md")
    (novel / "人物.md").unlink()
    store.build_index(progress=None)
    assert [v for v in coll.data.values() if v["metadata"]["source"] == src] == []
    assert all("人物" not in v["metadata"]["source"] for v in coll.data.values())


def test_rebuild_keeps_chapter_blocks(tmp_path):
    """rebuild 只清自己的 c* 块，index add 写入的章节块原样保留。"""
    novel, store = _store(tmp_path)
    (novel / "人物.md").write_text("甲" * 800, encoding="utf-8")
    store.build_index(progress=None)
    zh = novel / "正文"
    zh.mkdir()
    (zh / "001.md").write_text("章节正文。" * 100, encoding="utf-8")
    n_ch = store.add_document("正文/001.md", progress=None)
    before = {i for i, v in store._collection_obj().data.items()
              if v["metadata"]["type"] == "chapter"}
    assert len(before) == n_ch
    store.build_index(progress=None)  # 再 rebuild
    after = {i for i, v in store._collection_obj().data.items()
             if v["metadata"]["type"] == "chapter"}
    assert after == before  # 章节块一个不少


def test_rebuild_corrupt_manifest_not_fatal(tmp_path):
    """manifest 损坏：当作无清单处理，rebuild 照常完成。"""
    novel, store = _store(tmp_path)
    (novel / "总纲.md").write_text("乙" * 300, encoding="utf-8")
    m = novel / ".agent" / "chroma_db" / "rebuild_manifest.json"
    m.parent.mkdir(parents=True)
    m.write_text("{不是合法JSON", encoding="utf-8")
    total = store.build_index(progress=None)
    assert total > 0
    assert store._collection_obj().count() == total
