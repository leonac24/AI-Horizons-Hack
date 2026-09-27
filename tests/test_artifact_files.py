from core import artifact_files


def test_readers_keep_old_complete_artifact_until_new_artifact_is_published(tmp_path, monkeypatch):
    target = tmp_path / "model.json"
    target.write_text('{"revision": 1}\n', encoding="utf-8")
    real_replace = artifact_files.os.replace

    def inspect_before_publish(source, destination):
        assert target.read_text(encoding="utf-8") == '{"revision": 1}\n'
        assert source.read_text(encoding="utf-8") == '{"revision": 2}\n'
        real_replace(source, destination)

    monkeypatch.setattr(artifact_files.os, "replace", inspect_before_publish)
    artifact_files.replace_text(target, '{"revision": 2}\n')
    assert target.read_text(encoding="utf-8") == '{"revision": 2}\n'
    assert list(tmp_path.iterdir()) == [target]
