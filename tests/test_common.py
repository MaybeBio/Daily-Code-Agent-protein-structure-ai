import os, json
from scripts import common

def test_load_config_has_required_keys(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("topic: demo\ntitle: Demo\nllm:\n  concurrency: 8\n")
    cfg = common.load_config(str(p))
    assert cfg["topic"] == "demo"
    assert cfg["llm"]["concurrency"] == 8

def test_dump_json_creates_parents(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", str(tmp_path))
    path = common.data_dir("daily", "x.json")
    common.dump_json(path, {"k": 1})
    assert json.load(open(path))["k"] == 1


def test_dump_json_keeps_old_content_when_write_fails(tmp_path, monkeypatch):
    """增量落盘可能被 SIGTERM 打断:写一半不能把上一版有效文件弄坏。"""
    path = tmp_path / "x.json"
    common.dump_json(str(path), {"v": 1})

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(common.json, "dump", boom)
    try:
        common.dump_json(str(path), {"v": 2})
    except OSError:
        pass
    assert common.load_json(str(path)) == {"v": 1}
    assert not (tmp_path / "x.json.tmp").exists()      # 临时文件要清理
