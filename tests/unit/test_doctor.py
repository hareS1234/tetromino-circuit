from tools.doctor import is_under


def test_is_under_resolves_directory_aliases(tmp_path):
    real_bin = tmp_path / "private" / "var" / "suite" / "bin"
    real_bin.mkdir(parents=True)
    alias = tmp_path / "var"
    alias.symlink_to(tmp_path / "private" / "var", target_is_directory=True)

    assert is_under(str(alias / "suite" / "bin" / "yosys"), real_bin)
    assert not is_under(str(alias / "somewhere-else" / "yosys"), real_bin)
