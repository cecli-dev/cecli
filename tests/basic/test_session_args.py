"""CLI args for session encryption and auto-save."""

from cecli.args import get_parser


def test_session_encrypt_defaults_off():
    parser = get_parser([], "/tmp/project")
    args = parser.parse_args([])
    assert args.session_encrypt is False
    assert args.session_key_file is None
    assert args.auto_save is True
    assert args.auto_load is False
    assert args.auto_save_session_name == "auto-save"


def test_session_encrypt_flag():
    parser = get_parser([], "/tmp/project")
    args = parser.parse_args(["--session-encrypt"])
    assert args.session_encrypt is True


def test_session_encrypt_no_flag():
    parser = get_parser([], "/tmp/project")
    args = parser.parse_args(["--no-session-encrypt"])
    assert args.session_encrypt is False


def test_session_key_file_flag():
    parser = get_parser([], "/tmp/project")
    args = parser.parse_args(["--session-key-file", "/tmp/key.bin"])
    assert args.session_key_file == "/tmp/key.bin"
