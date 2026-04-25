try:
    from tree_sitter_language_pack import get_language, get_parser

    USING_TSL_PACK = True
except ImportError:
    from tree_sitter_languages import get_language, get_parser

    USING_TSL_PACK = False

__all__ = [get_parser, get_language, USING_TSL_PACK]
