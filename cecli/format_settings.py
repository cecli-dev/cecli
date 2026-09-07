import os


def scrub_sensitive_info(args, text):
    # Replace sensitive information with last 4 characters
    if text and args.openai_api_key:
        last_4 = args.openai_api_key[-4:]
        text = text.replace(args.openai_api_key, f"...{last_4}")
    if text and args.anthropic_api_key:
        last_4 = args.anthropic_api_key[-4:]
        text = text.replace(args.anthropic_api_key, f"...{last_4}")
    return text


def format_settings(parser, args):
    show = scrub_sensitive_info(args, parser.format_values())
    # clean up the headings for consistency w/ new lines
    heading_env = "Environment Variables:"
    heading_defaults = "Defaults:"
    if heading_env in show:
        show = show.replace(heading_env, "\n" + heading_env)
        show = show.replace(heading_defaults, "\n" + heading_defaults)
    show += "\n"
    show += "Option settings:\n"
    for arg, val in sorted(vars(args).items()):
        if val:
            val = scrub_sensitive_info(args, str(val))
        show += f"  - {arg}: {val}\n"  # noqa: E221
    # Add environment variables that start with CECLI_
    show += "\nEnvironment variables:\n"
    for env_var, env_val in sorted(os.environ.items()):
        if env_var.startswith("CECLI_"):
            # Scrub sensitive env vars if needed
            if (
                env_var
                in ["CECLI_OPENROUTER_API_KEY", "CECLI_OPENAI_API_KEY", "CECLI_ANTHROPIC_API_KEY"]
                and env_val
            ):
                last_4 = env_val[-4:] if len(env_val) >= 4 else env_val
                env_val = f"...{last_4}"
            show += f"  - {env_var}: {env_val}\n"
    return show
