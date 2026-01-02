import argparse


def add_deprecated_model_args(parser, group):
    """Add deprecated model shortcut arguments to the argparse parser."""

    group.add_argument(
        "--opus",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--sonnet",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--haiku",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--4",
        "-4",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--4o",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--mini",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--4-turbo",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--35turbo",
        "--35-turbo",
        "--3",
        "-3",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--deepseek",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--o1-mini",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    group.add_argument(
        "--o1-preview",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )

    #########
    group = parser.add_argument_group("API Keys and Settings (Deprecated)")
    group.add_argument(
        "--openai-api-type",
        help=argparse.SUPPRESS,
    )
    group.add_argument(
        "--openai-api-version",
        help=argparse.SUPPRESS,
    )
    group.add_argument(
        "--openai-api-deployment-id",
        help=argparse.SUPPRESS,
    )
    group.add_argument(
        "--openai-organization-id",
        help=argparse.SUPPRESS,
    )

    #########
    group = parser.add_argument_group("History Files (Deprecated)")
    group.add_argument(
        "--llm-history-file",
        help=argparse.SUPPRESS,
    )

    ##########
    group = parser.add_argument_group("Analytics")
    group.add_argument(
        "--analytics",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=argparse.SUPPRESS,
    )
    group.add_argument(
        "--analytics-log",
        metavar="ANALYTICS_LOG_FILE",
        help=argparse.SUPPRESS,
    )
    group.add_argument(
        "--analytics-disable",
        action="store_true",
        help=argparse.SUPPRESS,
        default=False,
    )
    group.add_argument(
        "--analytics-posthog-host",
        metavar="ANALYTICS_POSTHOG_HOST",
        help=argparse.SUPPRESS,
    )
    group.add_argument(
        "--analytics-posthog-project-api-key",
        metavar="ANALYTICS_POSTHOG_PROJECT_API_KEY",
        help=argparse.SUPPRESS,
    )


def handle_deprecated_model_args(args, io):
    """Handle deprecated model shortcut arguments and provide appropriate warnings."""
    # Define model mapping
    model_map = {
        "opus": "claude-3-opus-20240229",
        "sonnet": "anthropic/claude-3-7-sonnet-20250219",
        "haiku": "claude-3-5-haiku-20241022",
        "4": "gpt-4-0613",
        "4o": "gpt-4o",
        "mini": "gpt-4o-mini",
        "4_turbo": "gpt-4-1106-preview",
        "35turbo": "gpt-3.5-turbo",
        "deepseek": "deepseek/deepseek-chat",
        "o1_mini": "o1-mini",
        "o1_preview": "o1-preview",
    }

    # Check if any deprecated args are used
    for arg_name, model_name in model_map.items():
        arg_name_clean = arg_name.replace("-", "_")
        if hasattr(args, arg_name_clean) and getattr(args, arg_name_clean):
            # Find preferred name to display in warning
            from cecli.models import MODEL_ALIASES

            display_name = model_name
            # Check if there's a shorter alias for this model
            for alias, full_name in MODEL_ALIASES.items():
                if full_name == model_name:
                    display_name = alias
                    break

            # Show the warning
            io.tool_warning(
                f"The --{arg_name.replace('_', '-')} flag is deprecated and will be removed in a"
                f" future version. Please use --model {display_name} instead."
            )

            # Set the model
            if not args.model:
                args.model = model_name
            break
